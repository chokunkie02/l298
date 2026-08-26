"""ตัวสร้างชุดข้อมูล OCR สังเคราะห์ (synthetic) จากข้อความไทย/อังกฤษที่รู้ ground
truth แน่นอน แล้วจำลองสภาพกล้อง (แสง, มุม, เบลอ, noise, JPEG artifacts ฯลฯ)
เพื่อใช้ประกอบ (ไม่ใช่แทนที่) ชุดข้อมูลภาพถ่ายจริงใน evaluation/

โมดูลนี้เป็นฟังก์ชันบริสุทธิ์ล้วน แยกจาก Flask, ocr_service.py, Serial, และ ESP32
โดยเจตนา ไม่ import อะไรจากที่นั่นเลย เพื่อให้ทดสอบและนำไปใช้ซ้ำได้อิสระจาก
generate_synthetic_ocr.py (CLI)

**ข้อจำกัดสำคัญที่ต้องเข้าใจก่อนใช้งาน**:
  - ภาพสังเคราะห์ไม่ใช่ตัวแทนของภาพถ่ายจริงจากกล้อง/มือถือ ห้ามใช้แทน
    benchmark ภาพจริงใน evaluation/ (ดู evaluation/README.md)
  - ค่า CER จากชุดสังเคราะห์และชุดภาพจริงต้องไม่ถูกนำมารวมเป็นคะแนนเดียวกัน
    ต้องรายงานแยกกันเสมอ (ดู ocr_evaluation.determine_dataset_label)
  - การตรวจสอบว่า font รองรับตัวอักษรที่ต้องการ (font coverage check) เป็นเพียง
    heuristic ที่เทียบ bounding box ของตัวอักษรกับ "ตัวอักษรที่ไม่มีในฟอนต์"
    (.notdef / tofu glyph) ของฟอนต์นั้น ไม่ใช่การอ่าน cmap ของฟอนต์จริงแบบ
    fontTools จึงอาจพลาดกรณีฟอนต์วาด glyph ทดแทนที่มีรูปร่างเหมือนตัวอักษรจริง
    โดยบังเอิญ หรือกรณีฟอนต์ไม่มี .notdef glyph ที่ชัดเจน ผู้ใช้ควรตรวจสอบเอง
    ด้วยสายตาว่าตัวอักษรไทยที่ต้องการ (สระ/วรรณยุกต์) แสดงผลถูกต้องในฟอนต์ที่ใช้
  - ผู้ใช้ต้องตรวจสอบ license ของฟอนต์เองว่าอนุญาตให้ใช้งานลักษณะนี้ได้
    เครื่องมือนี้ไม่ดาวน์โหลดหรือ bundle ฟอนต์ใด ๆ ให้
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from random import Random
from typing import Any, Iterable, Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

GENERATOR_VERSION = "1.0.0"

# ต้องตรงกับคอลัมน์ที่ ocr_evaluation.load_manifest ต้องการเป็นอย่างน้อย
REQUIRED_MANIFEST_COLUMNS = ("image_path", "ground_truth", "language", "notes")

MANIFEST_FIELDNAMES = (
    "image_path",
    "ground_truth",
    "language",
    "notes",
    "sample_id",
    "source_text_id",
    "group_id",
    "split",
    "font",
    "font_size",
    "seed",
    "variant",
    "augmentation_parameters",
    "synthetic",
)

REQUIRED_CORPUS_COLUMNS = ("text_id", "ground_truth", "language", "notes")

FONT_EXTENSIONS = (".ttf", ".otf")

# หมวดหมู่ variant ที่ต้อง generate ให้ครบตามข้อกำหนด เรียงตามลำดับที่จะถูกวนใช้
# เมื่อ variants-per-text >= จำนวนหมวดหมู่นี้ (clean ต้องมาก่อนเสมอ)
VARIANT_CATEGORIES = (
    "clean",
    "dark",
    "bright",
    "low_contrast",
    "rotated",
    "perspective",
    "zoomed_out",
    "blurred",
    "noisy",
    "jpeg_compressed",
    "combined_camera_like",
)


class SyntheticDatasetError(RuntimeError):
    """คลาสฐานของข้อผิดพลาดในโมดูลนี้"""


class CorpusError(SyntheticDatasetError):
    """เกิดขึ้นเมื่อไฟล์ corpus CSV ไม่มีอยู่จริง อ่านไม่ได้ หรือรูปแบบไม่ถูกต้อง"""


class FontDiscoveryError(SyntheticDatasetError):
    """เกิดขึ้นเมื่อไม่พบไฟล์ font (.ttf/.otf) ที่ใช้งานได้ใน font directory ที่ระบุ"""


class RunAlreadyExistsError(SyntheticDatasetError):
    """เกิดขึ้นเมื่อโฟลเดอร์ผลลัพธ์ของ run นี้มีอยู่แล้วและไม่ได้ระบุ force=True

    ป้องกันการเขียนทับผลลัพธ์เดิมโดยไม่ตั้งใจ (ดูข้อกำหนด "ห้ามเขียนทับ run เดิม
    แบบเงียบ ๆ") เครื่องมือนี้จะไม่ลบโฟลเดอร์เดิมโดยอัตโนมัติไม่ว่ากรณีใด
    """


class SplitConfigError(SyntheticDatasetError):
    """เกิดขึ้นเมื่อการตั้งค่า train/val/test split ไม่ถูกต้อง (เช่น สัดส่วนไม่รวมเป็น 1)"""


class LeakageError(SyntheticDatasetError):
    """เกิดขึ้นเมื่อพบว่า group_id เดียวกันถูกแบ่งไปมากกว่าหนึ่ง split (data leakage)"""


# --- การตั้งค่าที่ปรับได้ (ค่าคงที่ default อธิบายไว้ทุกตัวว่าทำไมใช้ช่วงนี้) ------


@dataclass(frozen=True)
class RenderConfig:
    """การตั้งค่าการ render ข้อความเป็นภาพ"""

    font_sizes: tuple[int, ...] = (28, 36, 48)
    fg_color: tuple[int, int, int] = (25, 25, 25)
    paper_color: tuple[int, int, int] = (255, 255, 255)
    margin_px: int = 20
    line_spacing: float = 1.35

    # padding พิเศษด้านบน/ล่าง (คูณกับ font_size) เพื่อกันสระ/วรรณยุกต์ไทยที่อยู่
    # เหนือ/ใต้บรรทัดปกติไม่ให้ถูกตัด (เช่น ไม้โท, สระอี, สระอึ, ตัวเชิงล่างของ ญ/ฐ)
    top_pad_ratio: float = 0.7
    bottom_pad_ratio: float = 0.6

    # เผื่อขอบเพิ่มรอบภาพก่อนทำ geometric transform (หมุน/perspective/เลื่อน)
    # เป็นสัดส่วนของขนาดภาพ base เพื่อไม่ให้ transform ดันข้อความหลุดขอบ
    transform_margin_ratio: float = 0.45

    max_output_dimension: int = 1600
    min_output_dimension: int = 24


@dataclass(frozen=True)
class AugmentConfig:
    """ช่วงค่าพารามิเตอร์ของแต่ละ augmentation แบบสุ่มได้ (ทุกช่วงเลือกให้เห็นผล
    ชัดเจนแต่ยังพอมองออกว่าเป็นข้อความอะไร ไม่ใช่ทำลายภาพจนไม่มีความหมาย)
    """

    brightness_dark_factor: tuple[float, float] = (0.35, 0.6)
    brightness_bright_factor: tuple[float, float] = (1.4, 1.85)
    gamma_dark: tuple[float, float] = (1.25, 1.7)
    gamma_bright: tuple[float, float] = (0.55, 0.8)
    contrast_low_factor: tuple[float, float] = (0.35, 0.65)

    rotation_degrees: tuple[float, float] = (2.0, 8.0)  # ขนาดมุม (ทิศสุ่ม +/-)
    perspective_shift_ratio: tuple[float, float] = (0.03, 0.09)
    zoom_out_scale: tuple[float, float] = (0.35, 0.65)  # ข้อความเหลือกี่เท่าของเดิม
    downscale_factor: tuple[float, float] = (0.35, 0.6)

    gaussian_blur_radius: tuple[float, float] = (0.8, 2.2)
    motion_blur_kernel: tuple[int, int] = (5, 15)  # ต้องเป็นเลขคี่ (ปรับให้คี่อัตโนมัติ)
    motion_blur_angle_degrees: tuple[float, float] = (0.0, 180.0)

    noise_sigma: tuple[float, float] = (6.0, 22.0)
    jpeg_quality: tuple[int, int] = (20, 55)
    paper_tint_shift: tuple[int, int] = (-14, 14)
    safe_shift_ratio: tuple[float, float] = (0.15, 0.45)  # สัดส่วนของ margin ที่เผื่อไว้

    # combined_camera_like: จำนวน op ที่จะสุ่มผสมกัน (ไม่ทำทุก op พร้อมกันเพื่อไม่ให้
    # ภาพเสียหายจนอ่านไม่ได้เลยเสมอไป)
    combined_ops_count: tuple[int, int] = (3, 5)
    # สเกลช่วงค่าพารามิเตอร์ลงเมื่อใช้ใน combined_camera_like (ผสมหลาย op พร้อมกัน
    # จึงใช้ความรุนแรงต่อ op น้อยกว่าตอนใช้ op เดี่ยว ๆ)
    combined_intensity_scale: float = 0.6


DEFAULT_RENDER_CONFIG = RenderConfig()
DEFAULT_AUGMENT_CONFIG = AugmentConfig()

# ตัวอักษรที่ใช้ตรวจว่าฟอนต์ไม่มี glyph จริง (มักถูกวาดเป็น "กล่องทดแทน" หรือ
# glyph ว่างที่เรียกว่า .notdef) เลือก private-use codepoint ที่แทบไม่มีฟอนต์ใด
# assign ความหมายจริงไว้ เพื่อใช้เป็น "ลายนิ้วมือ" ของ .notdef ของฟอนต์นั้น ๆ
_NOTDEF_PROBE_CODEPOINT = "\U0010fffd"


# --- Corpus (ข้อความต้นทางพร้อม ground truth) --------------------------------


@dataclass(frozen=True)
class CorpusRow:
    """หนึ่งแถวของ corpus: ข้อความต้นทางหนึ่งรายการพร้อม ground truth ที่รู้แน่นอน"""

    text_id: str
    ground_truth: str
    language: str
    notes: str

    @property
    def normalized_ground_truth(self) -> str:
        """ground truth หลัง Unicode NFC normalization - ใช้ค่านี้เสมอเมื่อบันทึกลง
        manifest เพื่อให้สอดคล้องกับการ normalize ใน ocr_evaluation.normalize_text
        """
        return unicodedata.normalize("NFC", self.ground_truth)


def load_corpus(corpus_path: Path) -> list[CorpusRow]:
    """อ่านไฟล์ corpus CSV และตรวจรูปแบบคอลัมน์ที่จำเป็น

    แถวที่ text_id ว่างเปล่าจะถูกข้ามไปเงียบ ๆ (ใช้เป็นแถวหมายเหตุได้เหมือน
    ocr_evaluation.load_manifest)
    """
    import csv

    corpus_path = Path(corpus_path)
    if not corpus_path.is_file():
        raise CorpusError(f"ไม่พบไฟล์ corpus: {corpus_path}")

    with open(corpus_path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CorpusError(f"corpus ว่างเปล่าหรืออ่านไม่ได้: {corpus_path}")

        missing = [c for c in REQUIRED_CORPUS_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise CorpusError(
                f"corpus ขาดคอลัมน์ที่จำเป็น: {', '.join(missing)} "
                f"(ต้องมีคอลัมน์: {', '.join(REQUIRED_CORPUS_COLUMNS)})"
            )

        rows: list[CorpusRow] = []
        seen_ids: set[str] = set()
        for raw_row in reader:
            text_id = (raw_row.get("text_id") or "").strip()
            if not text_id:
                continue
            if text_id in seen_ids:
                raise CorpusError(f"text_id ซ้ำกันใน corpus: {text_id!r}")
            seen_ids.add(text_id)
            rows.append(
                CorpusRow(
                    text_id=text_id,
                    ground_truth=raw_row.get("ground_truth") or "",
                    language=(raw_row.get("language") or "").strip(),
                    notes=(raw_row.get("notes") or "").strip(),
                )
            )

    if not rows:
        raise CorpusError(f"corpus ที่ {corpus_path} ไม่มีแถวข้อมูลเลย")

    return rows


# --- Font discovery และการตรวจ coverage แบบ heuristic ------------------------


def discover_fonts(font_dir: Path) -> list[Path]:
    """สแกนหาไฟล์ font (.ttf/.otf เท่านั้น ไม่รองรับ .ttc/.dfont) ใน font_dir

    ไม่ค้นแบบ recursive (เฉพาะไฟล์ตรงใน font_dir) เรียงตามชื่อไฟล์เพื่อให้ผลลัพธ์
    เหมือนเดิมทุกครั้งไม่ว่า filesystem จะคืนลำดับไฟล์แบบใด (จำเป็นต่อการทำซ้ำผล
    ได้แน่นอนเมื่อใช้ seed เดียวกัน)
    """
    font_dir = Path(font_dir)
    if not font_dir.is_dir():
        raise FontDiscoveryError(f"ไม่พบโฟลเดอร์ font: {font_dir}")

    fonts = sorted(
        p for p in font_dir.iterdir() if p.is_file() and p.suffix.lower() in FONT_EXTENSIONS
    )
    if not fonts:
        raise FontDiscoveryError(
            f"ไม่พบไฟล์ font (.ttf หรือ .otf) ใน {font_dir} "
            "กรุณาระบุโฟลเดอร์ที่มีไฟล์ font จริง เครื่องมือนี้จะไม่ดาวน์โหลด "
            "font ให้อัตโนมัติ และไม่ใช้ font ของระบบปฏิบัติการเป็นค่าเริ่มต้น "
            "(ต้องระบุ --font-dir อย่างชัดเจน)"
        )
    return fonts


def _notdef_fingerprint(font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    return font.getbbox(_NOTDEF_PROBE_CODEPOINT)


def find_unsupported_characters(font: ImageFont.FreeTypeFont, text: str) -> list[str]:
    """คืนรายการตัวอักษร (ไม่ซ้ำ) ใน text ที่ดูเหมือนฟอนต์นี้ไม่มี glyph จริงให้

    Heuristic: เทียบ bounding box ของตัวอักษรกับ bounding box ของ .notdef glyph
    (จำลองด้วย private-use codepoint ที่แทบไม่มีฟอนต์ใดมีความหมายจริง) หากตรงกัน
    เป๊ะ ถือว่าตัวอักษรนั้นน่าจะถูกวาดเป็น glyph ทดแทน ไม่ใช่ glyph จริง

    ข้อจำกัด: นี่ไม่ใช่การอ่าน cmap ของฟอนต์ อาจพลาดกรณีฟอนต์บังเอิญวาด glyph
    ทดแทนที่มีขนาดต่างจาก .notdef ปกติ หรือไม่มี .notdef glyph ที่ชัดเจน
    ตัวอักษรที่เป็นช่องว่าง (whitespace) จะไม่ถูกตรวจเพราะไม่มี ink อยู่แล้วโดย
    ธรรมชาติ
    """
    fingerprint = _notdef_fingerprint(font)
    unsupported: list[str] = []
    seen: set[str] = set()
    for ch in text:
        if ch in seen or ch.isspace():
            continue
        seen.add(ch)
        if font.getbbox(ch) == fingerprint:
            unsupported.append(ch)
    return unsupported


# --- การ render ข้อความเป็นภาพ ------------------------------------------------


@dataclass(frozen=True)
class _MeasuredLine:
    text: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def _measure_lines(font: ImageFont.FreeTypeFont, text: str) -> list[_MeasuredLine]:
    lines = text.split("\n") or [""]
    measured = []
    for line in lines:
        # เว้นบรรทัดว่างไว้เป็นบรรทัดสูงเท่าตัวอักษรทั่วไป (ใช้ค่า bbox ของช่องว่าง)
        probe = line if line else " "
        left, top, right, bottom = font.getbbox(probe)
        measured.append(_MeasuredLine(text=line, left=left, top=top, right=right, bottom=bottom))
    return measured


def render_text_image(
    text: str,
    font_path: Path,
    font_size: int,
    *,
    render_config: RenderConfig = DEFAULT_RENDER_CONFIG,
) -> Image.Image:
    """Render ข้อความหนึ่งก้อนเป็นภาพ RGB โดยวัดขนาด ink จริงก่อนกำหนดขนาด canvas
    เพื่อไม่ให้ตัวอักษร (โดยเฉพาะสระ/วรรณยุกต์ไทยที่ยื่นเหนือ/ใต้บรรทัดปกติ) ถูกตัด

    รองรับหลายบรรทัด (คั่นด้วย \\n ใน ground truth) แนวคิดคือเริ่มจากข้อความ
    สั้น ๆ หรือย่อหน้าสั้น ไม่ใช่ layout เอกสารซับซ้อน
    """
    font = ImageFont.truetype(str(font_path), font_size)
    lines = _measure_lines(font, text)

    content_width = max((line.width for line in lines), default=0)
    line_gap = int(round(font_size * (render_config.line_spacing - 1.0)))
    content_height = sum(line.height for line in lines) + line_gap * max(0, len(lines) - 1)

    top_pad = int(round(font_size * render_config.top_pad_ratio))
    bottom_pad = int(round(font_size * render_config.bottom_pad_ratio))
    margin = render_config.margin_px

    canvas_width = max(1, content_width + 2 * margin)
    canvas_height = max(1, content_height + top_pad + bottom_pad + 2 * margin)

    image = Image.new("RGB", (canvas_width, canvas_height), render_config.paper_color)
    draw = ImageDraw.Draw(image)

    y = margin + top_pad
    for line in lines:
        x = margin - line.left
        draw.text((x, y - line.top), line.text, font=font, fill=render_config.fg_color)
        y += line.height + line_gap

    return image


# --- helper สุ่มแบบ deterministic ---------------------------------------------


def sample_rng(seed: int, *parts: Any) -> Random:
    """สร้าง Random ที่ deterministic จาก seed หลักรวมกับ "พิกัด" ของตัวอย่างนั้น ๆ
    (เช่น text_id, variant, ลำดับ) เพื่อให้ seed เดียวกัน + input เดียวกัน
    ให้ผลลัพธ์เหมือนเดิมทุกครั้งไม่ว่าจะ generate ลำดับใดก่อน/หลัง และ seed ต่าง
    กันให้ผลต่างกัน
    """
    key = "|".join([str(seed), *(str(p) for p in parts)])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return Random(int(digest[:16], 16))


def _clip_uint8(array: np.ndarray) -> np.ndarray:
    return np.clip(array, 0, 255).astype(np.uint8)


def _to_array(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("RGB"))


def _to_image(array: np.ndarray) -> Image.Image:
    return Image.fromarray(_clip_uint8(array), mode="RGB")


# --- augmentation primitives ---------------------------------------------
# แต่ละฟังก์ชันรับภาพ RGB (PIL.Image) + rng + ช่วงค่าที่กำหนด คืนภาพใหม่พร้อม
# dict พารามิเตอร์ที่สุ่มได้จริง (บันทึกลง augmentation_parameters เพื่อทำซ้ำ/
# ตรวจสอบย้อนหลังได้)


def op_brightness(image: Image.Image, rng: Random, factor_range: tuple[float, float]) -> tuple[Image.Image, dict]:
    factor = rng.uniform(*factor_range)
    out = ImageEnhance.Brightness(image).enhance(factor)
    return out, {"brightness_factor": round(factor, 3)}


def op_gamma(image: Image.Image, rng: Random, gamma_range: tuple[float, float]) -> tuple[Image.Image, dict]:
    gamma = rng.uniform(*gamma_range)
    lut = ((np.arange(256, dtype=np.float64) / 255.0) ** gamma * 255.0).clip(0, 255).astype(np.uint8)
    array = lut[_to_array(image)]
    return _to_image(array), {"gamma": round(gamma, 3)}


def op_contrast(image: Image.Image, rng: Random, factor_range: tuple[float, float]) -> tuple[Image.Image, dict]:
    factor = rng.uniform(*factor_range)
    out = ImageEnhance.Contrast(image).enhance(factor)
    return out, {"contrast_factor": round(factor, 3)}


def op_grayscale(image: Image.Image, rng: Random) -> tuple[Image.Image, dict]:
    del rng  # ไม่มีพารามิเตอร์สุ่ม แต่รับ rng ไว้ให้ signature สอดคล้องกับ op อื่น
    gray = cv2.cvtColor(_to_array(image), cv2.COLOR_RGB2GRAY)
    rgb = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    return _to_image(rgb), {"grayscale": True}


def op_uneven_lighting(image: Image.Image, rng: Random, strength_range: tuple[float, float] = (0.25, 0.55)) -> tuple[Image.Image, dict]:
    """จำลองแสงไม่สม่ำเสมอ/เงาแบบ gradient โดยคูณ mask ไล่ระดับความสว่างทับภาพ"""
    array = _to_array(image).astype(np.float64)
    h, w = array.shape[:2]
    angle = rng.uniform(0, 2 * math.pi)
    strength = rng.uniform(*strength_range)
    darker_first = rng.random() < 0.5

    yy, xx = np.mgrid[0:h, 0:w]
    direction = math.cos(angle) * xx / max(w, 1) + math.sin(angle) * yy / max(h, 1)
    direction = (direction - direction.min()) / max(direction.max() - direction.min(), 1e-9)
    if not darker_first:
        direction = 1.0 - direction

    multiplier = 1.0 - strength * direction
    array *= multiplier[..., None]
    return _to_image(array), {
        "uneven_lighting_strength": round(strength, 3),
        "uneven_lighting_angle_degrees": round(math.degrees(angle), 1),
    }


def op_paper_tint(image: Image.Image, rng: Random, shift_range: tuple[int, int]) -> tuple[Image.Image, dict]:
    shift = tuple(rng.randint(*shift_range) for _ in range(3))
    array = _to_array(image).astype(np.int16) + np.array(shift, dtype=np.int16)
    return _to_image(array), {"paper_tint_shift_rgb": list(shift)}


def op_gaussian_blur(image: Image.Image, rng: Random, radius_range: tuple[float, float]) -> tuple[Image.Image, dict]:
    radius = rng.uniform(*radius_range)
    out = image.filter(ImageFilter.GaussianBlur(radius=radius))
    return out, {"gaussian_blur_radius": round(radius, 3)}


def op_motion_blur(
    image: Image.Image,
    rng: Random,
    kernel_range: tuple[int, int],
    angle_range: tuple[float, float],
) -> tuple[Image.Image, dict]:
    size = rng.randint(*kernel_range)
    if size % 2 == 0:
        size += 1
    size = max(3, size)
    angle = rng.uniform(*angle_range)

    kernel = np.zeros((size, size), dtype=np.float64)
    kernel[size // 2, :] = 1.0
    center = (size / 2 - 0.5, size / 2 - 0.5)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    kernel = cv2.warpAffine(kernel, rotation_matrix, (size, size))
    kernel_sum = kernel.sum()
    if kernel_sum > 0:
        kernel /= kernel_sum

    array = cv2.filter2D(_to_array(image), -1, kernel)
    return _to_image(array), {"motion_blur_kernel_size": size, "motion_blur_angle_degrees": round(angle, 1)}


def op_gaussian_noise(image: Image.Image, rng: Random, sigma_range: tuple[float, float]) -> tuple[Image.Image, dict]:
    sigma = rng.uniform(*sigma_range)
    array = _to_array(image).astype(np.float64)
    seed_for_numpy = rng.randint(0, 2**31 - 1)
    generator = np.random.default_rng(seed_for_numpy)
    noise = generator.normal(0.0, sigma, size=array.shape)
    return _to_image(array + noise), {"noise_sigma": round(sigma, 3)}


def op_jpeg_artifacts(image: Image.Image, rng: Random, quality_range: tuple[int, int]) -> tuple[Image.Image, dict]:
    """เข้ารหัส/ถอดรหัส JPEG ในหน่วยความจำเพื่อฝัง compression artifact ลงพิกเซล
    (ไฟล์ผลลัพธ์บนดิสก์ยังคงบันทึกตามฟอร์แมตที่ผู้ใช้เลือกใน CLI ตามปกติ)
    """
    quality = rng.randint(*quality_range)
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    out = Image.open(buffer).convert("RGB")
    out.load()
    return out, {"jpeg_quality": quality}


def op_downscale_upscale(image: Image.Image, rng: Random, factor_range: tuple[float, float]) -> tuple[Image.Image, dict]:
    factor = rng.uniform(*factor_range)
    original_size = image.size
    small_size = (max(1, round(original_size[0] * factor)), max(1, round(original_size[1] * factor)))
    down_filter = rng.choice([Image.BILINEAR, Image.NEAREST])
    small = image.resize(small_size, down_filter)
    out = small.resize(original_size, Image.BICUBIC)
    return out, {
        "downscale_factor": round(factor, 3),
        "downscale_filter": "NEAREST" if down_filter == Image.NEAREST else "BILINEAR",
    }


def op_rotate(image: Image.Image, rng: Random, degrees_range: tuple[float, float], paper_color: tuple[int, int, int]) -> tuple[Image.Image, dict]:
    magnitude = rng.uniform(*degrees_range)
    angle = magnitude if rng.random() < 0.5 else -magnitude
    # expand=True รับประกันว่า canvas จะขยายพอรองรับมุมเอียง ไม่ตัดข้อความทิ้ง
    # ไม่ว่า transform_margin ที่เผื่อไว้ล่วงหน้าจะพอหรือไม่ก็ตาม
    out = image.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=paper_color)
    return out, {"rotation_degrees": round(angle, 2)}


def op_perspective(
    image: Image.Image,
    rng: Random,
    shift_ratio_range: tuple[float, float],
    paper_color: tuple[int, int, int],
) -> tuple[Image.Image, dict]:
    array = _to_array(image)
    h, w = array.shape[:2]
    shift_ratio = rng.uniform(*shift_ratio_range)
    max_shift = shift_ratio * min(w, h)

    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    offsets = [(rng.uniform(-max_shift, max_shift), rng.uniform(-max_shift, max_shift)) for _ in range(4)]
    dst = np.float32([[x + dx, y + dy] for (x, y), (dx, dy) in zip(src, offsets)])

    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(
        array,
        matrix,
        (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=paper_color,
    )
    return _to_image(warped), {
        "perspective_shift_ratio": round(shift_ratio, 3),
        "perspective_corner_offsets_px": [[round(dx, 1), round(dy, 1)] for dx, dy in offsets],
    }


def op_zoom_out(
    base_image: Image.Image,
    rng: Random,
    scale_range: tuple[float, float],
    working_size: tuple[int, int],
    paper_color: tuple[int, int, int],
) -> tuple[Image.Image, dict]:
    """ย่อข้อความที่ render ไว้แล้วให้เล็กลง แล้ววางกึ่งกลางบน canvas ขนาด
    working_size (เผื่อขอบไว้แล้วจาก transform_margin) รักษาสัดส่วนเดิมเสมอ
    """
    scale = rng.uniform(*scale_range)
    new_size = (max(1, round(base_image.width * scale)), max(1, round(base_image.height * scale)))
    shrunk = base_image.resize(new_size, Image.LANCZOS)

    canvas = Image.new("RGB", working_size, paper_color)
    paste_x = (working_size[0] - shrunk.width) // 2
    paste_y = (working_size[1] - shrunk.height) // 2
    canvas.paste(shrunk, (paste_x, paste_y))
    return canvas, {"zoom_out_scale": round(scale, 3)}


def op_safe_shift(
    image: Image.Image,
    rng: Random,
    shift_ratio_range: tuple[float, float],
    margin_px: int,
    paper_color: tuple[int, int, int],
) -> tuple[Image.Image, dict]:
    """เลื่อนภาพเล็กน้อยภายในขอบเขต margin ที่เผื่อไว้ (ไม่ดึงข้อความออกนอกกรอบ)"""
    ratio = rng.uniform(*shift_ratio_range)
    max_shift = max(1, int(round(margin_px * ratio)))
    dx = rng.randint(-max_shift, max_shift)
    dy = rng.randint(-max_shift, max_shift)

    canvas = Image.new("RGB", image.size, paper_color)
    canvas.paste(image, (dx, dy))
    return canvas, {"safe_shift_px": [dx, dy]}


# --- การประกอบ variant จาก primitive ops --------------------------------


def _pad_to_working_canvas(image: Image.Image, transform_margin_ratio: float, paper_color: tuple[int, int, int]) -> tuple[Image.Image, int]:
    border_x = max(4, int(round(image.width * transform_margin_ratio)))
    border_y = max(4, int(round(image.height * transform_margin_ratio)))
    border = max(border_x, border_y)
    working_size = (image.width + 2 * border, image.height + 2 * border)
    canvas = Image.new("RGB", working_size, paper_color)
    canvas.paste(image, (border, border))
    return canvas, border


def _clamp_max_dimension(image: Image.Image, max_dimension: int) -> tuple[Image.Image, bool]:
    if max(image.size) <= max_dimension:
        return image, False
    scale = max_dimension / max(image.size)
    new_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(new_size, Image.LANCZOS), True


def apply_variant(
    base_image: Image.Image,
    variant: str,
    rng: Random,
    *,
    render_config: RenderConfig = DEFAULT_RENDER_CONFIG,
    augment_config: AugmentConfig = DEFAULT_AUGMENT_CONFIG,
) -> tuple[Image.Image, dict[str, Any]]:
    """ใช้ augmentation ตามหมวดหมู่ variant กับภาพข้อความ "สะอาด" ที่ render ไว้แล้ว

    คืนภาพผลลัพธ์พร้อม dict พารามิเตอร์ทั้งหมดที่สุ่มได้จริง (เพื่อบันทึกใน
    manifest คอลัมน์ augmentation_parameters) รวมทั้งชื่อ ops ที่ถูกใช้
    """
    if variant not in VARIANT_CATEGORIES:
        raise ValueError(f"ไม่รู้จัก variant: {variant!r} (ต้องเป็นหนึ่งใน {VARIANT_CATEGORIES})")

    paper_color = render_config.paper_color
    params: dict[str, Any] = {"variant": variant}
    ops_applied: list[str] = []

    if variant == "clean":
        image, border = _pad_to_working_canvas(base_image, render_config.transform_margin_ratio, paper_color)
        params["transform_margin_px"] = border

    elif variant == "dark":
        image = base_image
        image, p = op_brightness(image, rng, augment_config.brightness_dark_factor)
        params.update(p)
        ops_applied.append("brightness")
        image, p = op_gamma(image, rng, augment_config.gamma_dark)
        params.update(p)
        ops_applied.append("gamma")
        image, _ = _pad_to_working_canvas(image, render_config.transform_margin_ratio, paper_color)

    elif variant == "bright":
        image = base_image
        image, p = op_brightness(image, rng, augment_config.brightness_bright_factor)
        params.update(p)
        ops_applied.append("brightness")
        image, p = op_gamma(image, rng, augment_config.gamma_bright)
        params.update(p)
        ops_applied.append("gamma")
        image, _ = _pad_to_working_canvas(image, render_config.transform_margin_ratio, paper_color)

    elif variant == "low_contrast":
        image, p = op_contrast(base_image, rng, augment_config.contrast_low_factor)
        params.update(p)
        ops_applied.append("contrast")
        image, _ = _pad_to_working_canvas(image, render_config.transform_margin_ratio, paper_color)

    elif variant == "rotated":
        image, border = _pad_to_working_canvas(base_image, render_config.transform_margin_ratio, paper_color)
        params["transform_margin_px"] = border
        image, p = op_rotate(image, rng, augment_config.rotation_degrees, paper_color)
        params.update(p)
        ops_applied.append("rotate")

    elif variant == "perspective":
        image, border = _pad_to_working_canvas(base_image, render_config.transform_margin_ratio, paper_color)
        params["transform_margin_px"] = border
        image, p = op_perspective(image, rng, augment_config.perspective_shift_ratio, paper_color)
        params.update(p)
        ops_applied.append("perspective")

    elif variant == "zoomed_out":
        working_placeholder, border = _pad_to_working_canvas(base_image, render_config.transform_margin_ratio, paper_color)
        params["transform_margin_px"] = border
        image, p = op_zoom_out(base_image, rng, augment_config.zoom_out_scale, working_placeholder.size, paper_color)
        params.update(p)
        ops_applied.append("zoom_out")

    elif variant == "blurred":
        image, border = _pad_to_working_canvas(base_image, render_config.transform_margin_ratio, paper_color)
        params["transform_margin_px"] = border
        if rng.random() < 0.5:
            image, p = op_gaussian_blur(image, rng, augment_config.gaussian_blur_radius)
            ops_applied.append("gaussian_blur")
        else:
            image, p = op_motion_blur(image, rng, augment_config.motion_blur_kernel, augment_config.motion_blur_angle_degrees)
            ops_applied.append("motion_blur")
        params.update(p)

    elif variant == "noisy":
        image, border = _pad_to_working_canvas(base_image, render_config.transform_margin_ratio, paper_color)
        params["transform_margin_px"] = border
        image, p = op_gaussian_noise(image, rng, augment_config.noise_sigma)
        params.update(p)
        ops_applied.append("gaussian_noise")

    elif variant == "jpeg_compressed":
        image, border = _pad_to_working_canvas(base_image, render_config.transform_margin_ratio, paper_color)
        params["transform_margin_px"] = border
        image, p = op_jpeg_artifacts(image, rng, augment_config.jpeg_quality)
        params.update(p)
        ops_applied.append("jpeg_artifacts")

    elif variant == "combined_camera_like":
        image, border = _pad_to_working_canvas(base_image, render_config.transform_margin_ratio, paper_color)
        params["transform_margin_px"] = border
        image, p = _apply_combined_camera_like(image, rng, augment_config, paper_color)
        params.update(p)
        ops_applied.extend(p.get("ops", []))

    else:  # pragma: no cover - ป้องกันไว้ กันกรณีเพิ่ม variant ใหม่แล้วลืมจัดการ
        raise AssertionError(f"variant {variant!r} ยังไม่มี implementation")

    image, resized = _clamp_max_dimension(image, render_config.max_output_dimension)
    params["final_resize_applied"] = resized
    if "ops" not in params:
        params["ops"] = ops_applied

    _validate_dimensions(image, render_config)
    return image, params


def _scaled_range(range_: tuple[float, float], scale: float) -> tuple[float, float]:
    lo, hi = range_
    mid = (lo + hi) / 2
    return (mid - (mid - lo) * scale, mid + (hi - mid) * scale)


def _apply_combined_camera_like(
    image: Image.Image,
    rng: Random,
    augment_config: AugmentConfig,
    paper_color: tuple[int, int, int],
) -> tuple[Image.Image, dict[str, Any]]:
    """สุ่มผสม op หลายตัวพร้อมกันในระดับความรุนแรง "กลาง ๆ" (ไม่ maximal ทุกตัว)
    เพื่อจำลองภาพถ่ายจากกล้องจริงที่มักมีหลายปัญหาผสมกันเบา ๆ พร้อมกัน
    """
    scale = augment_config.combined_intensity_scale
    pool = [
        "uneven_lighting",
        "paper_tint",
        "brightness",
        "gamma",
        "rotate",
        "perspective",
        "downscale_upscale",
        "blur",
        "noise",
        "jpeg_artifacts",
        "safe_shift",
    ]
    k = min(len(pool), rng.randint(*augment_config.combined_ops_count))
    chosen = set(rng.sample(pool, k))

    params: dict[str, Any] = {"ops": []}

    if "uneven_lighting" in chosen:
        image, p = op_uneven_lighting(image, rng)
        params.update(p)
        params["ops"].append("uneven_lighting")

    if "paper_tint" in chosen:
        image, p = op_paper_tint(image, rng, augment_config.paper_tint_shift)
        params.update(p)
        params["ops"].append("paper_tint")

    if "brightness" in chosen:
        direction_dark = rng.random() < 0.5
        factor_range = augment_config.brightness_dark_factor if direction_dark else augment_config.brightness_bright_factor
        image, p = op_brightness(image, rng, _scaled_range(factor_range, scale))
        params.update(p)
        params["ops"].append("brightness")

    if "gamma" in chosen:
        direction_dark = rng.random() < 0.5
        gamma_range = augment_config.gamma_dark if direction_dark else augment_config.gamma_bright
        image, p = op_gamma(image, rng, _scaled_range(gamma_range, scale))
        params.update(p)
        params["ops"].append("gamma")

    if "rotate" in chosen:
        image, p = op_rotate(image, rng, _scaled_range(augment_config.rotation_degrees, scale), paper_color)
        params.update(p)
        params["ops"].append("rotate")

    if "perspective" in chosen:
        image, p = op_perspective(image, rng, _scaled_range(augment_config.perspective_shift_ratio, scale), paper_color)
        params.update(p)
        params["ops"].append("perspective")

    if "downscale_upscale" in chosen:
        image, p = op_downscale_upscale(image, rng, _scaled_range(augment_config.downscale_factor, scale))
        params.update(p)
        params["ops"].append("downscale_upscale")

    if "blur" in chosen:
        if rng.random() < 0.5:
            image, p = op_gaussian_blur(image, rng, _scaled_range(augment_config.gaussian_blur_radius, scale))
            params["ops"].append("gaussian_blur")
        else:
            image, p = op_motion_blur(image, rng, augment_config.motion_blur_kernel, augment_config.motion_blur_angle_degrees)
            params["ops"].append("motion_blur")
        params.update(p)

    if "noise" in chosen:
        image, p = op_gaussian_noise(image, rng, _scaled_range(augment_config.noise_sigma, scale))
        params.update(p)
        params["ops"].append("noise")

    if "jpeg_artifacts" in chosen:
        lo, hi = augment_config.jpeg_quality
        # jpeg ผสมกับ op อื่น ใช้ quality สูงกว่าช่วงเดี่ยวเล็กน้อย (เสียหายน้อยลง
        # เพราะมี op อื่นเสียหายร่วมด้วยแล้ว)
        boosted = (min(95, int(lo + (hi - lo) * 0.3)), min(95, int(hi + (hi - lo) * 0.3)))
        image, p = op_jpeg_artifacts(image, rng, boosted)
        params.update(p)
        params["ops"].append("jpeg_artifacts")

    if "safe_shift" in chosen:
        # margin_px ที่แท้จริงถูกส่งเข้ามาแล้วผ่าน image.size ครึ่งหนึ่งของ border
        # เดิม ใช้สัดส่วนคงที่จาก config เพื่อไม่ให้เลื่อนจนหลุดขอบ
        margin_estimate = min(image.size) // 4
        image, p = op_safe_shift(image, rng, augment_config.safe_shift_ratio, margin_estimate, paper_color)
        params.update(p)
        params["ops"].append("safe_shift")

    return image, params


def _validate_dimensions(image: Image.Image, render_config: RenderConfig) -> None:
    w, h = image.size
    if w < render_config.min_output_dimension or h < render_config.min_output_dimension:
        raise SyntheticDatasetError(
            f"ภาพผลลัพธ์เล็กเกินไป: {w}x{h} (ขั้นต่ำ {render_config.min_output_dimension}px)"
        )
    if w > render_config.max_output_dimension or h > render_config.max_output_dimension:
        raise SyntheticDatasetError(
            f"ภาพผลลัพธ์ใหญ่เกินไปหลัง clamp: {w}x{h} (สูงสุด {render_config.max_output_dimension}px)"
        )


# --- Sample / manifest ---------------------------------------------------


@dataclass(frozen=True)
class Sample:
    """หนึ่งภาพที่ generate สำเร็จแล้ว พร้อม metadata ครบสำหรับเขียนลง manifest"""

    sample_id: str
    source_text_id: str
    group_id: str
    image_path: str  # สัมพัทธ์กับตำแหน่งไฟล์ manifest
    ground_truth: str  # ผ่าน NFC normalization แล้ว
    language: str
    notes: str
    font: str
    font_size: int
    seed: int
    variant: str
    augmentation_parameters: dict[str, Any]
    split: str = ""
    synthetic: bool = True

    def to_manifest_row(self) -> dict[str, str]:
        return {
            "image_path": self.image_path,
            "ground_truth": self.ground_truth,
            "language": self.language,
            "notes": self.notes,
            "sample_id": self.sample_id,
            "source_text_id": self.source_text_id,
            "group_id": self.group_id,
            "split": self.split,
            "font": self.font,
            "font_size": str(self.font_size),
            "seed": str(self.seed),
            "variant": self.variant,
            "augmentation_parameters": json.dumps(self.augmentation_parameters, ensure_ascii=False, sort_keys=True),
            "synthetic": "true" if self.synthetic else "false",
        }


def write_manifest_csv(samples: Sequence[Sample], path: Path) -> None:
    import csv

    path = Path(path)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDNAMES)
        writer.writeheader()
        for sample in samples:
            writer.writerow(sample.to_manifest_row())


# --- Train/val/test split (แบ่งตาม group_id เท่านั้น กัน leakage) ------------


def parse_split_spec(spec: str) -> dict[str, float]:
    """แปลงสตริงรูปแบบ "train:0.7,val:0.15,test:0.15" เป็น dict ชื่อ->สัดส่วน

    ตรวจว่าสัดส่วนรวมกันได้ประมาณ 1.0 (ยอมคลาดเคลื่อนได้เล็กน้อยจาก floating
    point) มิฉะนั้น raise SplitConfigError ทันทีเพื่อไม่ให้ split ผิดเงียบ ๆ
    """
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        raise SplitConfigError(f"รูปแบบ split ไม่ถูกต้อง (ว่างเปล่า): {spec!r}")

    result: dict[str, float] = {}
    for part in parts:
        if ":" not in part:
            raise SplitConfigError(f"รูปแบบ split ไม่ถูกต้อง (ต้องเป็น name:ratio): {part!r}")
        name, _, ratio_text = part.partition(":")
        name = name.strip()
        if not name:
            raise SplitConfigError(f"ชื่อ split ว่างเปล่าใน: {part!r}")
        try:
            ratio = float(ratio_text)
        except ValueError as exc:
            raise SplitConfigError(f"สัดส่วน split ไม่ใช่ตัวเลข: {part!r}") from exc
        if ratio <= 0:
            raise SplitConfigError(f"สัดส่วน split ต้องมากกว่า 0: {part!r}")
        result[name] = ratio

    total = sum(result.values())
    if not math.isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-3):
        raise SplitConfigError(f"สัดส่วน split รวมกันต้องได้ 1.0 แต่ได้ {total} จาก {spec!r}")

    return result


def _unit_interval(seed: int, group_id: str) -> float:
    digest = hashlib.sha256(f"{seed}|split|{group_id}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16**12)


def assign_splits(group_ids: Iterable[str], proportions: dict[str, float], seed: int) -> dict[str, str]:
    """กำหนด split ให้แต่ละ group_id (ไม่ใช่แต่ละภาพ) แบบ deterministic จาก seed

    group_id เดียวกันได้ split เดียวกันเสมอ (การันตีโดยโครงสร้าง เพราะ hash มา
    จาก group_id ตรง ๆ) seed ต่างกันอาจทำให้การกระจาย split เปลี่ยนไป
    """
    ordered_names = sorted(proportions.keys())
    boundaries = []
    cumulative = 0.0
    for name in ordered_names:
        cumulative += proportions[name]
        boundaries.append((name, cumulative))

    assignment: dict[str, str] = {}
    for group_id in dict.fromkeys(group_ids):  # unique, เก็บลำดับเดิม
        value = _unit_interval(seed, group_id)
        chosen = ordered_names[-1]
        for name, boundary in boundaries:
            if value < boundary:
                chosen = name
                break
        assignment[group_id] = chosen
    return assignment


def validate_no_leakage(samples: Sequence[Sample]) -> None:
    """ตรวจว่าไม่มี group_id ใดถูกกระจายไปมากกว่าหนึ่ง split

    ต้องเรียกหลังกำหนด split เสร็จเสมอ (generate_dataset เรียกให้อัตโนมัติ) ถ้า
    พบ leakage จะ raise LeakageError ทันที ไม่ปล่อยให้ manifest ที่มี leakage
    หลุดออกไปใช้งาน
    """
    group_to_splits: dict[str, set[str]] = {}
    for sample in samples:
        if not sample.split:
            continue
        group_to_splits.setdefault(sample.group_id, set()).add(sample.split)

    leaking = {group: splits for group, splits in group_to_splits.items() if len(splits) > 1}
    if leaking:
        detail = "; ".join(f"{group}: {sorted(splits)}" for group, splits in sorted(leaking.items()))
        raise LeakageError(f"พบ group_id ที่ถูกแบ่งไปมากกว่าหนึ่ง split (data leakage): {detail}")


# --- Orchestration ---------------------------------------------------------


@dataclass
class GenerationResult:
    samples: list[Sample]
    run_metadata: dict[str, Any]
    failures: list[dict[str, str]]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(Path(path).read_bytes())
    return digest.hexdigest()


def prepare_run_directory(output_dir: Path, run_name: str, *, force: bool = False) -> Path:
    """เตรียมโฟลเดอร์ผลลัพธ์ของ run นี้ ปฏิเสธหากมีอยู่แล้วและไม่ได้ระบุ force

    ไม่เคยลบโฟลเดอร์เดิมไม่ว่ากรณีใด (ทั้งตอนปฏิเสธและตอน force) - force เพียง
    อนุญาตให้เขียนทับไฟล์ที่จะสร้างใหม่ทับไฟล์เดิมในโฟลเดอร์เดียวกันเท่านั้น
    """
    run_dir = Path(output_dir) / run_name
    marker_files = [run_dir / "manifest.csv", run_dir / "run_metadata.json"]
    already_has_results = run_dir.is_dir() and any(marker.exists() for marker in marker_files)

    if already_has_results and not force:
        raise RunAlreadyExistsError(
            f"โฟลเดอร์ผลลัพธ์ของ run นี้มีอยู่แล้ว: {run_dir} "
            "กรุณาเปลี่ยน --run-name หรือระบุ --force เพื่อเขียนทับไฟล์ในโฟลเดอร์นี้ "
            "(เครื่องมือนี้จะไม่ลบโฟลเดอร์เดิมโดยอัตโนมัติ)"
        )

    (run_dir / "images").mkdir(parents=True, exist_ok=True)
    return run_dir


def generate_dataset(
    *,
    corpus: Sequence[CorpusRow],
    font_paths: Sequence[Path],
    run_dir: Path,
    variants_per_text: int,
    seed: int,
    render_config: RenderConfig = DEFAULT_RENDER_CONFIG,
    augment_config: AugmentConfig = DEFAULT_AUGMENT_CONFIG,
    image_format: str = "png",
    jpeg_quality: int = 90,
    split_proportions: dict[str, float] | None = None,
) -> GenerationResult:
    """แกนหลักของการ generate: วนทุกแถวใน corpus x variants_per_text แล้ว render +
    augment + บันทึกภาพ คืน Sample ทุกตัวที่สำเร็จ พร้อม metadata การรัน

    ฟังก์ชันนี้ไม่ยุ่งกับ argparse/stdout เลย เพื่อให้ทดสอบเป็นหน่วยได้ตรงไปตรงมา
    (CLI ใน generate_synthetic_ocr.py เป็นเพียง wrapper บาง ๆ รอบฟังก์ชันนี้)
    """
    if variants_per_text < 1:
        raise ValueError("variants_per_text ต้องมากกว่าหรือเท่ากับ 1")
    if not font_paths:
        raise FontDiscoveryError("ไม่มี font ให้ใช้งาน (font_paths ว่างเปล่า)")

    image_format = image_format.lower()
    if image_format not in ("png", "jpg", "jpeg"):
        raise ValueError(f"ไม่รองรับฟอร์แมตภาพ: {image_format!r} (ใช้ png หรือ jpg)")
    file_ext = "jpg" if image_format in ("jpg", "jpeg") else "png"

    images_dir = Path(run_dir) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    samples: list[Sample] = []
    failures: list[dict[str, str]] = []
    fonts_used: set[str] = set()

    for row in corpus:
        group_id = f"grp_{row.text_id}"
        ground_truth = row.normalized_ground_truth
        variant_counts: dict[str, int] = {}

        for i in range(variants_per_text):
            variant = VARIANT_CATEGORIES[i % len(VARIANT_CATEGORIES)]
            rng = sample_rng(seed, row.text_id, variant, i // len(VARIANT_CATEGORIES))

            font_path = rng.choice(list(font_paths))
            font_size = rng.choice(list(render_config.font_sizes))

            variant_counts[variant] = variant_counts.get(variant, 0) + 1
            occurrence = variant_counts[variant]
            sample_id = f"{row.text_id}__{variant}__{occurrence:02d}"

            try:
                font = ImageFont.truetype(str(font_path), font_size)
                unsupported = find_unsupported_characters(font, ground_truth)
                if unsupported:
                    raise SyntheticDatasetError(
                        f"ฟอนต์ {font_path.name} ดูเหมือนไม่มีตัวอักษรต่อไปนี้: "
                        f"{''.join(unsupported)!r}"
                    )

                base_image = render_text_image(ground_truth, font_path, font_size, render_config=render_config)
                image, params = apply_variant(
                    base_image, variant, rng, render_config=render_config, augment_config=augment_config
                )

                image_filename = f"{sample_id}.{file_ext}"
                image_path = images_dir / image_filename
                save_kwargs = {"quality": jpeg_quality} if file_ext == "jpg" else {}
                image.save(image_path, **save_kwargs)

                fonts_used.add(font_path.name)
                samples.append(
                    Sample(
                        sample_id=sample_id,
                        source_text_id=row.text_id,
                        group_id=group_id,
                        image_path=f"images/{image_filename}",
                        ground_truth=ground_truth,
                        language=row.language,
                        notes=row.notes,
                        font=font_path.name,
                        font_size=font_size,
                        seed=seed,
                        variant=variant,
                        augmentation_parameters=params,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - ตั้งใจกันทุก error ต่อ sample ไม่ให้ล้มทั้ง run
                failures.append(
                    {
                        "text_id": row.text_id,
                        "variant": variant,
                        "font": font_path.name if isinstance(font_path, Path) else str(font_path),
                        "reason": str(exc),
                    }
                )

    if split_proportions:
        group_ids = [s.group_id for s in samples]
        assignment = assign_splits(group_ids, split_proportions, seed)
        samples = [
            Sample(**{**asdict(s), "split": assignment.get(s.group_id, "")}) for s in samples
        ]
        validate_no_leakage(samples)

    run_metadata = {
        "generator": "synthetic_dataset",
        "generator_version": GENERATOR_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "variants_per_text": variants_per_text,
        "variant_categories": list(VARIANT_CATEGORIES),
        "fonts_available": sorted(p.name for p in font_paths),
        "fonts_used": sorted(fonts_used),
        "image_format": file_ext,
        "success_count": len(samples),
        "failure_count": len(failures),
        "failures": failures,
        "splits": split_proportions or {},
    }

    return GenerationResult(samples=samples, run_metadata=run_metadata, failures=failures)


def write_run_metadata_json(
    run_metadata: dict[str, Any],
    path: Path,
    *,
    corpus_path: Path,
    render_config: RenderConfig,
    augment_config: AugmentConfig,
) -> None:
    payload = dict(run_metadata)
    payload["corpus_path"] = str(corpus_path)
    payload["corpus_sha256"] = _sha256_file(corpus_path)
    payload["render_config"] = asdict(render_config)
    payload["augment_config"] = asdict(augment_config)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
