#!/usr/bin/env python3
"""CLI สำหรับประเมินความแม่นยำ OCR บนชุดข้อมูลจริงในเครื่อง เทียบทุกโหมด
preprocessing กับ ground truth ที่ผู้ใช้เตรียมไว้เอง

สคริปต์นี้:
  - อ่าน manifest CSV (ดูรูปแบบใน evaluation/manifest.example.csv)
  - รันทุกภาพผ่านทุกโหมด preprocessing (หรือเฉพาะโหมดที่ระบุด้วย --modes)
  - ใช้ EasyOCRService เดียวกับที่ /api/ocr ใช้จริง (โหลดโมเดลจริง เว้นแต่ทดสอบ
    ด้วย mock)
  - คำนวณ Character Error Rate (CER) เป็นตัวชี้วัดหลัก และ whitespace-token
    error rate เป็นตัวชี้วัดเสริมเฉพาะข้อความที่เว้นวรรคมีความหมาย
  - พิมพ์สรุปผลแยกตามภาษาและโหมด preprocessing
  - บันทึกผลละเอียดเป็น CSV หรือ JSON ได้ด้วย --output

สคริปต์นี้ไม่ยุ่งเกี่ยวกับ Flask, Serial, หรือ ESP32 เลย - เรียกใช้ EasyOCRService
และ image_preprocessing โดยตรงเท่านั้น

ตัวอย่างการใช้งาน:
    python evaluate_ocr.py --manifest evaluation/manifest.csv
    python evaluate_ocr.py --manifest evaluation/manifest.csv --modes none resize
    python evaluate_ocr.py --manifest evaluation/manifest.csv --output evaluation/results/run1.csv
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Sequence

from image_preprocessing import (
    PREPROCESSING_MODES,
    ImageDecodeError,
    ImageTooLargeError,
    compute_quality_diagnostics,
    preprocess_image,
)
from ocr_evaluation import (
    EvaluationRecord,
    ManifestError,
    ManifestRow,
    MixedDatasetError,
    character_error_rate,
    determine_dataset_label,
    load_manifest,
    normalize_text,
    summarize,
    whitespace_token_error_rate,
    write_records,
)
from ocr_service import EasyOCRService, OCRInitializationError, OCRProcessingError

DEFAULT_MANIFEST = Path("evaluation/manifest.csv")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help=f"ไฟล์ manifest CSV (ค่าเริ่มต้น: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        default=list(PREPROCESSING_MODES),
        choices=PREPROCESSING_MODES,
        help="โหมด preprocessing ที่จะทดสอบ (ค่าเริ่มต้น: ทุกโหมด)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="ไฟล์ผลลัพธ์แบบละเอียดต่อภาพ/โหมด (.csv หรือ .json)",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="ใช้ GPU สำหรับ EasyOCR หากมี (ค่าเริ่มต้นคือ CPU เหมือนกับ production)",
    )
    return parser


def _empty_record(row: ManifestRow, mode: str, error: str) -> EvaluationRecord:
    return EvaluationRecord(
        image_path=row.image_path,
        language=row.language,
        mode=mode,
        ground_truth=row.ground_truth,
        predicted_text="",
        predicted_text_raw="",
        cer=None,
        token_error_rate=None,
        exact_match=False,
        mean_confidence=None,
        processing_seconds=0.0,
        warnings=[],
        error=error,
        variant=row.variant,
        synthetic=row.synthetic,
    )


def run_evaluation(
    rows: Sequence[ManifestRow],
    modes: Sequence[str],
    ocr_service: EasyOCRService,
    base_dir: Path,
) -> list[EvaluationRecord]:
    """รันทุกแถวใน manifest ผ่านทุกโหมดที่ระบุ คืน EvaluationRecord ต่อคู่ (ภาพ, โหมด)

    รับ ocr_service เป็นพารามิเตอร์ (dependency injection) เพื่อให้เทสต์ส่ง mock
    เข้ามาแทนได้โดยไม่ต้องดาวน์โหลดโมเดลจริง
    """
    records: list[EvaluationRecord] = []

    for row in rows:
        image_path = row.resolve_image_path(base_dir)
        if not image_path.is_file():
            for mode in modes:
                records.append(_empty_record(row, mode, f"ไม่พบไฟล์ภาพ: {image_path}"))
            continue

        image_bytes = image_path.read_bytes()

        for mode in modes:
            start = time.perf_counter()
            try:
                array, _info = preprocess_image(image_bytes, mode=mode)
                quality = compute_quality_diagnostics(array)
                result = ocr_service.recognize(array)
            except (ImageDecodeError, ImageTooLargeError) as exc:
                records.append(_empty_record(row, mode, f"เตรียมภาพไม่สำเร็จ: {exc}"))
                continue
            except (OCRInitializationError, OCRProcessingError) as exc:
                records.append(_empty_record(row, mode, f"OCR ล้มเหลว: {exc}"))
                continue

            elapsed = time.perf_counter() - start
            predicted_raw = result.get("text", "")
            predicted_normalized = normalize_text(predicted_raw)
            ground_truth_normalized = normalize_text(row.ground_truth)

            records.append(
                EvaluationRecord(
                    image_path=row.image_path,
                    language=row.language,
                    mode=mode,
                    ground_truth=row.ground_truth,
                    predicted_text=predicted_normalized,
                    predicted_text_raw=predicted_raw,
                    cer=character_error_rate(predicted_raw, row.ground_truth),
                    token_error_rate=whitespace_token_error_rate(predicted_raw, row.ground_truth),
                    exact_match=(predicted_normalized == ground_truth_normalized),
                    mean_confidence=result.get("mean_confidence"),
                    processing_seconds=elapsed,
                    warnings=list(quality.warnings),
                    error=None,
                    variant=row.variant,
                    synthetic=row.synthetic,
                )
            )

    return records


def _format_percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _format_seconds(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}s"


def _print_group_table(title: str, groups: dict[str, dict]) -> None:
    print(f"\n{title}")
    header = f"  {'กลุ่ม':<18}{'จำนวน':>8}{'สำเร็จ':>8}{'ล้มเหลว':>9}{'CER เฉลี่ย':>12}{'CER มัธยฐาน':>14}{'ตรงทุกตัว':>11}{'เวลาเฉลี่ย':>12}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, stats in groups.items():
        print(
            f"  {name:<18}"
            f"{stats['sample_count']:>8}"
            f"{stats['success_count']:>8}"
            f"{stats['failure_count']:>9}"
            f"{_format_percent(stats['mean_cer']):>12}"
            f"{_format_percent(stats['median_cer']):>14}"
            f"{_format_percent(stats['exact_match_rate']):>11}"
            f"{_format_seconds(stats['mean_processing_seconds']):>12}"
        )


_DATASET_LABEL_THAI = {
    "synthetic": "SYNTHETIC (สังเคราะห์ - ไม่ใช่ภาพถ่ายจริง)",
    "real_camera": "REAL_CAMERA (ภาพถ่ายจริง)",
    "unknown": "UNKNOWN (ไม่ทราบประเภท)",
}


def print_summary(summary: dict, dataset_label: str) -> None:
    overall = summary["overall"]
    print("=" * 70)
    print(f"ประเภทชุดข้อมูล: {_DATASET_LABEL_THAI.get(dataset_label, dataset_label)}")
    print("สรุปผลการประเมิน OCR (CER = Character Error Rate, ตัวชี้วัดหลัก)")
    print("=" * 70)
    if dataset_label == "synthetic":
        print(
            "คำเตือน: นี่คือผลจากชุดข้อมูลสังเคราะห์ (render จากฟอนต์ + จำลองสภาพกล้อง) "
            "ใช้เพื่อตรวจสอบ pipeline เท่านั้น ห้ามใช้แทนหรือรวมกับผลชุดภาพถ่ายจริง "
            "และห้ามใช้สรุปว่าโหมด preprocessing ใด 'เหมาะกับ production' โดยไม่มี "
            "หลักฐานจากชุดภาพถ่ายจริงยืนยันด้วย (ดู evaluation/synthetic/README.md)"
        )
    print(f"จำนวนตัวอย่างทั้งหมด (ภาพ x โหมด): {overall['sample_count']}")
    print(f"สำเร็จ: {overall['success_count']}  ล้มเหลว: {overall['failure_count']}")
    print(f"CER เฉลี่ย: {_format_percent(overall['mean_cer'])}  CER มัธยฐาน: {_format_percent(overall['median_cer'])}")
    print(f"อัตราตรงทุกตัวอักษร (exact match): {_format_percent(overall['exact_match_rate'])}")
    print(f"เวลาประมวลผลเฉลี่ยต่อภาพ: {_format_seconds(overall['mean_processing_seconds'])}")

    _print_group_table("แยกตามภาษา (ตามคอลัมน์ language ใน manifest)", summary["by_language"])
    _print_group_table("แยกตามโหมด preprocessing", summary["by_mode"])

    by_variant = summary.get("by_variant", {})
    has_variant_info = any(name != "none" for name in by_variant)
    if has_variant_info:
        _print_group_table("แยกตาม augmentation variant (เฉพาะชุดข้อมูลสังเคราะห์)", by_variant)

    print(
        "\nหมายเหตุ: whitespace-token error rate ถูกบันทึกไว้ในไฟล์ผลลัพธ์ละเอียด "
        "(--output) เท่านั้น ไม่ใช่ความแม่นยำระดับคำภาษาไทยที่แท้จริง เพราะภาษาไทย"
        "ไม่เว้นวรรคระหว่างคำ ใช้ CER เป็นตัวชี้วัดหลักเสมอโดยเฉพาะกลุ่มภาษาไทย "
        "และห้ามเลือกโหมดที่ 'ชนะ' จาก mean_confidence ของ EasyOCR เพียงอย่างเดียว "
        "ต้องเทียบ CER กับ ground truth เท่านั้น"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if not args.manifest.is_file():
        print(
            f"ไม่พบไฟล์ manifest: {args.manifest}\n\n"
            "ยังไม่มีชุดข้อมูลประเมินผลในเครื่อง กรุณา:\n"
            "  1. อ่านวิธีเตรียมชุดข้อมูลที่ evaluation/README.md\n"
            "  2. สร้างไฟล์ evaluation/manifest.csv ตามรูปแบบใน "
            "evaluation/manifest.example.csv (คอลัมน์: image_path,ground_truth,"
            "language,notes)\n"
            "  3. วางภาพจริงไว้ในตำแหน่งที่ image_path อ้างถึง\n"
            "  4. รันคำสั่งนี้อีกครั้ง: python evaluate_ocr.py --manifest evaluation/manifest.csv\n\n"
            "เครื่องมือนี้จะไม่สร้างผลลัพธ์จำลองขึ้นมาเองเมื่อไม่มีชุดข้อมูลจริง",
            file=sys.stderr,
        )
        return 1

    try:
        rows = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"อ่าน manifest ไม่สำเร็จ: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print(
            f"manifest ที่ {args.manifest} ไม่มีแถวข้อมูลภาพเลย "
            "กรุณาเพิ่มอย่างน้อย 1 แถวที่มี image_path จริง",
            file=sys.stderr,
        )
        return 1

    # ตรวจประเภทชุดข้อมูล (synthetic/real_camera) ก่อนรัน OCR จริงเสมอ (fail
    # fast) เพื่อไม่ให้เสียเวลารัน OCR กับ manifest ที่ปนกันแล้วค่อยพบปัญหาทีหลัง
    try:
        dataset_label = determine_dataset_label(rows)
    except MixedDatasetError as exc:
        print(f"หยุดการประเมิน: {exc}", file=sys.stderr)
        return 1

    print(f"พบภาพในชุดข้อมูล {len(rows)} รายการ (ประเภท: {_DATASET_LABEL_THAI.get(dataset_label, dataset_label)}) "
          f"กำลังประเมินด้วยโหมด: {', '.join(args.modes)}")
    if len(rows) < 20:
        print(
            f"คำแนะนำ: ชุดข้อมูลปัจจุบันมี {len(rows)} ภาพ แนะนำอย่างน้อย 20-30 ภาพ "
            "เพื่อผลที่เป็นตัวแทนมากขึ้น (เครื่องมือนี้ยังทำงานได้กับจำนวนน้อยกว่านั้น)"
        )

    ocr_service = EasyOCRService(gpu=args.gpu)
    records = run_evaluation(rows, args.modes, ocr_service, base_dir=args.manifest.parent)

    summary = summarize(records)
    print_summary(summary, dataset_label)

    if args.output:
        write_records(records, args.output)
        print(f"\nบันทึกผลลัพธ์ละเอียดแล้วที่: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
