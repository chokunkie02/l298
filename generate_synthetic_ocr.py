#!/usr/bin/env python3
"""CLI สำหรับสร้างชุดข้อมูล OCR สังเคราะห์ (synthetic) จาก corpus ข้อความไทย/
อังกฤษที่รู้ ground truth แน่นอน พร้อมจำลองสภาพกล้อง (แสง มุม เบลอ noise ฯลฯ)
ผ่าน synthetic_dataset.py แล้วสร้าง manifest ที่ evaluate_ocr.py ใช้ได้ทันที

**ชุดข้อมูลนี้ไม่ใช่ตัวแทนของภาพถ่ายจริง** ใช้เพื่อทดสอบ pipeline preprocessing/
evaluation และหาข้อบกพร่องเชิงระบบเท่านั้น ต้องมีชุดภาพถ่ายจริงแยกต่างหาก (ดู
evaluation/README.md) ก่อนตัดสินใจใด ๆ เกี่ยวกับ production เสมอ

ตัวอย่างการใช้งาน:
    python generate_synthetic_ocr.py \\
        --corpus evaluation/synthetic/corpus.example.csv \\
        --font-dir /path/to/approved-fonts \\
        --output evaluation/generated \\
        --run-name baseline-seed-42 \\
        --variants-per-text 5 \\
        --seed 42

สคริปต์นี้ไม่ยุ่งเกี่ยวกับ Flask, Serial, หรือ ESP32 เลย
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from synthetic_dataset import (
    VARIANT_CATEGORIES,
    AugmentConfig,
    CorpusError,
    FontDiscoveryError,
    LeakageError,
    RenderConfig,
    RunAlreadyExistsError,
    SplitConfigError,
    discover_fonts,
    generate_dataset,
    load_corpus,
    parse_split_spec,
    prepare_run_directory,
    write_manifest_csv,
    write_run_metadata_json,
)


def _parse_color(value: str) -> tuple[int, int, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"สีต้องอยู่ในรูปแบบ R,G,B เช่น 255,255,255 (ได้รับ: {value!r})")
    try:
        r, g, b = (int(p.strip()) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"สีต้องเป็นตัวเลขจำนวนเต็ม 0-255: {value!r}") from exc
    if not all(0 <= c <= 255 for c in (r, g, b)):
        raise argparse.ArgumentTypeError(f"ค่าสีแต่ละช่องต้องอยู่ระหว่าง 0-255: {value!r}")
    return (r, g, b)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True, help="ไฟล์ corpus CSV (คอลัมน์: text_id,ground_truth,language,notes)")
    parser.add_argument("--font-dir", type=Path, required=True, help="โฟลเดอร์ที่มีไฟล์ font .ttf/.otf ของคุณเอง (ไม่ดาวน์โหลดให้อัตโนมัติ)")
    parser.add_argument("--output", type=Path, required=True, help="โฟลเดอร์ผลลัพธ์หลัก (จะสร้างโฟลเดอร์ย่อยตาม --run-name ข้างใน)")
    parser.add_argument("--run-name", type=str, default=None, help="ชื่อ run (ค่าเริ่มต้น: synthetic-seed-<seed>)")
    parser.add_argument("--variants-per-text", type=int, default=len(VARIANT_CATEGORIES), help=f"จำนวนภาพที่ generate ต่อข้อความหนึ่งรายการ (ค่าเริ่มต้น {len(VARIANT_CATEGORIES)} = ครบทุกหมวดหมู่ variant คนละ 1 ภาพ)")
    parser.add_argument("--seed", type=int, required=True, help="random seed หลัก (จำเป็น เพื่อบังคับให้ผู้ใช้ระบุอย่างชัดเจนสำหรับการทำซ้ำผลได้)")
    parser.add_argument("--font-sizes", type=int, nargs="+", default=None, help=f"ขนาดตัวอักษรที่จะสุ่มใช้ (ค่าเริ่มต้น {list(RenderConfig().font_sizes)})")
    parser.add_argument("--image-format", choices=["png", "jpg"], default="png", help="ฟอร์แมตไฟล์ภาพที่บันทึกลงดิสก์ (ค่าเริ่มต้น png)")
    parser.add_argument("--jpeg-quality", type=int, default=90, help="คุณภาพ JPEG เมื่อ --image-format=jpg (ไม่เกี่ยวกับ variant jpeg_compressed ซึ่งจำลอง artifact ที่ระดับพิกเซลแยกต่างหาก)")
    parser.add_argument("--fg-color", type=_parse_color, default=None, help="สีตัวอักษร R,G,B (ค่าเริ่มต้น 25,25,25)")
    parser.add_argument("--paper-color", type=_parse_color, default=None, help="สีพื้นหลัง/กระดาษ R,G,B (ค่าเริ่มต้น 255,255,255)")
    parser.add_argument("--margin-px", type=int, default=None, help="ขอบรอบข้อความเป็นพิกเซล (ค่าเริ่มต้น 20)")
    parser.add_argument("--line-spacing", type=float, default=None, help="ตัวคูณระยะห่างบรรทัด (ค่าเริ่มต้น 1.35)")
    parser.add_argument("--splits", type=str, default=None, help='ตั้งค่า train/val/test เช่น "train:0.7,val:0.15,test:0.15" (ไม่ระบุ = ไม่แบ่ง split)')
    parser.add_argument("--force", action="store_true", help="อนุญาตให้เขียนทับไฟล์ในโฟลเดอร์ run เดิม (จะไม่ลบโฟลเดอร์เดิมไม่ว่ากรณีใด)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    run_name = args.run_name or f"synthetic-seed-{args.seed}"

    try:
        corpus = load_corpus(args.corpus)
    except CorpusError as exc:
        print(f"อ่าน corpus ไม่สำเร็จ: {exc}", file=sys.stderr)
        return 1

    try:
        font_paths = discover_fonts(args.font_dir)
    except FontDiscoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    render_kwargs = {}
    if args.font_sizes:
        render_kwargs["font_sizes"] = tuple(args.font_sizes)
    if args.fg_color:
        render_kwargs["fg_color"] = args.fg_color
    if args.paper_color:
        render_kwargs["paper_color"] = args.paper_color
    if args.margin_px is not None:
        render_kwargs["margin_px"] = args.margin_px
    if args.line_spacing is not None:
        render_kwargs["line_spacing"] = args.line_spacing
    render_config = RenderConfig(**render_kwargs) if render_kwargs else RenderConfig()
    augment_config = AugmentConfig()

    split_proportions = None
    if args.splits:
        try:
            split_proportions = parse_split_spec(args.splits)
        except SplitConfigError as exc:
            print(f"ตั้งค่า --splits ไม่ถูกต้อง: {exc}", file=sys.stderr)
            return 1

    try:
        run_dir = prepare_run_directory(args.output, run_name, force=args.force)
    except RunAlreadyExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"กำลัง generate ชุดข้อมูลสังเคราะห์: {len(corpus)} ข้อความ x {args.variants_per_text} variants "
          f"= สูงสุด {len(corpus) * args.variants_per_text} ภาพ (seed={args.seed})")
    print(f"font ที่พบ ({len(font_paths)}): {', '.join(p.name for p in font_paths)}")

    try:
        result = generate_dataset(
            corpus=corpus,
            font_paths=font_paths,
            run_dir=run_dir,
            variants_per_text=args.variants_per_text,
            seed=args.seed,
            render_config=render_config,
            augment_config=augment_config,
            image_format=args.image_format,
            jpeg_quality=args.jpeg_quality,
            split_proportions=split_proportions,
        )
    except LeakageError as exc:
        print(f"ตรวจพบ data leakage ระหว่าง split: {exc}", file=sys.stderr)
        return 1

    write_manifest_csv(result.samples, run_dir / "manifest.csv")
    write_run_metadata_json(
        result.run_metadata,
        run_dir / "run_metadata.json",
        corpus_path=args.corpus,
        render_config=render_config,
        augment_config=augment_config,
    )

    print(f"\nสำเร็จ: {result.run_metadata['success_count']} ภาพ  ล้มเหลว: {result.run_metadata['failure_count']} ภาพ")
    if result.failures:
        print("ตัวอย่างความล้มเหลว (ดูรายการเต็มใน run_metadata.json):")
        for failure in result.failures[:5]:
            print(f"  - {failure['text_id']} / {failure['variant']} ({failure['font']}): {failure['reason']}")

    print(f"\nบันทึกไว้ที่: {run_dir}")
    print(f"  manifest:     {run_dir / 'manifest.csv'}")
    print(f"  run metadata: {run_dir / 'run_metadata.json'}")
    print(f"\nขั้นตอนถัดไป - รันประเมินผลด้วยตัวประเมิน OCR เดิม (ผลลัพธ์จะถูกระบุว่าเป็น synthetic โดยอัตโนมัติ):")
    print(f"  python evaluate_ocr.py --manifest {run_dir / 'manifest.csv'} --output evaluation/results/{run_name}.csv")
    print("\nคำเตือน: ผลลัพธ์จากชุดข้อมูลสังเคราะห์นี้ต้องไม่ถูกใช้แทนชุดภาพถ่ายจริง "
          "และต้องไม่นำ CER ของชุดสังเคราะห์ไปรวมกับ CER ของชุดภาพจริงเป็นคะแนนเดียว")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
