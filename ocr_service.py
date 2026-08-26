"""บริการ EasyOCR สำหรับอ่านข้อความไทยและอังกฤษจากข้อมูลภาพในหน่วยความจำ"""

from __future__ import annotations

import math
import threading
from typing import Any, Callable, Sequence


OCR_LANGUAGES = ("th", "en")
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.60


class OCRInitializationError(RuntimeError):
    """เกิดขึ้นเมื่อไม่สามารถสร้างหรือดาวน์โหลดโมเดลของ EasyOCR ได้"""


class OCRProcessingError(RuntimeError):
    """เกิดขึ้นเมื่อ EasyOCR ไม่สามารถประมวลผลภาพได้"""


class EasyOCRService:
    """ห่อ EasyOCR Reader แบบ lazy และใช้ Reader เดียวร่วมกันทุกคำขอ"""

    def __init__(
        self,
        reader_factory: Callable[..., Any] | None = None,
        languages: Sequence[str] = OCR_LANGUAGES,
        gpu: bool = False,
        low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    ) -> None:
        self.languages = tuple(languages)
        self.gpu = gpu
        self.low_confidence_threshold = low_confidence_threshold
        self._reader_factory = reader_factory or self._create_default_reader
        self._reader = None
        self._initialization_error: OCRInitializationError | None = None
        self._initialization_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @staticmethod
    def _create_default_reader(languages: Sequence[str], gpu: bool) -> Any:
        # Import แบบ lazy เพื่อไม่โหลดไลบรารีหรือโมเดลระหว่าง import โมดูลนี้
        import easyocr

        return easyocr.Reader(list(languages), gpu=gpu)

    def _get_reader(self) -> Any:
        if self._reader is not None:
            return self._reader
        if self._initialization_error is not None:
            raise self._initialization_error

        with self._initialization_lock:
            if self._reader is not None:
                return self._reader
            if self._initialization_error is not None:
                raise self._initialization_error

            try:
                self._reader = self._reader_factory(self.languages, gpu=self.gpu)
            except Exception:
                self._initialization_error = OCRInitializationError(
                    "ไม่สามารถเริ่มต้น EasyOCR หรือดาวน์โหลดโมเดลได้ "
                    "กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต พื้นที่จัดเก็บ และเริ่มแอปใหม่"
                )
                raise self._initialization_error from None

        return self._reader

    def recognize(self, image_bytes: bytes) -> dict[str, Any]:
        """อ่านข้อความจากภาพและคืนข้อมูลที่พร้อมแปลงเป็น JSON"""
        reader = self._get_reader()

        try:
            # Reader เดียวถูกใช้ร่วมกัน จึงล็อกช่วง inference เพื่อหลีกเลี่ยง state ชนกัน
            with self._inference_lock:
                raw_results = reader.readtext(image_bytes, detail=1, paragraph=False)
        except Exception:
            raise OCRProcessingError(
                "EasyOCR ไม่สามารถประมวลผลภาพนี้ได้ กรุณาลองถ่ายหรือเลือกภาพใหม่"
            ) from None

        try:
            segments = [self._serialize_segment(item) for item in raw_results]
        except OCRProcessingError:
            raise
        except Exception:
            raise OCRProcessingError(
                "EasyOCR ส่งผลลัพธ์ในรูปแบบที่ระบบไม่รองรับ"
            ) from None
        text = " ".join(segment["text"] for segment in segments if segment["text"])
        confidences = [segment["confidence"] for segment in segments]
        mean_confidence = (
            sum(confidences) / len(confidences) if confidences else None
        )
        low_confidence = (
            mean_confidence is not None
            and mean_confidence < self.low_confidence_threshold
        )

        message = (
            "อ่านข้อความจากภาพสำเร็จ"
            if text
            else "ไม่พบข้อความในภาพ กรุณาถ่ายหรือเลือกภาพใหม่"
        )

        return {
            "ok": True,
            "text": text,
            "segments": segments,
            "mean_confidence": mean_confidence,
            "mean_confidence_note": (
                "mean_confidence คือค่าเฉลี่ยเลขคณิตของ confidence ทุก segment "
                "ไม่ใช่ค่ารับประกันความแม่นยำของ OCR"
            ),
            "low_confidence": low_confidence,
            "low_confidence_threshold": self.low_confidence_threshold,
            "languages": list(self.languages),
            "message": message,
        }

    @classmethod
    def _serialize_segment(cls, item: Any) -> dict[str, Any]:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            raise OCRProcessingError(
                "EasyOCR ส่งผลลัพธ์ในรูปแบบที่ระบบไม่รองรับ"
            )

        bounding_box, text, raw_confidence = item[:3]
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError, OverflowError):
            raise OCRProcessingError(
                "EasyOCR ส่งค่า confidence ในรูปแบบที่ระบบไม่รองรับ"
            ) from None

        if not math.isfinite(confidence):
            raise OCRProcessingError(
                "EasyOCR ส่งค่า confidence ที่ไม่สามารถแปลงเป็น JSON ได้"
            )

        return {
            "text": str(text).strip(),
            "confidence": confidence,
            "bounding_box": cls._to_json_value(bounding_box),
        }

    @classmethod
    def _to_json_value(cls, value: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, (list, tuple)):
            return [cls._to_json_value(item) for item in value]
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise OCRProcessingError(
                    "EasyOCR ส่ง bounding box ที่ไม่สามารถแปลงเป็น JSON ได้"
                )
            return value
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError):
            raise OCRProcessingError(
                "EasyOCR ส่ง bounding box ในรูปแบบที่ระบบไม่รองรับ"
            ) from None
        if not math.isfinite(numeric_value):
            raise OCRProcessingError(
                "EasyOCR ส่ง bounding box ที่ไม่สามารถแปลงเป็น JSON ได้"
            )
        return numeric_value
