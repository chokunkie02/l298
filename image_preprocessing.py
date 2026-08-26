"""โมดูลเตรียมภาพก่อนส่งเข้า OCR แยกออกจาก Flask route และ EasyOCRService โดยเจตนา
เพื่อให้ทดสอบแต่ละขั้นตอนได้อิสระ และเปรียบเทียบผลระหว่างโหมดต่าง ๆ ได้ก่อนเปลี่ยน
พฤติกรรม production จริง

ลำดับการประมวลผลที่แน่นอน (deterministic) สำหรับแต่ละโหมด มีดังนี้:

  1. none
     - decode ภาพเท่านั้น
     - แก้ EXIF orientation
     - ไม่ทำอะไรเพิ่มเติม คงลักษณะเดิมของภาพไว้

  2. resize
     - แก้ EXIF orientation
     - ขยายภาพที่เล็กเกินไปโดยรักษาสัดส่วนภาพ (safe upscale)
     - จำกัดขนาดสูงสุดเพื่อไม่ให้ใช้หน่วยความจำเกินควร (safe downscale)

  3. grayscale_clahe
     - แก้ EXIF orientation
     - resize อย่างปลอดภัยเหมือนโหมด resize
     - แปลงเป็น grayscale
     - ใช้ CLAHE (Contrast Limited Adaptive Histogram Equalization) ด้วยพารามิเตอร์
       ที่กำหนดไว้เป็นค่าคงที่และปรับได้

  4. adaptive_threshold
     - แก้ EXIF orientation
     - resize อย่างปลอดภัยเหมือนโหมด resize
     - แปลงเป็น grayscale
     - ใช้ adaptive thresholding ด้วยพารามิเตอร์ที่กำหนดไว้เป็นค่าคงที่และปรับได้

ค่าเริ่มต้นของ production (DEFAULT_PREPROCESSING_MODE) คือ "resize" เท่านั้น -
แก้ EXIF orientation และ resize อย่างปลอดภัย ไม่ใช้ CLAHE หรือ thresholding เป็น
ค่าเริ่มต้น จนกว่าจะมีข้อมูลประเมินผลจริง (ดู evaluate_ocr.py) ยืนยันว่าช่วยเพิ่ม
ความแม่นยำ
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


# --- ค่าคงที่ที่ควบคุมพฤติกรรมการ decode และ resize -------------------------

# ป้องกัน decompression bomb: ปฏิเสธภาพที่มีจำนวนพิกเซล (กว้าง x สูง) เกินค่านี้
# ก่อนที่จะ decode พิกเซลจริง (ตรวจจาก header เท่านั้น) ค่า 40 ล้านพิกเซลครอบคลุม
# กล้องโทรศัพท์ทั่วไป (ส่วนใหญ่ไม่เกิน 48MP) แต่กันภาพที่จงใจสร้างให้ header เล็ก
# แต่ขยายเป็นภาพมหึมาเมื่อ decode
MAX_INPUT_PIXELS = 40_000_000

# ขนาดด้านยาวสูงสุดหลัง resize (พิกเซล) เพื่อจำกัดเวลาและหน่วยความจำของ OCR
MAX_DIMENSION_PX = 4000

# ขนาดด้านสั้นเป้าหมายขั้นต่ำ (พิกเซล) สำหรับภาพที่เล็กเกินไป - EasyOCR มักอ่านได้
# แม่นยำขึ้นเมื่อด้านสั้นไม่เล็กกว่านี้มากนัก
MIN_DIMENSION_PX = 800

# จำกัดอัตราขยายสูงสุดไม่ให้เกินกี่เท่า เพื่อไม่ขยาย noise/ความเบลอของภาพเล็กมาก
# จนเกินจริง
MAX_UPSCALE_FACTOR = 3.0

# --- ค่าคงที่ของ CLAHE -------------------------------------------------------

CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID_SIZE = (8, 8)

# --- ค่าคงที่ของ adaptive threshold ------------------------------------------

# ต้องเป็นเลขคี่ตามข้อกำหนดของ cv2.adaptiveThreshold
ADAPTIVE_THRESH_BLOCK_SIZE = 35
ADAPTIVE_THRESH_C = 15

# --- ค่าคงที่ของ heuristic วัดคุณภาพภาพ ---------------------------------------
# ทั้งหมดนี้เป็นค่า heuristic ปรับได้ ไม่ใช่เกณฑ์ตัดสินความแม่นยำ OCR ที่แน่นอน

DARK_MEAN_BRIGHTNESS_THRESHOLD = 70.0
BRIGHT_MEAN_BRIGHTNESS_THRESHOLD = 200.0
LOW_CONTRAST_STD_THRESHOLD = 30.0
BLUR_LAPLACIAN_VARIANCE_THRESHOLD = 100.0

PREPROCESSING_MODES = ("none", "resize", "grayscale_clahe", "adaptive_threshold")
DEFAULT_PREPROCESSING_MODE = "resize"


class ImageDecodeError(RuntimeError):
    """เกิดขึ้นเมื่อไม่สามารถ decode ไฟล์ภาพได้ หรือขนาดภาพไม่ถูกต้อง"""


class ImageTooLargeError(RuntimeError):
    """เกิดขึ้นเมื่อภาพมีจำนวนพิกเซลเกินขีดจำกัด (สงสัยว่าเป็น decompression bomb)"""


@dataclass(frozen=True)
class PreprocessingResult:
    """สรุปว่าโหมดใดถูกใช้และมีการขยายภาพ (upscale) หรือไม่"""

    mode: str
    upscaled: bool
    original_size: tuple[int, int]
    processed_size: tuple[int, int]

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "upscaled": self.upscaled}


@dataclass(frozen=True)
class ImageQuality:
    """ผลการวัดคุณภาพภาพแบบ heuristic - ไม่ใช่การรับประกันผล OCR"""

    width: int
    height: int
    mean_brightness: float
    contrast: float
    blur_score: float
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "mean_brightness": round(self.mean_brightness, 2),
            "contrast": round(self.contrast, 2),
            "blur_score": round(self.blur_score, 2),
            "warnings": list(self.warnings),
        }


def _check_pixel_count(width: int, height: int, max_pixels: int = MAX_INPUT_PIXELS) -> None:
    """ตรวจจำนวนพิกเซลจาก header ก่อน decode จริง เพื่อกัน decompression bomb

    แยกเป็นฟังก์ชันบริสุทธิ์ (pure function) ต่างหากเพื่อให้ทดสอบได้เร็วโดยไม่ต้อง
    สร้างภาพจริงขนาดใหญ่
    """
    if width <= 0 or height <= 0:
        raise ImageDecodeError(f"ขนาดภาพไม่ถูกต้อง: {width}x{height}")
    if width * height > max_pixels:
        raise ImageTooLargeError(
            f"ภาพมีขนาด {width}x{height} พิกเซล ({width * height:,} พิกเซล) "
            f"เกินขีดจำกัด {max_pixels:,} พิกเซล กรุณาใช้ภาพที่มีขนาดเล็กลง"
        )


def decode_image_with_orientation(image_bytes: bytes) -> Image.Image:
    """Decode ภาพอย่างปลอดภัยแล้วแก้ EXIF orientation

    ลำดับการทำงาน: เปิดไฟล์ (ยังไม่ decode พิกเซล) -> ตรวจจำนวนพิกเซลจาก header ->
    แก้ EXIF orientation (ทำให้ decode พิกเซลจริง) -> แปลงเป็นโหมดสี RGB
    """
    try:
        image = Image.open(BytesIO(image_bytes))
        width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageDecodeError(f"ไม่สามารถอ่านไฟล์นี้เป็นภาพได้: {exc}") from None

    _check_pixel_count(width, height)

    try:
        oriented = ImageOps.exif_transpose(image)
        if oriented is None:
            oriented = image
        return oriented.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageDecodeError(f"ไม่สามารถ decode พิกเซลของภาพนี้ได้: {exc}") from None


def resize_safe(
    image: Image.Image,
    *,
    min_dimension: int = MIN_DIMENSION_PX,
    max_dimension: int = MAX_DIMENSION_PX,
    max_upscale_factor: float = MAX_UPSCALE_FACTOR,
) -> tuple[Image.Image, bool]:
    """ปรับขนาดภาพอย่างปลอดภัยโดยรักษาสัดส่วนเสมอ (uniform scale ทั้งสองด้าน)

    - ถ้าด้านสั้นเล็กกว่า min_dimension: ขยายให้ด้านสั้น >= min_dimension แต่ไม่เกิน
      max_upscale_factor เท่าของขนาดเดิม
    - ถ้าด้านยาวหลังขยาย (หรือของเดิม) เกิน max_dimension: ย่อกลับให้ด้านยาว ==
      max_dimension
    - คืนค่า (ภาพที่ปรับขนาดแล้ว, upscaled) โดย upscaled = True เมื่อ scale
      สุดท้ายมากกว่า 1.0 เท่านั้น (ไม่นับกรณีที่ถูกย่อกลับจนเท่าเดิมหรือเล็กลง)
    """
    width, height = image.size
    shorter_side = min(width, height)
    longer_side = max(width, height)

    scale = 1.0
    if shorter_side < min_dimension:
        scale = min(min_dimension / shorter_side, max_upscale_factor)

    projected_longer = longer_side * scale
    if projected_longer > max_dimension:
        scale *= max_dimension / projected_longer

    if scale == 1.0:
        return image.copy(), False

    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    resample = Image.LANCZOS
    resized = image.resize(new_size, resample)
    return resized, scale > 1.0


def apply_grayscale_clahe(
    image: Image.Image,
    *,
    clip_limit: float = CLAHE_CLIP_LIMIT,
    tile_grid_size: tuple[int, int] = CLAHE_TILE_GRID_SIZE,
) -> Image.Image:
    """แปลงเป็น grayscale แล้วปรับ contrast ด้วย CLAHE"""
    gray = np.array(image.convert("L"))
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
    enhanced = clahe.apply(gray)
    return Image.fromarray(enhanced)


def apply_adaptive_threshold(
    image: Image.Image,
    *,
    block_size: int = ADAPTIVE_THRESH_BLOCK_SIZE,
    c: int = ADAPTIVE_THRESH_C,
) -> Image.Image:
    """แปลงเป็น grayscale แล้วทำ adaptive thresholding (ขาว-ดำ)"""
    if block_size % 2 == 0 or block_size < 3:
        raise ValueError("block_size ต้องเป็นเลขคี่และมีค่าอย่างน้อย 3")

    gray = np.array(image.convert("L"))
    thresholded = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        block_size,
        c,
    )
    return Image.fromarray(thresholded)


def preprocess_image(
    image_bytes: bytes, mode: str = DEFAULT_PREPROCESSING_MODE
) -> tuple[np.ndarray, PreprocessingResult]:
    """จุดรวมของ pipeline เตรียมภาพ ดูลำดับขั้นตอนที่แน่นอนใน docstring ของโมดูล

    คืนค่าเป็น numpy array (RGB สำหรับโหมด none/resize, grayscale/binary
    สำหรับโหมด grayscale_clahe/adaptive_threshold) พร้อมข้อมูลสรุปว่าใช้โหมดใด
    """
    if mode not in PREPROCESSING_MODES:
        raise ValueError(
            f"ไม่รู้จักโหมด preprocessing: {mode!r} (ต้องเป็นหนึ่งใน {PREPROCESSING_MODES})"
        )

    image = decode_image_with_orientation(image_bytes)
    original_size = image.size

    if mode == "none":
        processed = image
        upscaled = False
    else:
        processed, upscaled = resize_safe(image)
        if mode == "grayscale_clahe":
            processed = apply_grayscale_clahe(processed)
        elif mode == "adaptive_threshold":
            processed = apply_adaptive_threshold(processed)

    array = np.array(processed)
    info = PreprocessingResult(
        mode=mode,
        upscaled=upscaled,
        original_size=original_size,
        processed_size=processed.size,
    )
    return array, info


def compute_quality_diagnostics(
    image_array: np.ndarray,
    *,
    dark_threshold: float = DARK_MEAN_BRIGHTNESS_THRESHOLD,
    bright_threshold: float = BRIGHT_MEAN_BRIGHTNESS_THRESHOLD,
    low_contrast_threshold: float = LOW_CONTRAST_STD_THRESHOLD,
    blur_threshold: float = BLUR_LAPLACIAN_VARIANCE_THRESHOLD,
) -> ImageQuality:
    """คำนวณ heuristic วัดคุณภาพภาพก่อนส่งเข้า OCR

    - mean_brightness / contrast: ค่าเฉลี่ยและส่วนเบี่ยงเบนมาตรฐานของพิกเซล
      grayscale (0-255)
    - blur_score: ความแปรปรวน (variance) ของ Laplacian ซึ่งเป็นวิธี heuristic
      ที่นิยมใช้ประมาณความเบลอ (ค่ายิ่งต่ำยิ่งน่าสงสัยว่าเบลอ) แต่ขึ้นกับเนื้อหา
      ของภาพด้วย ไม่ใช่ค่าตัดสินที่แน่นอน

    คำเตือนทั้งหมดเป็นเพียงสัญญาณเตือน ไม่ใช่การตัดสินที่แน่ชัด และจะไม่ปิดกั้น
    การทำ OCR ต่อ
    """
    if image_array.ndim == 3:
        gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
    else:
        gray = image_array

    height, width = gray.shape[:2]
    gray_float = gray.astype(np.float64)
    mean_brightness = float(gray_float.mean())
    contrast = float(gray_float.std())
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    warnings: list[str] = []
    if mean_brightness < dark_threshold:
        warnings.append("dark")
    if mean_brightness > bright_threshold:
        warnings.append("bright")
    if contrast < low_contrast_threshold:
        warnings.append("low_contrast")
    if blur_score < blur_threshold:
        warnings.append("blurry")

    return ImageQuality(
        width=width,
        height=height,
        mean_brightness=mean_brightness,
        contrast=contrast,
        blur_score=blur_score,
        warnings=tuple(warnings),
    )
