"""เครื่องมือวัดความแม่นยำ OCR: การอ่าน manifest, การทำ Unicode normalization,
Character Error Rate (CER) และ whitespace-token error rate, และการสรุปผลลัพธ์
แยกตามภาษาและโหมด preprocessing

โมดูลนี้เป็นฟังก์ชันบริสุทธิ์ (pure functions) ล้วน ไม่ยุ่งกับ Flask, Serial,
หรือ ESP32 เลย เพื่อให้ทดสอบและนำไปใช้ซ้ำได้ง่ายจาก evaluate_ocr.py (CLI)
"""

from __future__ import annotations

import csv
import statistics
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence


REQUIRED_MANIFEST_COLUMNS = ("image_path", "ground_truth", "language", "notes")


class ManifestError(ValueError):
    """เกิดขึ้นเมื่อไฟล์ manifest ไม่มีอยู่จริง อ่านไม่ได้ หรือรูปแบบไม่ถูกต้อง"""


@dataclass(frozen=True)
class ManifestRow:
    """หนึ่งแถวของชุดข้อมูลประเมินผล: ภาพหนึ่งภาพพร้อมข้อความอ้างอิงจริง"""

    image_path: str
    ground_truth: str
    language: str
    notes: str

    def resolve_image_path(self, base_dir: Path) -> Path:
        """แปลง image_path (สัมพัทธ์กับตำแหน่งไฟล์ manifest) เป็น path เต็ม"""
        path = Path(self.image_path)
        return path if path.is_absolute() else base_dir / path


def load_manifest(manifest_path: Path) -> list[ManifestRow]:
    """อ่านไฟล์ manifest CSV และตรวจรูปแบบคอลัมน์ที่จำเป็น

    แถวที่ image_path ว่างเปล่า (เช่นแถวตัวอย่าง/หมายเหตุ) จะถูกข้ามไปเงียบ ๆ
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise ManifestError(f"ไม่พบไฟล์ manifest: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ManifestError(f"manifest ว่างเปล่าหรืออ่านไม่ได้: {manifest_path}")

        missing = [c for c in REQUIRED_MANIFEST_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise ManifestError(
                f"manifest ขาดคอลัมน์ที่จำเป็น: {', '.join(missing)} "
                f"(ต้องมีคอลัมน์: {', '.join(REQUIRED_MANIFEST_COLUMNS)})"
            )

        rows: list[ManifestRow] = []
        for raw_row in reader:
            image_path = (raw_row.get("image_path") or "").strip()
            if not image_path:
                continue
            rows.append(
                ManifestRow(
                    image_path=image_path,
                    ground_truth=raw_row.get("ground_truth") or "",
                    language=(raw_row.get("language") or "").strip(),
                    notes=(raw_row.get("notes") or "").strip(),
                )
            )

    return rows


def normalize_text(text: str | None) -> str:
    """ทำ Unicode NFC normalization ก่อนเปรียบเทียบข้อความเสมอ

    ป้องกันปัญหาตัวอักษรไทยที่ประกอบขึ้นจาก code point หลายตัว (เช่นสระ/วรรณยุกต์
    ที่เขียนได้มากกว่าหนึ่งลำดับ) ถูกนับว่าต่างกันทั้งที่แสดงผลเหมือนกัน
    """
    return unicodedata.normalize("NFC", text or "")


def levenshtein_distance(a: Sequence[Any], b: Sequence[Any]) -> int:
    """ระยะแก้ไข (edit distance) แบบ dynamic programming มาตรฐาน

    ใช้ได้ทั้งกับสตริง (เทียบทีละตัวอักษร) และลิสต์ของโทเคน (เทียบทีละโทเคน)
    เพราะ Python วนซ้ำสตริงและลิสต์ด้วยอินเทอร์เฟซเดียวกัน
    """
    if a == b:
        return 0
    len_a, len_b = len(a), len(b)
    if len_a == 0:
        return len_b
    if len_b == 0:
        return len_a

    previous_row = list(range(len_b + 1))
    for i in range(1, len_a + 1):
        current_row = [i] + [0] * len_b
        char_a = a[i - 1]
        for j in range(1, len_b + 1):
            insertion_cost = current_row[j - 1] + 1
            deletion_cost = previous_row[j] + 1
            substitution_cost = previous_row[j - 1] + (0 if char_a == b[j - 1] else 1)
            current_row[j] = min(insertion_cost, deletion_cost, substitution_cost)
        previous_row = current_row
    return previous_row[-1]


def character_error_rate(prediction: str, ground_truth: str) -> float | None:
    """CER = ระยะแก้ไขระดับตัวอักษร (หลัง NFC) หารด้วยความยาว ground truth

    นี่คือตัวชี้วัดหลักสำหรับภาษาไทย เพราะภาษาไทยไม่เว้นวรรคระหว่างคำ ทำให้การ
    วัดระดับ 'คำ' ด้วยการตัดคำด้วยช่องว่างไม่มีความหมาย

    คืนค่า None เมื่อ ground_truth ว่างเปล่า (คำนวณอัตราความผิดพลาดไม่ได้อย่างมี
    ความหมาย ไม่ควรตีความ None เป็น 0)
    """
    gt = normalize_text(ground_truth)
    if not gt:
        return None
    pred = normalize_text(prediction)
    distance = levenshtein_distance(pred, gt)
    return distance / len(gt)


def whitespace_token_error_rate(prediction: str, ground_truth: str) -> float | None:
    """อัตราความผิดพลาดระดับ 'โทเคนที่คั่นด้วยช่องว่าง' เท่านั้น

    คำเตือนสำคัญ: นี่ไม่ใช่ความแม่นยำระดับคำภาษาไทยที่แท้จริง ภาษาไทยไม่เว้น
    วรรคระหว่างคำ ค่านี้จึงมีความหมายเฉพาะข้อความที่เว้นวรรคจริง เช่นภาษาอังกฤษ
    หรือประโยคไทยที่มีการเว้นวรรคระดับวลี/ประโยคเท่านั้น ห้ามรายงานค่านี้ว่าเป็น
    'word accuracy' ของภาษาไทย ใช้ character_error_rate() เป็นตัวชี้วัดหลักเสมอ

    คืนค่า None เมื่อ ground_truth ไม่มีโทเคนเลย (เช่นว่างเปล่า)
    """
    gt_tokens = normalize_text(ground_truth).split()
    if not gt_tokens:
        return None
    pred_tokens = normalize_text(prediction).split()
    distance = levenshtein_distance(pred_tokens, gt_tokens)
    return distance / len(gt_tokens)


@dataclass
class EvaluationRecord:
    """ผลการรัน OCR หนึ่งภาพ x หนึ่งโหมด preprocessing หนึ่งรายการ"""

    image_path: str
    language: str
    mode: str
    ground_truth: str
    predicted_text: str
    predicted_text_raw: str
    cer: float | None
    token_error_rate: float | None
    exact_match: bool
    mean_confidence: float | None
    processing_seconds: float
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_path": self.image_path,
            "language": self.language,
            "mode": self.mode,
            "ground_truth": self.ground_truth,
            "predicted_text": self.predicted_text,
            "predicted_text_raw": self.predicted_text_raw,
            "cer": self.cer,
            "token_error_rate": self.token_error_rate,
            "exact_match": self.exact_match,
            "mean_confidence": self.mean_confidence,
            "processing_seconds": self.processing_seconds,
            "warnings": list(self.warnings),
            "error": self.error,
        }


def _mean_or_none(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def _median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _summarize_group(records: list[EvaluationRecord]) -> dict[str, Any]:
    failures = [r for r in records if r.error is not None]
    successes = [r for r in records if r.error is None]
    cer_values = [r.cer for r in successes if r.cer is not None]
    token_error_values = [r.token_error_rate for r in successes if r.token_error_rate is not None]
    latencies = [r.processing_seconds for r in successes]
    exact_matches = [r for r in successes if r.exact_match]

    return {
        "sample_count": len(records),
        "success_count": len(successes),
        "failure_count": len(failures),
        "mean_cer": _mean_or_none(cer_values),
        "median_cer": _median_or_none(cer_values),
        "mean_token_error_rate": _mean_or_none(token_error_values),
        "exact_match_rate": (len(exact_matches) / len(successes)) if successes else None,
        "mean_processing_seconds": _mean_or_none(latencies),
    }


def summarize(records: Iterable[EvaluationRecord]) -> dict[str, Any]:
    """สรุปผลรวม: ภาพรวม, แยกตามภาษา, และแยกตามโหมด preprocessing

    CER คือตัวชี้วัดหลักที่ควรดูก่อนเสมอ โดยเฉพาะกลุ่มภาษาไทย
    ความแม่นยำต้องเทียบกับ ground truth เท่านั้น - ไม่ใช้ mean_confidence ของ
    EasyOCR เป็นตัวตัดสินว่าโหมดใด 'ชนะ'
    """
    records = list(records)

    by_language: dict[str, list[EvaluationRecord]] = {}
    by_mode: dict[str, list[EvaluationRecord]] = {}
    for record in records:
        by_language.setdefault(record.language or "unknown", []).append(record)
        by_mode.setdefault(record.mode, []).append(record)

    return {
        "overall": _summarize_group(records),
        "by_language": {lang: _summarize_group(rows) for lang, rows in sorted(by_language.items())},
        "by_mode": {mode: _summarize_group(rows) for mode, rows in sorted(by_mode.items())},
    }


EVALUATION_RECORD_FIELDNAMES = (
    "image_path",
    "language",
    "mode",
    "ground_truth",
    "predicted_text",
    "predicted_text_raw",
    "cer",
    "token_error_rate",
    "exact_match",
    "mean_confidence",
    "processing_seconds",
    "warnings",
    "error",
)


def write_records_csv(records: Iterable[EvaluationRecord], path: Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVALUATION_RECORD_FIELDNAMES)
        writer.writeheader()
        for record in records:
            row = record.to_dict()
            row["warnings"] = ";".join(row["warnings"])
            writer.writerow(row)


def write_records_json(records: Iterable[EvaluationRecord], path: Path) -> None:
    import json

    with open(path, "w", encoding="utf-8") as handle:
        json.dump([record.to_dict() for record in records], handle, ensure_ascii=False, indent=2)


def write_records(records: Iterable[EvaluationRecord], path: Path) -> None:
    """เลือกรูปแบบไฟล์ผลลัพธ์จากนามสกุลไฟล์ (.csv หรือ .json)"""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        write_records_csv(records, path)
    elif suffix == ".json":
        write_records_json(records, path)
    else:
        raise ValueError(f"ไม่รองรับนามสกุลไฟล์ผลลัพธ์: {suffix} (ใช้ .csv หรือ .json เท่านั้น)")
