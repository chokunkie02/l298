"""ทดสอบโมดูล image_preprocessing.py: decode, EXIF, resize, CLAHE, threshold,
และ heuristic วัดคุณภาพภาพ ทั้งหมดใช้ภาพเล็กที่สร้างในหน่วยความจำ ไม่ต้องใช้
โมเดล OCR จริง
"""

import io
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import image_preprocessing as ip


def _png_bytes(image: Image.Image, **save_kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", **save_kwargs)
    return buffer.getvalue()


def _jpeg_bytes_with_exif(image: Image.Image, orientation: int) -> bytes:
    exif = Image.Exif()
    exif[274] = orientation  # 274 = Orientation tag
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


class PixelCountGuardTests(unittest.TestCase):
    """ฟังก์ชันบริสุทธิ์ ทดสอบได้เร็วโดยไม่ต้องสร้างภาพขนาดใหญ่จริง"""

    def test_accepts_reasonable_dimensions(self):
        ip._check_pixel_count(1920, 1080)  # ไม่ควร raise

    def test_rejects_decompression_bomb_sized_dimensions(self):
        with self.assertRaises(ip.ImageTooLargeError):
            ip._check_pixel_count(20000, 20000)

    def test_rejects_non_positive_dimensions(self):
        with self.assertRaises(ip.ImageDecodeError):
            ip._check_pixel_count(0, 100)

    def test_custom_limit_is_respected(self):
        with self.assertRaises(ip.ImageTooLargeError):
            ip._check_pixel_count(100, 100, max_pixels=5000)


class DecodeAndOrientationTests(unittest.TestCase):
    def test_decodes_valid_png(self):
        image = Image.new("RGB", (10, 6), color=(120, 130, 140))
        decoded = ip.decode_image_with_orientation(_png_bytes(image))
        self.assertEqual(decoded.size, (10, 6))
        self.assertEqual(decoded.mode, "RGB")

    def test_invalid_bytes_raise_decode_error(self):
        with self.assertRaises(ip.ImageDecodeError):
            ip.decode_image_with_orientation(b"not an image")

    def test_decompression_bomb_sized_header_is_rejected(self):
        # จำลอง PNG ที่ประกาศขนาดใหญ่เกินจริงผ่าน mock ของ Image.open เพื่อไม่ต้อง
        # จัดสรรหน่วยความจำสำหรับภาพจริง
        from unittest.mock import patch

        class _FakeImage:
            size = (30000, 30000)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(ip.Image, "open", return_value=_FakeImage()):
            with self.assertRaises(ip.ImageTooLargeError):
                ip.decode_image_with_orientation(b"fake-header-bytes")

    def test_exif_orientation_90_degrees_swaps_dimensions(self):
        # ภาพต้นฉบับ 4x2 พร้อม orientation=6 (ต้องหมุน 90 องศาตามเข็มเพื่อแสดงถูก)
        # หลังแก้ orientation ขนาดต้องกลายเป็น 2x4
        image = Image.new("RGB", (4, 2), color=(0, 0, 0))
        image.putpixel((0, 0), (255, 0, 0))

        decoded = ip.decode_image_with_orientation(_jpeg_bytes_with_exif(image, orientation=6))
        self.assertEqual(decoded.size, (2, 4))

    def test_no_exif_orientation_tag_leaves_dimensions_unchanged(self):
        image = Image.new("RGB", (5, 3), color=(10, 20, 30))
        decoded = ip.decode_image_with_orientation(_png_bytes(image))
        self.assertEqual(decoded.size, (5, 3))


class ResizeSafeTests(unittest.TestCase):
    def test_small_image_is_upscaled_preserving_aspect_ratio(self):
        image = Image.new("RGB", (100, 50))
        resized, upscaled = ip.resize_safe(
            image, min_dimension=800, max_dimension=4000, max_upscale_factor=3.0
        )
        self.assertTrue(upscaled)
        self.assertEqual(resized.size, (300, 150))  # capped at 3x, ratio 2:1 preserved

    def test_large_image_is_downscaled_and_not_marked_upscaled(self):
        image = Image.new("RGB", (600, 300))
        resized, upscaled = ip.resize_safe(
            image, min_dimension=20, max_dimension=200, max_upscale_factor=3.0
        )
        self.assertFalse(upscaled)
        self.assertEqual(max(resized.size), 200)
        self.assertAlmostEqual(resized.size[0] / resized.size[1], 600 / 300)

    def test_image_already_within_bounds_is_unchanged(self):
        image = Image.new("RGB", (100, 100))
        resized, upscaled = ip.resize_safe(
            image, min_dimension=50, max_dimension=200, max_upscale_factor=3.0
        )
        self.assertFalse(upscaled)
        self.assertEqual(resized.size, (100, 100))

    def test_upscale_is_capped_by_max_upscale_factor(self):
        image = Image.new("RGB", (10, 10))
        resized, upscaled = ip.resize_safe(
            image, min_dimension=1000, max_dimension=4000, max_upscale_factor=2.0
        )
        self.assertTrue(upscaled)
        self.assertEqual(resized.size, (20, 20))  # capped at 2x, not 100x

    def test_upscale_then_max_dimension_cap_still_preserves_aspect_ratio(self):
        image = Image.new("RGB", (10, 5))
        resized, upscaled = ip.resize_safe(
            image, min_dimension=1000, max_dimension=40, max_upscale_factor=100.0
        )
        self.assertEqual(max(resized.size), 40)
        self.assertAlmostEqual(resized.size[0] / resized.size[1], 10 / 5)


class PreprocessModeTests(unittest.TestCase):
    def _sample_png(self, size=(40, 30)):
        image = Image.new("RGB", size, color=(180, 180, 180))
        return _png_bytes(image)

    def test_mode_none_only_decodes_without_resize(self):
        array, info = ip.preprocess_image(self._sample_png((40, 30)), mode="none")
        self.assertEqual(info.mode, "none")
        self.assertFalse(info.upscaled)
        self.assertEqual(array.shape[:2], (30, 40))
        self.assertEqual(array.ndim, 3)  # ยังเป็นภาพสี RGB

    def test_mode_resize_applies_safe_resize(self):
        # ภาพ 10x10 เล็กกว่า MIN_DIMENSION_PX มาก แต่ถูกจำกัดไม่ให้ขยายเกิน
        # MAX_UPSCALE_FACTOR (ค่าเริ่มต้น 3 เท่า) จึงได้ 30x30 ไม่ใช่ 800x800
        array, info = ip.preprocess_image(self._sample_png((10, 10)), mode="resize")
        self.assertEqual(info.mode, "resize")
        self.assertTrue(info.upscaled)
        expected_side = round(10 * ip.MAX_UPSCALE_FACTOR)
        self.assertEqual(array.shape[:2], (expected_side, expected_side))

    def test_mode_grayscale_clahe_produces_single_channel_output(self):
        array, info = ip.preprocess_image(self._sample_png((10, 10)), mode="grayscale_clahe")
        self.assertEqual(info.mode, "grayscale_clahe")
        self.assertEqual(array.ndim, 2)
        self.assertEqual(array.dtype, np.uint8)

    def test_mode_adaptive_threshold_produces_binary_output(self):
        # ใช้ภาพที่มีลวดลาย (ไม่ใช่สีพื้นเดียว) เพื่อให้ adaptive threshold มีความหมาย
        image = Image.new("RGB", (20, 20), color=(0, 0, 0))
        for x in range(0, 20, 2):
            for y in range(20):
                image.putpixel((x, y), (255, 255, 255))
        array, info = ip.preprocess_image(_png_bytes(image), mode="adaptive_threshold")
        self.assertEqual(info.mode, "adaptive_threshold")
        self.assertEqual(array.ndim, 2)
        unique_values = set(np.unique(array).tolist())
        self.assertTrue(unique_values.issubset({0, 255}))

    def test_unknown_mode_raises_value_error(self):
        with self.assertRaises(ValueError):
            ip.preprocess_image(self._sample_png(), mode="does_not_exist")

    def test_adaptive_threshold_rejects_even_block_size(self):
        image = Image.new("RGB", (10, 10))
        with self.assertRaises(ValueError):
            ip.apply_adaptive_threshold(image, block_size=10, c=5)

    def test_default_production_mode_is_resize(self):
        self.assertEqual(ip.DEFAULT_PREPROCESSING_MODE, "resize")


class QualityDiagnosticsTests(unittest.TestCase):
    def test_dark_image_triggers_dark_warning(self):
        array = np.full((100, 100, 3), 10, dtype=np.uint8)
        quality = ip.compute_quality_diagnostics(array)
        self.assertIn("dark", quality.warnings)
        self.assertNotIn("bright", quality.warnings)

    def test_bright_image_triggers_bright_warning(self):
        array = np.full((100, 100, 3), 250, dtype=np.uint8)
        quality = ip.compute_quality_diagnostics(array)
        self.assertIn("bright", quality.warnings)
        self.assertNotIn("dark", quality.warnings)

    def test_flat_image_triggers_low_contrast_and_blurry_warnings(self):
        array = np.full((100, 100, 3), 128, dtype=np.uint8)
        quality = ip.compute_quality_diagnostics(array)
        self.assertIn("low_contrast", quality.warnings)
        self.assertIn("blurry", quality.warnings)

    def test_high_contrast_sharp_pattern_has_no_contrast_or_blur_warning(self):
        array = np.zeros((100, 100, 3), dtype=np.uint8)
        array[:, ::2] = 255  # ลายทางสลับขาวดำทุกคอลัมน์ = คมชัดและ contrast สูง
        quality = ip.compute_quality_diagnostics(array)
        self.assertNotIn("low_contrast", quality.warnings)
        self.assertNotIn("blurry", quality.warnings)

    def test_diagnostics_report_dimensions(self):
        array = np.full((50, 80, 3), 128, dtype=np.uint8)
        quality = ip.compute_quality_diagnostics(array)
        self.assertEqual(quality.width, 80)
        self.assertEqual(quality.height, 50)

    def test_diagnostics_accept_grayscale_arrays_directly(self):
        array = np.full((50, 50), 128, dtype=np.uint8)
        quality = ip.compute_quality_diagnostics(array)
        self.assertEqual(quality.width, 50)
        self.assertEqual(quality.height, 50)

    def test_custom_thresholds_are_respected(self):
        array = np.full((100, 100, 3), 90, dtype=np.uint8)
        default_quality = ip.compute_quality_diagnostics(array)
        self.assertNotIn("dark", default_quality.warnings)

        strict_quality = ip.compute_quality_diagnostics(array, dark_threshold=95.0)
        self.assertIn("dark", strict_quality.warnings)

    def test_to_dict_serializes_cleanly(self):
        array = np.full((10, 10, 3), 128, dtype=np.uint8)
        quality = ip.compute_quality_diagnostics(array)
        payload = quality.to_dict()
        self.assertEqual(set(payload.keys()), {"width", "height", "mean_brightness", "contrast", "blur_score", "warnings"})
        self.assertIsInstance(payload["warnings"], list)


class PreprocessingResultSerializationTests(unittest.TestCase):
    def test_to_dict_matches_documented_shape(self):
        result = ip.PreprocessingResult(
            mode="resize", upscaled=True, original_size=(10, 10), processed_size=(300, 300)
        )
        self.assertEqual(result.to_dict(), {"mode": "resize", "upscaled": True})


class NoSerialCouplingTests(unittest.TestCase):
    """image_preprocessing.py ต้องไม่ยุ่งเกี่ยวกับ Serial/ESP32 เลย"""

    def test_module_source_has_no_serial_or_send_references(self):
        source = Path(ip.__file__).read_text(encoding="utf-8")
        self.assertNotIn("serial", source.lower())
        self.assertNotIn("/send", source)
        self.assertNotIn("ser_conn", source)


if __name__ == "__main__":
    unittest.main()
