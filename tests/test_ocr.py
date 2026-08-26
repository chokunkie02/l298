import base64
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import app as app_module
from image_preprocessing import ImageDecodeError, ImageTooLargeError
from ocr_service import (
    EasyOCRService,
    OCRInitializationError,
    OCRProcessingError,
)


VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class FakeReader:
    def __init__(self, results=None, error=None):
        self.results = results or []
        self.error = error
        self.calls = []

    def readtext(self, image_bytes, **kwargs):
        self.calls.append((image_bytes, kwargs))
        if self.error:
            raise self.error
        return self.results


class ArrayLikeBoundingBox:
    def tolist(self):
        return [[1.5, 2.5], [10.0, 2.5], [10.0, 12.0], [1.5, 12.0]]


class EasyOCRServiceTests(unittest.TestCase):
    def make_service(self, results):
        reader = FakeReader(results=results)
        factory = Mock(return_value=reader)
        return EasyOCRService(reader_factory=factory), reader, factory

    def test_successful_thai_ocr_result(self):
        service, reader, _factory = self.make_service([
            ([[0, 0], [20, 0], [20, 10], [0, 10]], "สวัสดี", 0.93),
        ])

        result = service.recognize(VALID_PNG)

        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "สวัสดี")
        self.assertEqual(result["languages"], ["th", "en"])
        self.assertFalse(result["low_confidence"])
        self.assertEqual(reader.calls[0][1], {"detail": 1, "paragraph": False})

    def test_successful_english_ocr_result(self):
        service, _reader, _factory = self.make_service([
            ([[0, 0], [20, 0], [20, 10], [0, 10]], "Hello world", 0.88),
        ])

        result = service.recognize(VALID_PNG)

        self.assertEqual(result["text"], "Hello world")
        self.assertAlmostEqual(result["mean_confidence"], 0.88)

    def test_mixed_thai_english_preserves_detected_order(self):
        service, _reader, _factory = self.make_service([
            ([[0, 0], [10, 0], [10, 10], [0, 10]], "ภาษาไทย", 0.90),
            ([[12, 0], [22, 0], [22, 10], [12, 10]], "English", 0.74),
            ([[24, 0], [34, 0], [34, 10], [24, 10]], "ข้อความ", 0.82),
        ])

        result = service.recognize(VALID_PNG)

        self.assertEqual(result["text"], "ภาษาไทย English ข้อความ")
        self.assertEqual(
            [segment["text"] for segment in result["segments"]],
            ["ภาษาไทย", "English", "ข้อความ"],
        )
        self.assertAlmostEqual(result["mean_confidence"], (0.90 + 0.74 + 0.82) / 3)
        self.assertIn("ค่าเฉลี่ยเลขคณิต", result["mean_confidence_note"])
        self.assertIn("ไม่ใช่ค่ารับประกัน", result["mean_confidence_note"])

    def test_confidence_and_bounding_box_serialization_keeps_low_score(self):
        service, _reader, _factory = self.make_service([
            (ArrayLikeBoundingBox(), "ไม่ชัด", 0.20),
            (None, "unclear", 0.40),
        ])

        result = service.recognize(VALID_PNG)

        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0]["confidence"], 0.20)
        self.assertEqual(
            result["segments"][0]["bounding_box"],
            [[1.5, 2.5], [10.0, 2.5], [10.0, 12.0], [1.5, 12.0]],
        )
        self.assertIsNone(result["segments"][1]["bounding_box"])
        self.assertAlmostEqual(result["mean_confidence"], 0.30)
        self.assertTrue(result["low_confidence"])

    def test_no_text_detected_is_successful_empty_result(self):
        service, _reader, _factory = self.make_service([])

        result = service.recognize(VALID_PNG)

        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["segments"], [])
        self.assertIsNone(result["mean_confidence"])
        self.assertFalse(result["low_confidence"])
        self.assertEqual(
            result["message"],
            "ไม่พบข้อความในภาพ กรุณาถ่ายหรือเลือกภาพใหม่",
        )

    def test_initialization_failure_is_wrapped(self):
        factory = Mock(side_effect=RuntimeError("download failed"))
        service = EasyOCRService(reader_factory=factory)

        with self.assertRaises(OCRInitializationError):
            service.recognize(VALID_PNG)
        with self.assertRaises(OCRInitializationError):
            service.recognize(VALID_PNG)

        factory.assert_called_once_with(("th", "en"), gpu=False)

    def test_inference_failure_is_wrapped(self):
        reader = FakeReader(error=RuntimeError("internal inference details"))
        service = EasyOCRService(reader_factory=Mock(return_value=reader))

        with self.assertRaises(OCRProcessingError) as error_context:
            service.recognize(VALID_PNG)

        self.assertNotIn("internal inference details", str(error_context.exception))

    def test_reader_initialization_occurs_only_once_across_threads(self):
        reader = FakeReader(results=[])
        factory_call_count = 0
        factory_count_lock = threading.Lock()

        def factory(_languages, gpu=False):
            nonlocal factory_call_count
            with factory_count_lock:
                factory_call_count += 1
            self.assertFalse(gpu)
            return reader

        service = EasyOCRService(reader_factory=factory)
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(service.recognize, [VALID_PNG] * 6))

        self.assertEqual(factory_call_count, 1)
        self.assertTrue(all(result["ok"] for result in results))


class OCRApiTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.original_ocr_service = app_module.ocr_service

    def tearDown(self):
        app_module.ocr_service = self.original_ocr_service

    def post_image(self, image_bytes=VALID_PNG, content_type="image/png"):
        return self.client.post(
            "/api/ocr",
            data={"image": (BytesIO(image_bytes), "sample.png", content_type)},
            content_type="multipart/form-data",
        )

    def test_invalid_image_upload(self):
        mocked_service = Mock()
        app_module.ocr_service = mocked_service

        response = self.post_image(b"not an image")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["ok"])
        self.assertEqual(response.get_json()["error"]["code"], "invalid_image")
        mocked_service.recognize.assert_not_called()

    def test_initialization_failure_returns_structured_error(self):
        mocked_service = Mock()
        mocked_service.recognize.side_effect = OCRInitializationError("เริ่ม OCR ไม่สำเร็จ")
        app_module.ocr_service = mocked_service

        response = self.post_image()

        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "ocr_initialization_failed")
        self.assertNotIn("Traceback", response.get_data(as_text=True))

    def test_inference_failure_returns_structured_error(self):
        mocked_service = Mock()
        mocked_service.recognize.side_effect = OCRProcessingError("ประมวลผลไม่สำเร็จ")
        app_module.ocr_service = mocked_service

        response = self.post_image()

        payload = response.get_json()
        self.assertEqual(response.status_code, 500)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "ocr_processing_failed")
        self.assertNotIn("Traceback", response.get_data(as_text=True))

    def test_no_text_api_result_remains_successful(self):
        reader = FakeReader(results=[])
        app_module.ocr_service = EasyOCRService(
            reader_factory=Mock(return_value=reader)
        )

        response = self.post_image()

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["text"], "")
        self.assertEqual(
            payload["message"],
            "ไม่พบข้อความในภาพ กรุณาถ่ายหรือเลือกภาพใหม่",
        )

    def test_frontend_uses_real_ocr_api_and_accessible_empty_message(self):
        script = (Path(app_module.BASE_DIR) / "static" / "script.js").read_text(
            encoding="utf-8"
        )
        template = (
            Path(app_module.BASE_DIR) / "templates" / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn("fetch('/api/ocr'", script)
        self.assertIn("new FormData()", script)
        self.assertIn("ไม่พบข้อความในภาพ กรุณาถ่ายหรือเลือกภาพใหม่", script)
        self.assertIn("ocrStatus", script)
        self.assertNotIn("OCR_PLACEHOLDER_TEXT", script)
        self.assertNotIn("<textarea", template.lower())

    def test_ocr_request_and_local_confirmation_do_not_call_esp32(self):
        mocked_service = Mock()
        mocked_service.recognize.return_value = {
            "ok": True,
            "text": "สวัสดี Hello",
            "segments": [],
            "mean_confidence": 0.9,
            "mean_confidence_note": "ค่าเฉลี่ยเลขคณิต ไม่ใช่ค่ารับประกัน",
            "low_confidence": False,
            "low_confidence_threshold": 0.6,
            "languages": ["th", "en"],
            "message": "อ่านข้อความจากภาพสำเร็จ",
        }
        app_module.ocr_service = mocked_service

        with patch.object(app_module, "init_serial") as init_serial:
            response = self.post_image()

        self.assertEqual(response.status_code, 200)
        init_serial.assert_not_called()

        script = (Path(app_module.BASE_DIR) / "static" / "script.js").read_text(
            encoding="utf-8"
        )
        confirmation_block = script.split("function confirmOcrResult()", 1)[1].split(
            "function chooseAnotherImage()", 1
        )[0]
        self.assertNotIn("fetch(", confirmation_block)
        self.assertNotIn("sendPatternToESP32", confirmation_block)

    def test_api_response_includes_structured_image_quality_and_preprocessing(self):
        reader = FakeReader(results=[
            ([[0, 0], [20, 0], [20, 10], [0, 10]], "สวัสดี", 0.93),
        ])
        app_module.ocr_service = EasyOCRService(reader_factory=Mock(return_value=reader))

        response = self.post_image()
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("image_quality", payload)
        self.assertIn("preprocessing", payload)

        image_quality = payload["image_quality"]
        self.assertEqual(
            set(image_quality.keys()),
            {"width", "height", "mean_brightness", "contrast", "blur_score", "warnings"},
        )
        self.assertIsInstance(image_quality["warnings"], list)

        preprocessing = payload["preprocessing"]
        self.assertEqual(set(preprocessing.keys()), {"mode", "upscaled"})
        self.assertEqual(preprocessing["mode"], "resize")

    def test_quality_warnings_do_not_block_ocr_success(self):
        # ภาพทดสอบ VALID_PNG เป็นภาพ 1x1 พิกเซลสีเข้ม ซึ่งหลัง preprocessing
        # ควรถูกตีคำเตือนเรื่องความมืด/contrast/ความเบลอ แต่ต้องไม่ทำให้ OCR ล้มเหลว
        reader = FakeReader(results=[
            ([[0, 0], [20, 0], [20, 10], [0, 10]], "ข้อความทดสอบ", 0.85),
        ])
        app_module.ocr_service = EasyOCRService(reader_factory=Mock(return_value=reader))

        response = self.post_image()
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["text"], "ข้อความทดสอบ")
        self.assertGreater(len(payload["image_quality"]["warnings"]), 0)

    def test_decompression_bomb_returns_structured_413_error(self):
        with patch.object(app_module, "preprocess_image", side_effect=ImageTooLargeError("ภาพใหญ่เกินไป")):
            response = self.post_image()

        payload = response.get_json()
        self.assertEqual(response.status_code, 413)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "image_too_large")

    def test_undecodable_image_after_validation_returns_structured_400_error(self):
        with patch.object(app_module, "preprocess_image", side_effect=ImageDecodeError("decode ไม่ได้")):
            response = self.post_image()

        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_image")

    def test_preprocessing_failure_does_not_reach_ocr_service_or_serial(self):
        mocked_service = Mock()
        app_module.ocr_service = mocked_service

        with patch.object(app_module, "preprocess_image", side_effect=ImageTooLargeError("x")):
            with patch.object(app_module, "init_serial") as init_serial:
                self.post_image()

        mocked_service.recognize.assert_not_called()
        init_serial.assert_not_called()


if __name__ == "__main__":
    unittest.main()
