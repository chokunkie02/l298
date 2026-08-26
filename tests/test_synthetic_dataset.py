"""ทดสอบ synthetic_dataset.py (Step 3.5): render ข้อความ, augmentation แบบ
deterministic, manifest/metadata, การแบ่ง split แบบกัน leakage, และการป้องกัน
เขียนทับ run เดิม ทั้งหมดใช้ font ขนาดเล็กในหน่วยความจำ/ไฟล์ชั่วคราว ไม่มีการ
ดาวน์โหลด font, OCR model, หรือ dataset ใด ๆ ระหว่างรันเทสต์

**เกี่ยวกับ font ที่ใช้ในเทสต์**: เทสต์ส่วนใหญ่ใช้ font ที่ extract มาจาก font
เริ่มต้นที่ฝังอยู่ใน Pillow เอง (Aileron, รองรับเฉพาะ Latin) เขียนลงไฟล์ชั่วคราว
เพื่อทดสอบกลไกทั่วไป (การ render, augmentation, manifest, ฯลฯ) โดยไม่ต้องพึ่ง
font ภายนอกหรือของระบบปฏิบัติการเลย เทสต์ที่ต้อง**ตรวจสอบการแสดงผลสระ/วรรณยุกต์
ไทยจริง**จะมองหา font ไทยที่มีอยู่แล้วในเครื่อง (จากรายชื่อตำแหน่งทั่วไปข้าม
แพลตฟอร์ม) และ**ข้าม (skip) อย่างชัดเจน** หากไม่พบ แทนที่จะ fail หรือดาวน์โหลด
font มาเอง - นี่เป็นพฤติกรรมของ "เทสต์" เท่านั้น ไม่ใช่ default path ของตัว
generator เอง (generator เองไม่มี hardcoded font path ใด ๆ ต้องรับ --font-dir
จากผู้ใช้เสมอ)
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from random import Random

import numpy as np
from PIL import Image, ImageFont

import synthetic_dataset as sd

# ตำแหน่ง font ไทยที่พบได้ทั่วไปข้ามแพลตฟอร์ม ใช้เพื่อ "ค้นหา" font ที่มีอยู่แล้ว
# ในเครื่องสำหรับเทสต์เท่านั้น (ไม่ดาวน์โหลด ไม่ hardcode ไว้ใน production code)
_CANDIDATE_THAI_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Ayuthaya.ttf",
    "/System/Library/Fonts/Supplemental/Krungthep.ttf",
    "/System/Library/Fonts/Supplemental/Silom.ttf",
    "/usr/share/fonts/truetype/tlwg/Garuda.ttf",
    "/usr/share/fonts/truetype/thai-tlwg/Garuda.ttf",
    "/usr/share/fonts/truetype/tlwg/Norasi.ttf",
    "C:\\Windows\\Fonts\\leelawui.ttf",
    "C:\\Windows\\Fonts\\leelawad.ttf",
]


def _find_local_thai_font() -> Path | None:
    for candidate in _CANDIDATE_THAI_FONT_PATHS:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


_LOCAL_THAI_FONT = _find_local_thai_font()

skip_without_thai_font = unittest.skipUnless(
    _LOCAL_THAI_FONT is not None,
    "ไม่พบ font ไทยในตำแหน่งทั่วไปของเครื่องนี้ - ข้ามเทสต์ที่ต้องใช้ glyph ไทยจริง "
    "(เทสต์นี้ค้นหา font ที่มีอยู่แล้วเท่านั้น ไม่ดาวน์โหลด)",
)


def _write_latin_test_font(directory: Path, filename: str = "test_latin.ttf") -> Path:
    """เขียน font Latin-only ที่ฝังอยู่ใน Pillow เองลงไฟล์ชั่วคราว เพื่อใช้ทดสอบ
    กลไกทั่วไปโดยไม่พึ่ง font ภายนอกหรือของระบบปฏิบัติการเลย
    """
    font_obj = ImageFont.load_default(size=20)
    font_bytes = font_obj.font_bytes
    path = directory / filename
    path.write_bytes(font_bytes)
    return path


def _ink_bbox(image: Image.Image, paper_color: tuple[int, int, int], tolerance: int = 10):
    """คืน bounding box ของพิกเซลที่ต่างจากสีกระดาษอย่างมีนัยสำคัญ (None ถ้าไม่มีเลย)
    ใช้ตรวจว่าข้อความไม่ได้ถูกวางชิดขอบภาพจนอาจถูกตัด
    """
    array = np.array(image.convert("RGB")).astype(np.int16)
    diff = np.abs(array - np.array(paper_color, dtype=np.int16)).sum(axis=2)
    mask = diff > tolerance
    if not mask.any():
        return None
    ys, xs = np.where(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _count_ink_pixels(image: Image.Image, paper_color: tuple[int, int, int], tolerance: int = 10) -> int:
    array = np.array(image.convert("RGB")).astype(np.int16)
    diff = np.abs(array - np.array(paper_color, dtype=np.int16)).sum(axis=2)
    return int((diff > tolerance).sum())


class _TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_dir = Path(self._tmp.name)


class CorpusTests(_TempDirTestCase):
    def _write_corpus(self, rows, header=("text_id", "ground_truth", "language", "notes")):
        path = self.tmp_dir / "corpus.csv"
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def test_loads_valid_corpus(self):
        path = self._write_corpus([["t1", "hello", "en", ""], ["t2", "สวัสดี", "th", "note"]])
        rows = sd.load_corpus(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].text_id, "t1")

    def test_missing_corpus_file_raises(self):
        with self.assertRaises(sd.CorpusError):
            sd.load_corpus(self.tmp_dir / "does_not_exist.csv")

    def test_missing_required_column_raises(self):
        path = self._write_corpus([["t1", "hello", "en"]], header=("text_id", "ground_truth", "language"))
        with self.assertRaises(sd.CorpusError):
            sd.load_corpus(path)

    def test_blank_text_id_rows_skipped(self):
        path = self._write_corpus([["", "placeholder", "en", ""], ["t1", "hello", "en", ""]])
        rows = sd.load_corpus(path)
        self.assertEqual(len(rows), 1)

    def test_duplicate_text_id_raises(self):
        path = self._write_corpus([["t1", "a", "en", ""], ["t1", "b", "en", ""]])
        with self.assertRaises(sd.CorpusError):
            sd.load_corpus(path)

    def test_empty_corpus_raises(self):
        path = self._write_corpus([])
        with self.assertRaises(sd.CorpusError):
            sd.load_corpus(path)

    def test_ground_truth_is_nfc_normalized(self):
        composed = "ก้"
        row = sd.CorpusRow(text_id="t1", ground_truth=composed, language="th", notes="")
        import unicodedata

        self.assertEqual(row.normalized_ground_truth, unicodedata.normalize("NFC", composed))

    def test_example_corpus_is_valid(self):
        example_path = Path(__file__).resolve().parent.parent / "evaluation" / "synthetic" / "corpus.example.csv"
        rows = sd.load_corpus(example_path)
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertIn("ตัวอย่างเท่านั้น", row.notes)


class FontDiscoveryTests(_TempDirTestCase):
    def test_missing_font_dir_raises(self):
        with self.assertRaises(sd.FontDiscoveryError):
            sd.discover_fonts(self.tmp_dir / "no_such_dir")

    def test_empty_font_dir_raises_clear_error(self):
        empty_dir = self.tmp_dir / "empty_fonts"
        empty_dir.mkdir()
        with self.assertRaises(sd.FontDiscoveryError):
            sd.discover_fonts(empty_dir)

    def test_discovers_ttf_and_otf_only_sorted(self):
        font_dir = self.tmp_dir / "fonts"
        font_dir.mkdir()
        _write_latin_test_font(font_dir, "b_font.ttf")
        _write_latin_test_font(font_dir, "a_font.ttf")
        (font_dir / "readme.txt").write_text("not a font")
        (font_dir / "ignored.ttc").write_bytes(b"fake")

        fonts = sd.discover_fonts(font_dir)
        self.assertEqual([f.name for f in fonts], ["a_font.ttf", "b_font.ttf"])

    def test_font_directory_is_not_used_by_default_anywhere(self):
        # generate_dataset ต้องรับ font_paths จากภายนอกเสมอ ไม่มี default ที่ผูกกับ
        # ระบบปฏิบัติการใด ๆ ฝังอยู่ในโมดูล
        source = Path(sd.__file__).read_text(encoding="utf-8")
        self.assertNotIn("/System/Library/Fonts", source)
        self.assertNotIn("C:\\\\Windows\\\\Fonts", source)
        self.assertNotIn("/usr/share/fonts", source)


class FontCoverageTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.font_path = _write_latin_test_font(self.tmp_dir)
        self.font = ImageFont.truetype(str(self.font_path), 20)

    def test_latin_text_has_no_unsupported_characters(self):
        unsupported = sd.find_unsupported_characters(self.font, "Hello World 123")
        self.assertEqual(unsupported, [])

    def test_thai_text_is_unsupported_in_latin_only_font(self):
        # font Latin-only (Aileron) ไม่มี glyph ไทยจริง - ต้องถูกตรวจพบว่าไม่รองรับ
        unsupported = sd.find_unsupported_characters(self.font, "สวัสดี")
        self.assertGreater(len(unsupported), 0)

    def test_whitespace_is_never_flagged_as_unsupported(self):
        unsupported = sd.find_unsupported_characters(self.font, "a b\tc")
        self.assertEqual(unsupported, [])


@skip_without_thai_font
class ThaiRenderingTests(_TempDirTestCase):
    def test_thai_tone_marks_and_vowels_are_not_cropped(self):
        render_config = sd.RenderConfig()
        image = sd.render_text_image(
            "ก้ ไก่ ผู้ใหญ่ เสื้อผ้า ฐาน ญาติ",
            _LOCAL_THAI_FONT,
            40,
            render_config=render_config,
        )
        bbox = _ink_bbox(image, render_config.paper_color)
        self.assertIsNotNone(bbox)
        left, top, right, bottom = bbox
        # ต้องมีระยะห่างจากขอบภาพจริง (ไม่ใช่แค่ไม่เท่ากับ 0 เป๊ะ ๆ) ยืนยันว่า
        # padding ที่เผื่อไว้กันสระ/วรรณยุกต์เพียงพอ ไม่ถูกตัดขอบภาพ
        self.assertGreater(top, 2)
        self.assertLess(bottom, image.height - 3)
        self.assertGreater(left, 2)
        self.assertLess(right, image.width - 3)

    def test_font_reported_as_unsupported_is_empty_for_common_thai_text(self):
        font = ImageFont.truetype(str(_LOCAL_THAI_FONT), 32)
        unsupported = sd.find_unsupported_characters(font, "สวัสดีครับ ยินดีต้อนรับ")
        self.assertEqual(unsupported, [])


class RenderMechanicsTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.font_path = _write_latin_test_font(self.tmp_dir)

    def test_render_preserves_aspect_ratio_across_font_sizes(self):
        small = sd.render_text_image("Hello World", self.font_path, 20)
        large = sd.render_text_image("Hello World", self.font_path, 40)
        # ขนาดใหญ่ขึ้นตามสัดส่วนคร่าว ๆ (ไม่บิดเบี้ยว) - ไม่ยืนยัน exact ratio เพราะ
        # padding/margin เป็นค่าคงที่ ไม่ scale เชิงเส้นตรงเป๊ะ
        self.assertGreater(large.width, small.width)
        self.assertGreater(large.height, small.height)

    def test_multiline_text_increases_height(self):
        single = sd.render_text_image("Hello", self.font_path, 24)
        multi = sd.render_text_image("Hello\nWorld\nFoo", self.font_path, 24)
        self.assertGreater(multi.height, single.height)

    def test_render_output_is_rgb(self):
        image = sd.render_text_image("Hello", self.font_path, 24)
        self.assertEqual(image.mode, "RGB")


class AugmentationOpTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.font_path = _write_latin_test_font(self.tmp_dir)
        self.render_config = sd.RenderConfig()
        self.augment_config = sd.AugmentConfig()
        self.base = sd.render_text_image("Test 123", self.font_path, 32, render_config=self.render_config)

    def _mean(self, image: Image.Image) -> float:
        return float(np.array(image.convert("L")).mean())

    def test_brightness_dark_reduces_mean_pixel_value(self):
        rng = Random(1)
        out, params = sd.op_brightness(self.base, rng, self.augment_config.brightness_dark_factor)
        self.assertLess(self._mean(out), self._mean(self.base))
        self.assertIn("brightness_factor", params)

    def test_brightness_bright_increases_mean_pixel_value(self):
        rng = Random(1)
        out, params = sd.op_brightness(self.base, rng, self.augment_config.brightness_bright_factor)
        self.assertGreater(self._mean(out), self._mean(self.base))
        self.assertIn("brightness_factor", params)

    def test_gamma_dark_darkens_image(self):
        rng = Random(1)
        out, params = sd.op_gamma(self.base, rng, self.augment_config.gamma_dark)
        self.assertLess(self._mean(out), self._mean(self.base))
        self.assertIn("gamma", params)

    def test_gamma_bright_brightens_image(self):
        rng = Random(1)
        out, params = sd.op_gamma(self.base, rng, self.augment_config.gamma_bright)
        self.assertGreaterEqual(self._mean(out), self._mean(self.base))

    def test_contrast_reduction_reduces_std_dev(self):
        rng = Random(1)
        out, params = sd.op_contrast(self.base, rng, self.augment_config.contrast_low_factor)
        base_std = float(np.array(self.base.convert("L")).std())
        out_std = float(np.array(out.convert("L")).std())
        self.assertLess(out_std, base_std)
        self.assertIn("contrast_factor", params)

    def test_grayscale_produces_equal_rgb_channels(self):
        rng = Random(1)
        out, params = sd.op_grayscale(self.base, rng)
        array = np.array(out)
        self.assertTrue(np.array_equal(array[..., 0], array[..., 1]))
        self.assertTrue(np.array_equal(array[..., 1], array[..., 2]))

    def test_gaussian_blur_reduces_sharpness(self):
        import cv2

        rng = Random(1)
        out, params = sd.op_gaussian_blur(self.base, rng, self.augment_config.gaussian_blur_radius)
        base_var = cv2.Laplacian(np.array(self.base.convert("L")), cv2.CV_64F).var()
        out_var = cv2.Laplacian(np.array(out.convert("L")), cv2.CV_64F).var()
        self.assertLess(out_var, base_var)
        self.assertIn("gaussian_blur_radius", params)

    def test_motion_blur_uses_odd_kernel_size(self):
        rng = Random(1)
        out, params = sd.op_motion_blur(self.base, rng, (4, 4), (0.0, 0.0))
        self.assertEqual(out.size, self.base.size)
        self.assertEqual(params["motion_blur_kernel_size"] % 2, 1)

    def test_gaussian_noise_increases_pixel_variance_from_original(self):
        rng = Random(1)
        out, params = sd.op_gaussian_noise(self.base, rng, self.augment_config.noise_sigma)
        diff = np.array(out.convert("L")).astype(np.float64) - np.array(self.base.convert("L")).astype(np.float64)
        self.assertGreater(float(diff.std()), 1.0)
        self.assertIn("noise_sigma", params)

    def test_jpeg_artifacts_changes_pixels_and_keeps_size(self):
        rng = Random(1)
        out, params = sd.op_jpeg_artifacts(self.base, rng, (10, 20))
        self.assertEqual(out.size, self.base.size)
        self.assertFalse(np.array_equal(np.array(out), np.array(self.base)))
        self.assertIn("jpeg_quality", params)
        self.assertGreaterEqual(params["jpeg_quality"], 10)
        self.assertLessEqual(params["jpeg_quality"], 20)

    def test_downscale_upscale_preserves_final_size(self):
        rng = Random(1)
        out, params = sd.op_downscale_upscale(self.base, rng, self.augment_config.downscale_factor)
        self.assertEqual(out.size, self.base.size)
        self.assertIn("downscale_factor", params)


class GeometricNoCropTests(_TempDirTestCase):
    """ตรวจว่า rotate/perspective/zoom_out ไม่ตัดข้อความทิ้งอย่างชัดเจน โดยเทียบ
    จำนวนพิกเซล 'หมึก' (ต่างจากสีกระดาษ) ก่อน/หลัง transform
    """

    def setUp(self):
        super().setUp()
        self.font_path = _write_latin_test_font(self.tmp_dir)
        self.render_config = sd.RenderConfig()
        self.augment_config = sd.AugmentConfig()
        self.base = sd.render_text_image("Test 123 Hello", self.font_path, 36, render_config=self.render_config)

    def test_rotate_does_not_lose_most_ink_pixels(self):
        padded, _ = sd._pad_to_working_canvas(self.base, self.render_config.transform_margin_ratio, self.render_config.paper_color)
        before = _count_ink_pixels(padded, self.render_config.paper_color)
        rng = Random(1)
        out, params = sd.op_rotate(padded, rng, self.augment_config.rotation_degrees, self.render_config.paper_color)
        after = _count_ink_pixels(out, self.render_config.paper_color)
        self.assertGreater(after, before * 0.7)
        self.assertIn("rotation_degrees", params)

    def test_perspective_does_not_lose_most_ink_pixels(self):
        padded, _ = sd._pad_to_working_canvas(self.base, self.render_config.transform_margin_ratio, self.render_config.paper_color)
        before = _count_ink_pixels(padded, self.render_config.paper_color)
        rng = Random(1)
        out, params = sd.op_perspective(padded, rng, self.augment_config.perspective_shift_ratio, self.render_config.paper_color)
        after = _count_ink_pixels(out, self.render_config.paper_color)
        self.assertGreater(after, before * 0.6)
        self.assertIn("perspective_shift_ratio", params)

    def test_zoom_out_reduces_ink_area_but_keeps_some_ink(self):
        padded, _ = sd._pad_to_working_canvas(self.base, self.render_config.transform_margin_ratio, self.render_config.paper_color)
        rng = Random(1)
        out, params = sd.op_zoom_out(self.base, rng, self.augment_config.zoom_out_scale, padded.size, self.render_config.paper_color)
        after = _count_ink_pixels(out, self.render_config.paper_color)
        self.assertGreater(after, 0)
        self.assertIn("zoom_out_scale", params)
        self.assertEqual(out.size, padded.size)


class ApplyVariantTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.font_path = _write_latin_test_font(self.tmp_dir)
        self.render_config = sd.RenderConfig()
        self.augment_config = sd.AugmentConfig()
        self.base = sd.render_text_image("Hello World 42", self.font_path, 32, render_config=self.render_config)

    def test_all_variant_categories_produce_valid_images(self):
        for variant in sd.VARIANT_CATEGORIES:
            with self.subTest(variant=variant):
                rng = sd.sample_rng(1, "sample-text", variant)
                image, params = sd.apply_variant(
                    self.base, variant, rng, render_config=self.render_config, augment_config=self.augment_config
                )
                self.assertGreaterEqual(image.width, self.render_config.min_output_dimension)
                self.assertGreaterEqual(image.height, self.render_config.min_output_dimension)
                self.assertLessEqual(image.width, self.render_config.max_output_dimension)
                self.assertLessEqual(image.height, self.render_config.max_output_dimension)
                self.assertEqual(params["variant"], variant)

    def test_unknown_variant_raises(self):
        rng = Random(1)
        with self.assertRaises(ValueError):
            sd.apply_variant(self.base, "not_a_real_variant", rng, render_config=self.render_config, augment_config=self.augment_config)

    def test_combined_camera_like_uses_between_configured_ops_count(self):
        rng = sd.sample_rng(1, "t", "combined_camera_like")
        _, params = sd.apply_variant(
            self.base, "combined_camera_like", rng, render_config=self.render_config, augment_config=self.augment_config
        )
        lo, hi = self.augment_config.combined_ops_count
        self.assertGreaterEqual(len(params["ops"]), min(lo, len(params["ops"])))
        self.assertLessEqual(len(params["ops"]), hi)

    def test_combined_camera_like_is_not_always_maximally_degraded(self):
        # รันหลาย seed แล้วตรวจว่าจำนวน ops ที่ใช้ไม่ใช่ค่าสูงสุดตายตัวทุกครั้ง
        op_counts = set()
        for seed in range(10):
            rng = sd.sample_rng(seed, "t", "combined_camera_like")
            _, params = sd.apply_variant(
                self.base, "combined_camera_like", rng, render_config=self.render_config, augment_config=self.augment_config
            )
            op_counts.add(len(params["ops"]))
        self.assertGreater(len(op_counts), 1, "จำนวน ops ที่ใช้ควรแตกต่างกันไปตาม seed ไม่ใช่ค่าคงที่เดียวเสมอ")

    def test_max_dimension_clamp_is_applied_and_recorded(self):
        tiny_config = sd.RenderConfig(max_output_dimension=50, min_output_dimension=5)
        rng = sd.sample_rng(1, "t", "rotated")
        image, params = sd.apply_variant(
            self.base, "rotated", rng, render_config=tiny_config, augment_config=self.augment_config
        )
        self.assertLessEqual(max(image.size), 50)
        self.assertTrue(params["final_resize_applied"])


class DeterminismTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.font_dir = self.tmp_dir / "fonts"
        self.font_dir.mkdir()
        _write_latin_test_font(self.font_dir, "test.ttf")
        self.fonts = sd.discover_fonts(self.font_dir)
        self.corpus = [
            sd.CorpusRow(text_id="t1", ground_truth="Hello World", language="en", notes=""),
            sd.CorpusRow(text_id="t2", ground_truth="Testing 123", language="en", notes=""),
        ]

    def _run(self, seed: int, run_name: str):
        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", run_name)
        result = sd.generate_dataset(
            corpus=self.corpus, font_paths=self.fonts, run_dir=run_dir,
            variants_per_text=4, seed=seed,
        )
        return result

    def test_same_seed_produces_identical_files_and_params(self):
        result_a = self._run(42, "run-a")
        result_b = self._run(42, "run-b")

        self.assertEqual(len(result_a.samples), len(result_b.samples))
        for sample_a, sample_b in zip(result_a.samples, result_b.samples):
            self.assertEqual(sample_a.sample_id, sample_b.sample_id)
            self.assertEqual(sample_a.font, sample_b.font)
            self.assertEqual(sample_a.font_size, sample_b.font_size)
            self.assertEqual(sample_a.augmentation_parameters, sample_b.augmentation_parameters)

            bytes_a = (self.tmp_dir / "out" / "run-a" / sample_a.image_path).read_bytes()
            bytes_b = (self.tmp_dir / "out" / "run-b" / sample_b.image_path).read_bytes()
            self.assertEqual(bytes_a, bytes_b, f"ไฟล์ภาพต่างกันสำหรับ {sample_a.sample_id} ทั้งที่ seed เดียวกัน")

    def test_different_seed_produces_different_parameters(self):
        result_a = self._run(1, "run-seed-1")
        result_b = self._run(2, "run-seed-2")

        differences = 0
        for sample_a, sample_b in zip(result_a.samples, result_b.samples):
            if sample_a.augmentation_parameters != sample_b.augmentation_parameters or sample_a.font_size != sample_b.font_size:
                differences += 1
        self.assertGreater(differences, 0, "seed ต่างกันควรให้พารามิเตอร์ augmentation ต่างกันอย่างน้อยบางส่วน")


class ManifestAndMetadataTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.font_dir = self.tmp_dir / "fonts"
        self.font_dir.mkdir()
        _write_latin_test_font(self.font_dir, "test.ttf")
        self.fonts = sd.discover_fonts(self.font_dir)
        self.corpus_path = self.tmp_dir / "corpus.csv"
        with open(self.corpus_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["text_id", "ground_truth", "language", "notes"])
            writer.writerow(["t1", "Hello World", "en", ""])
        self.corpus = sd.load_corpus(self.corpus_path)

    def test_manifest_row_contains_all_expected_fields(self):
        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        result = sd.generate_dataset(
            corpus=self.corpus, font_paths=self.fonts, run_dir=run_dir, variants_per_text=2, seed=5,
        )
        row = result.samples[0].to_manifest_row()
        self.assertEqual(set(row.keys()), set(sd.MANIFEST_FIELDNAMES))
        self.assertEqual(row["synthetic"], "true")
        self.assertTrue(row["image_path"].startswith("images/"))

    def test_manifest_is_readable_by_existing_evaluator_loader(self):
        import ocr_evaluation as ev

        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        result = sd.generate_dataset(
            corpus=self.corpus, font_paths=self.fonts, run_dir=run_dir, variants_per_text=2, seed=5,
        )
        manifest_path = run_dir / "manifest.csv"
        sd.write_manifest_csv(result.samples, manifest_path)

        rows = ev.load_manifest(manifest_path)
        self.assertEqual(len(rows), len(result.samples))
        self.assertTrue(all(row.synthetic for row in rows))
        self.assertTrue(all(row.variant for row in rows))
        self.assertEqual(ev.determine_dataset_label(rows), "synthetic")

    def test_run_metadata_json_has_required_keys(self):
        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        result = sd.generate_dataset(
            corpus=self.corpus, font_paths=self.fonts, run_dir=run_dir, variants_per_text=2, seed=5,
        )
        metadata_path = run_dir / "run_metadata.json"
        sd.write_run_metadata_json(
            result.run_metadata, metadata_path, corpus_path=self.corpus_path,
            render_config=sd.DEFAULT_RENDER_CONFIG, augment_config=sd.DEFAULT_AUGMENT_CONFIG,
        )
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        for key in (
            "generator_version", "created_at", "seed", "corpus_path", "corpus_sha256",
            "fonts_used", "variants_per_text", "success_count", "failure_count",
            "render_config", "augment_config",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["seed"], 5)
        self.assertEqual(len(payload["corpus_sha256"]), 64)


class GroupIdAndLeakageTests(_TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.font_dir = self.tmp_dir / "fonts"
        self.font_dir.mkdir()
        _write_latin_test_font(self.font_dir, "test.ttf")
        self.fonts = sd.discover_fonts(self.font_dir)
        self.corpus = [
            sd.CorpusRow(text_id="alpha", ground_truth="Alpha text", language="en", notes=""),
            sd.CorpusRow(text_id="beta", ground_truth="Beta text", language="en", notes=""),
        ]

    def test_all_variants_of_same_text_share_group_id(self):
        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        result = sd.generate_dataset(
            corpus=self.corpus, font_paths=self.fonts, run_dir=run_dir, variants_per_text=6, seed=1,
        )
        alpha_groups = {s.group_id for s in result.samples if s.source_text_id == "alpha"}
        beta_groups = {s.group_id for s in result.samples if s.source_text_id == "beta"}
        self.assertEqual(len(alpha_groups), 1)
        self.assertEqual(len(beta_groups), 1)
        self.assertNotEqual(alpha_groups, beta_groups)

    def test_splits_never_separate_a_single_group(self):
        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        proportions = sd.parse_split_spec("train:0.6,val:0.2,test:0.2")
        result = sd.generate_dataset(
            corpus=self.corpus, font_paths=self.fonts, run_dir=run_dir, variants_per_text=6, seed=1,
            split_proportions=proportions,
        )
        by_group: dict[str, set[str]] = {}
        for sample in result.samples:
            by_group.setdefault(sample.group_id, set()).add(sample.split)
        for group_id, splits in by_group.items():
            self.assertEqual(len(splits), 1, f"group {group_id} ถูกกระจายไปมากกว่าหนึ่ง split: {splits}")

    def test_validate_no_leakage_raises_on_artificial_leakage(self):
        leaking_samples = [
            sd.Sample(
                sample_id="a1", source_text_id="alpha", group_id="grp_alpha", image_path="images/a1.png",
                ground_truth="x", language="en", notes="", font="f.ttf", font_size=20, seed=1,
                variant="clean", augmentation_parameters={}, split="train",
            ),
            sd.Sample(
                sample_id="a2", source_text_id="alpha", group_id="grp_alpha", image_path="images/a2.png",
                ground_truth="x", language="en", notes="", font="f.ttf", font_size=20, seed=1,
                variant="dark", augmentation_parameters={}, split="test",
            ),
        ]
        with self.assertRaises(sd.LeakageError):
            sd.validate_no_leakage(leaking_samples)

    def test_validate_no_leakage_passes_for_consistent_splits(self):
        samples = [
            sd.Sample(
                sample_id="a1", source_text_id="alpha", group_id="grp_alpha", image_path="images/a1.png",
                ground_truth="x", language="en", notes="", font="f.ttf", font_size=20, seed=1,
                variant="clean", augmentation_parameters={}, split="train",
            ),
            sd.Sample(
                sample_id="a2", source_text_id="alpha", group_id="grp_alpha", image_path="images/a2.png",
                ground_truth="x", language="en", notes="", font="f.ttf", font_size=20, seed=1,
                variant="dark", augmentation_parameters={}, split="train",
            ),
        ]
        sd.validate_no_leakage(samples)  # ไม่ควร raise


class SplitConfigTests(unittest.TestCase):
    def test_valid_spec_parses(self):
        result = sd.parse_split_spec("train:0.7,val:0.15,test:0.15")
        self.assertAlmostEqual(sum(result.values()), 1.0)
        self.assertEqual(set(result.keys()), {"train", "val", "test"})

    def test_ratios_not_summing_to_one_raises(self):
        with self.assertRaises(sd.SplitConfigError):
            sd.parse_split_spec("train:0.5,test:0.2")

    def test_non_numeric_ratio_raises(self):
        with self.assertRaises(sd.SplitConfigError):
            sd.parse_split_spec("train:abc,test:0.5")

    def test_missing_colon_raises(self):
        with self.assertRaises(sd.SplitConfigError):
            sd.parse_split_spec("train0.7,test0.3")

    def test_empty_spec_raises(self):
        with self.assertRaises(sd.SplitConfigError):
            sd.parse_split_spec("")

    def test_assign_splits_is_deterministic_per_seed(self):
        proportions = {"train": 0.5, "test": 0.5}
        groups = [f"grp_{i}" for i in range(20)]
        first = sd.assign_splits(groups, proportions, seed=7)
        second = sd.assign_splits(groups, proportions, seed=7)
        self.assertEqual(first, second)


class RunOverwriteProtectionTests(_TempDirTestCase):
    def test_fresh_run_directory_is_created(self):
        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        self.assertTrue(run_dir.is_dir())
        self.assertTrue((run_dir / "images").is_dir())

    def test_existing_completed_run_is_not_overwritten_without_force(self):
        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        (run_dir / "manifest.csv").write_text("image_path,ground_truth,language,notes\n", encoding="utf-8")

        with self.assertRaises(sd.RunAlreadyExistsError):
            sd.prepare_run_directory(self.tmp_dir / "out", "run1")

        # โฟลเดอร์และไฟล์เดิมต้องยังอยู่ครบ ไม่ถูกลบไม่ว่ากรณีใด
        self.assertTrue(run_dir.is_dir())
        self.assertTrue((run_dir / "manifest.csv").is_file())

    def test_force_allows_reusing_existing_run_directory(self):
        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        (run_dir / "manifest.csv").write_text("image_path,ground_truth,language,notes\n", encoding="utf-8")

        reused_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1", force=True)
        self.assertEqual(reused_dir, run_dir)
        self.assertTrue(run_dir.is_dir())


class MissingInputTests(_TempDirTestCase):
    def test_generate_dataset_requires_at_least_one_font(self):
        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        corpus = [sd.CorpusRow(text_id="t1", ground_truth="Hello", language="en", notes="")]
        with self.assertRaises(sd.FontDiscoveryError):
            sd.generate_dataset(corpus=corpus, font_paths=[], run_dir=run_dir, variants_per_text=1, seed=1)

    def test_unusable_font_file_is_recorded_as_failure_not_a_crash(self):
        font_dir = self.tmp_dir / "fonts"
        font_dir.mkdir()
        bad_font = font_dir / "not_really_a_font.ttf"
        bad_font.write_bytes(b"this is not valid font data at all")

        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        corpus = [sd.CorpusRow(text_id="t1", ground_truth="Hello", language="en", notes="")]
        result = sd.generate_dataset(
            corpus=corpus, font_paths=[bad_font], run_dir=run_dir, variants_per_text=2, seed=1,
        )
        self.assertEqual(result.run_metadata["success_count"], 0)
        self.assertEqual(result.run_metadata["failure_count"], 2)
        self.assertEqual(len(result.failures), 2)


class SyntheticFlagTests(_TempDirTestCase):
    def test_every_generated_sample_is_marked_synthetic(self):
        font_dir = self.tmp_dir / "fonts"
        font_dir.mkdir()
        _write_latin_test_font(font_dir, "test.ttf")
        fonts = sd.discover_fonts(font_dir)
        corpus = [sd.CorpusRow(text_id="t1", ground_truth="Hello", language="en", notes="")]

        run_dir = sd.prepare_run_directory(self.tmp_dir / "out", "run1")
        result = sd.generate_dataset(corpus=corpus, font_paths=fonts, run_dir=run_dir, variants_per_text=3, seed=1)

        self.assertTrue(result.samples)
        self.assertTrue(all(sample.synthetic for sample in result.samples))


class NoSerialCouplingTests(unittest.TestCase):
    """synthetic_dataset.py และ generate_synthetic_ocr.py ต้องไม่มีโค้ดที่ยุ่งกับ
    Serial/ESP32/Braille เลย - Step 3.5 เป็นเรื่อง OCR evaluation เท่านั้น

    ตรวจจาก "หลักฐานการเชื่อมต่อจริง" (import serial, ser_conn, route /send,
    ตาราง Braille) เหมือนแบบแผนเดิมใน tests/test_ocr_evaluation.py ไม่ใช้การห้าม
    คำว่า "serial"/"esp32" แบบเหมารวม เพราะ docstring ของไฟล์เหล่านี้ตั้งใจระบุไว้
    ตรง ๆ ว่า "ไม่ยุ่งเกี่ยวกับ Serial/ESP32" ซึ่งเป็นคำอธิบายที่ดี ไม่ใช่การเชื่อมต่อจริง
    """

    def _assert_no_real_coupling(self, source: str) -> None:
        self.assertNotIn("import serial", source)
        self.assertNotIn("ser_conn", source)
        self.assertNotIn("/send", source)
        self.assertNotIn("THAI_BRAILLE_MAP", source)
        self.assertNotIn("init_serial", source)

    def test_synthetic_dataset_module_has_no_serial_coupling(self):
        source = Path(sd.__file__).read_text(encoding="utf-8")
        self._assert_no_real_coupling(source)

    def test_generate_synthetic_ocr_cli_has_no_serial_coupling(self):
        cli_path = Path(__file__).resolve().parent.parent / "generate_synthetic_ocr.py"
        source = cli_path.read_text(encoding="utf-8")
        self._assert_no_real_coupling(source)


if __name__ == "__main__":
    unittest.main()
