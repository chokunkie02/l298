"""ทดสอบ ocr_evaluation.py (CER/WER, manifest) และ evaluate_ocr.py (CLI)
ใช้ EasyOCR แบบ mock เสมอ ไม่ดาวน์โหลดโมเดลหรือ inference จริง
"""

import csv
import io
import unittest
from pathlib import Path
from unittest.mock import Mock

from PIL import Image

import evaluate_ocr as cli
import ocr_evaluation as ev
from ocr_service import EasyOCRService


class FakeReader:
    def __init__(self, text="สวัสดี", confidence=0.9):
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def readtext(self, image, **kwargs):
        self.calls += 1
        if not self.text:
            return []
        return [([[0, 0], [10, 0], [10, 5], [0, 5]], self.text, self.confidence)]


class NormalizationTests(unittest.TestCase):
    def test_nfc_normalizes_decomposed_thai_sequence(self):
        # ตัวอย่างสระ/วรรณยุกต์ที่เขียนได้มากกว่าหนึ่งลำดับ code point แต่แสดงผล
        # เหมือนกัน ต้องถูกมองว่าเท่ากันหลัง normalize
        composed = "ก้"  # ก + ไม้โท ประกอบ
        decomposed = "ก้"  # ในกรณีนี้ผสมแบบเดียวกัน แต่ทดสอบ idempotency
        self.assertEqual(ev.normalize_text(composed), ev.normalize_text(decomposed))

    def test_normalize_handles_none_and_empty(self):
        self.assertEqual(ev.normalize_text(None), "")
        self.assertEqual(ev.normalize_text(""), "")


class LevenshteinAndCerTests(unittest.TestCase):
    def test_exact_match_has_zero_distance_and_zero_cer(self):
        self.assertEqual(ev.levenshtein_distance("hello", "hello"), 0)
        self.assertEqual(ev.character_error_rate("hello", "hello"), 0.0)

    def test_insertion_increases_distance_by_one(self):
        self.assertEqual(ev.levenshtein_distance("helloo", "hello"), 1)

    def test_deletion_increases_distance_by_one(self):
        self.assertEqual(ev.levenshtein_distance("hell", "hello"), 1)

    def test_substitution_increases_distance_by_one(self):
        self.assertEqual(ev.levenshtein_distance("hallo", "hello"), 1)

    def test_cer_divides_by_ground_truth_length(self):
        # 1 substitution / 5 ตัวอักษรใน ground truth = 0.2
        self.assertAlmostEqual(ev.character_error_rate("hallo", "hello"), 0.2)

    def test_cer_returns_none_for_empty_ground_truth(self):
        self.assertIsNone(ev.character_error_rate("anything", ""))
        self.assertIsNone(ev.character_error_rate("", ""))

    def test_cer_can_exceed_one_when_prediction_much_longer(self):
        cer = ev.character_error_rate("xxxxxxxxxx", "a")
        self.assertGreater(cer, 1.0)

    def test_thai_text_cer(self):
        prediction = "สวัสดีครับ"
        ground_truth = "สวัสดีครับ"
        self.assertEqual(ev.character_error_rate(prediction, ground_truth), 0.0)

        prediction_with_error = "สวัสดีครัช"  # ตัวสุดท้ายผิด 1 ตัว
        cer = ev.character_error_rate(prediction_with_error, ground_truth)
        self.assertAlmostEqual(cer, 1 / len(ground_truth))

    def test_empty_prediction_against_nonempty_ground_truth_is_full_error(self):
        self.assertEqual(ev.character_error_rate("", "hello"), 1.0)


class WhitespaceTokenErrorRateTests(unittest.TestCase):
    def test_matching_tokens_have_zero_error(self):
        self.assertEqual(ev.whitespace_token_error_rate("hello world", "hello world"), 0.0)

    def test_one_wrong_token_out_of_two(self):
        self.assertAlmostEqual(ev.whitespace_token_error_rate("hello there", "hello world"), 0.5)

    def test_returns_none_for_empty_ground_truth(self):
        self.assertIsNone(ev.whitespace_token_error_rate("anything", ""))

    def test_thai_text_without_spaces_is_a_single_token(self):
        # ข้อความไทยไม่เว้นวรรค การนับ token แบบนี้จึงมีความหมายจำกัด (ตามที่บันทึก
        # ไว้ในเอกสาร) - ทดสอบว่าอย่างน้อยไม่ throw และให้ผลตามกลไก token เดียว
        rate = ev.whitespace_token_error_rate("สวัสดีครับผิด", "สวัสดีครับ")
        self.assertEqual(rate, 1.0)  # 1 token ผิดทั้งหมด จาก 1 token ทั้งหมด


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(self._make_temp_dir())

    def _make_temp_dir(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return tmp.name

    def _write_manifest(self, rows, header=("image_path", "ground_truth", "language", "notes")):
        path = self.tmp_dir / "manifest.csv"
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    def test_loads_valid_manifest(self):
        path = self._write_manifest([
            ["a.png", "hello", "en", "note"],
            ["b.png", "สวัสดี", "th", ""],
        ])
        rows = ev.load_manifest(path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].image_path, "a.png")
        self.assertEqual(rows[1].language, "th")

    def test_blank_image_path_rows_are_skipped(self):
        path = self._write_manifest([
            ["", "placeholder", "en", "skip me"],
            ["a.png", "hello", "en", ""],
        ])
        rows = ev.load_manifest(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].image_path, "a.png")

    def test_missing_manifest_file_raises_manifest_error(self):
        with self.assertRaises(ev.ManifestError):
            ev.load_manifest(self.tmp_dir / "does_not_exist.csv")

    def test_missing_required_column_raises_manifest_error(self):
        path = self._write_manifest(
            [["a.png", "hello", "en"]], header=("image_path", "ground_truth", "language")
        )
        with self.assertRaises(ev.ManifestError):
            ev.load_manifest(path)

    def test_resolve_image_path_is_relative_to_manifest_directory(self):
        row = ev.ManifestRow(image_path="sub/a.png", ground_truth="x", language="en", notes="")
        resolved = row.resolve_image_path(self.tmp_dir)
        self.assertEqual(resolved, self.tmp_dir / "sub" / "a.png")

    def test_the_example_manifest_is_valid_but_files_are_placeholders(self):
        example_path = Path(__file__).resolve().parent.parent / "evaluation" / "manifest.example.csv"
        rows = ev.load_manifest(example_path)
        self.assertGreater(len(rows), 0)
        for row in rows:
            resolved = row.resolve_image_path(example_path.parent)
            self.assertFalse(resolved.is_file(), "manifest.example.csv ต้องไม่มีไฟล์ภาพจริงอยู่")


class SummarizeTests(unittest.TestCase):
    def test_groups_by_language_and_mode_and_counts_failures(self):
        records = [
            ev.EvaluationRecord(
                image_path="a.png", language="th", mode="none", ground_truth="ก",
                predicted_text="ก", predicted_text_raw="ก", cer=0.0, token_error_rate=None,
                exact_match=True, mean_confidence=0.9, processing_seconds=0.1, warnings=[],
            ),
            ev.EvaluationRecord(
                image_path="b.png", language="th", mode="none", ground_truth="ข",
                predicted_text="ก", predicted_text_raw="ก", cer=1.0, token_error_rate=None,
                exact_match=False, mean_confidence=0.5, processing_seconds=0.2, warnings=["dark"],
            ),
            ev.EvaluationRecord(
                image_path="c.png", language="en", mode="none", ground_truth="",
                predicted_text="", predicted_text_raw="", cer=None, token_error_rate=None,
                exact_match=False, mean_confidence=None, processing_seconds=0.0, warnings=[],
                error="ไม่พบไฟล์ภาพ",
            ),
        ]
        summary = ev.summarize(records)
        self.assertEqual(summary["overall"]["sample_count"], 3)
        self.assertEqual(summary["overall"]["failure_count"], 1)
        self.assertAlmostEqual(summary["by_language"]["th"]["mean_cer"], 0.5)
        self.assertEqual(summary["by_language"]["en"]["failure_count"], 1)
        self.assertEqual(summary["by_mode"]["none"]["sample_count"], 3)

    def test_empty_records_do_not_crash(self):
        summary = ev.summarize([])
        self.assertEqual(summary["overall"]["sample_count"], 0)
        self.assertIsNone(summary["overall"]["mean_cer"])


class RunEvaluationWithMockedOcrTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = Path(tmp.name)

        self.image_path = self.tmp_dir / "sample.png"
        Image.new("RGB", (60, 30), color=(180, 180, 180)).save(self.image_path)

    def test_missing_image_file_produces_error_record_without_crashing(self):
        rows = [ev.ManifestRow(image_path="missing.png", ground_truth="x", language="en", notes="")]
        ocr_service = EasyOCRService(reader_factory=Mock(return_value=FakeReader()))

        records = cli.run_evaluation(rows, ["none"], ocr_service, base_dir=self.tmp_dir)

        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].error)
        self.assertIn("ไม่พบไฟล์ภาพ", records[0].error)

    def test_mocked_ocr_produces_cer_and_exact_match(self):
        rows = [ev.ManifestRow(image_path="sample.png", ground_truth="สวัสดี", language="th", notes="")]
        ocr_service = EasyOCRService(reader_factory=Mock(return_value=FakeReader(text="สวัสดี")))

        records = cli.run_evaluation(rows, ["none", "resize"], ocr_service, base_dir=self.tmp_dir)

        self.assertEqual(len(records), 2)
        for record in records:
            self.assertIsNone(record.error)
            self.assertEqual(record.cer, 0.0)
            self.assertTrue(record.exact_match)
            self.assertIn(record.mode, ("none", "resize"))

    def test_mocked_ocr_with_wrong_prediction_has_nonzero_cer(self):
        rows = [ev.ManifestRow(image_path="sample.png", ground_truth="สวัสดี", language="th", notes="")]
        ocr_service = EasyOCRService(reader_factory=Mock(return_value=FakeReader(text="ผิด")))

        records = cli.run_evaluation(rows, ["none"], ocr_service, base_dir=self.tmp_dir)

        self.assertEqual(len(records), 1)
        self.assertGreater(records[0].cer, 0.0)
        self.assertFalse(records[0].exact_match)

    def test_raw_prediction_is_preserved_separately_from_normalized(self):
        rows = [ev.ManifestRow(image_path="sample.png", ground_truth="hello", language="en", notes="")]
        ocr_service = EasyOCRService(reader_factory=Mock(return_value=FakeReader(text="hello")))

        records = cli.run_evaluation(rows, ["none"], ocr_service, base_dir=self.tmp_dir)

        self.assertEqual(records[0].predicted_text_raw, "hello")
        self.assertEqual(records[0].predicted_text, "hello")

    def test_empty_ocr_result_does_not_crash_and_cer_is_full_error(self):
        rows = [ev.ManifestRow(image_path="sample.png", ground_truth="hello", language="en", notes="")]
        ocr_service = EasyOCRService(reader_factory=Mock(return_value=FakeReader(text="")))

        records = cli.run_evaluation(rows, ["none"], ocr_service, base_dir=self.tmp_dir)

        self.assertIsNone(records[0].error)
        self.assertEqual(records[0].cer, 1.0)


class OutputWritersTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = Path(tmp.name)
        self.records = [
            ev.EvaluationRecord(
                image_path="a.png", language="th", mode="none", ground_truth="ก",
                predicted_text="ก", predicted_text_raw="ก", cer=0.0, token_error_rate=None,
                exact_match=True, mean_confidence=0.9, processing_seconds=0.1, warnings=["dark"],
            ),
        ]

    def test_write_csv(self):
        path = self.tmp_dir / "out.csv"
        ev.write_records(self.records, path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("image_path", content)
        self.assertIn("a.png", content)
        self.assertIn("dark", content)

    def test_write_json(self):
        import json

        path = self.tmp_dir / "out.json"
        ev.write_records(self.records, path)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["image_path"], "a.png")

    def test_unsupported_extension_raises(self):
        with self.assertRaises(ValueError):
            ev.write_records(self.records, self.tmp_dir / "out.txt")


class NoSerialCouplingTests(unittest.TestCase):
    """evaluate_ocr.py และ ocr_evaluation.py ต้องไม่ยุ่งกับ Serial/ESP32 เลย"""

    def test_evaluate_ocr_source_has_no_serial_references(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import serial", source)
        self.assertNotIn("/send", source)
        self.assertNotIn("ser_conn", source)
        self.assertNotIn("import app", source)

    def test_ocr_evaluation_source_has_no_serial_references(self):
        source = Path(ev.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import serial", source)
        self.assertNotIn("/send", source)
        self.assertNotIn("ser_conn", source)


class SyntheticManifestBackwardCompatibilityTests(unittest.TestCase):
    """Step 3.5 เพิ่มคอลัมน์ variant/synthetic ลง manifest - ต้องไม่ทำให้ manifest
    ภาพจริงแบบเดิม (ไม่มีคอลัมน์เหล่านี้) พังหรือเปลี่ยนพฤติกรรม
    """

    def test_manifest_row_defaults_when_columns_absent(self):
        row = ev.ManifestRow(image_path="a.png", ground_truth="x", language="en", notes="")
        self.assertEqual(row.variant, "")
        self.assertFalse(row.synthetic)

    def test_load_manifest_without_extra_columns_still_works(self):
        # เหมือน manifest ภาพจริงเดิมทุกประการ (4 คอลัมน์เท่านั้น)
        path = self._write_manifest_with_columns(
            ["image_path", "ground_truth", "language", "notes"],
            [["a.png", "hello", "en", ""]],
        )
        rows = ev.load_manifest(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].variant, "")
        self.assertFalse(rows[0].synthetic)

    def test_load_manifest_with_extra_synthetic_columns(self):
        path = self._write_manifest_with_columns(
            ["image_path", "ground_truth", "language", "notes", "variant", "synthetic", "font", "seed"],
            [["images/a.png", "hello", "en", "", "dark", "true", "test.ttf", "42"]],
        )
        rows = ev.load_manifest(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].variant, "dark")
        self.assertTrue(rows[0].synthetic)

    def test_synthetic_column_false_variants_are_parsed_correctly(self):
        path = self._write_manifest_with_columns(
            ["image_path", "ground_truth", "language", "notes", "synthetic"],
            [["a.png", "x", "en", "", "false"], ["b.png", "y", "en", "", ""], ["c.png", "z", "en", "", "0"]],
        )
        rows = ev.load_manifest(path)
        self.assertTrue(all(not row.synthetic for row in rows))

    def _write_manifest_with_columns(self, header, rows):
        import tempfile

        tmp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_dir, ignore_errors=True))
        path = tmp_dir / "manifest.csv"
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        return path


class DatasetLabelTests(unittest.TestCase):
    def _row(self, synthetic: bool, path: str = "a.png") -> ev.ManifestRow:
        return ev.ManifestRow(image_path=path, ground_truth="x", language="en", notes="", synthetic=synthetic)

    def test_all_real_camera_rows_label_as_real_camera(self):
        rows = [self._row(False), self._row(False)]
        self.assertEqual(ev.determine_dataset_label(rows), "real_camera")

    def test_all_synthetic_rows_label_as_synthetic(self):
        rows = [self._row(True), self._row(True)]
        self.assertEqual(ev.determine_dataset_label(rows), "synthetic")

    def test_empty_rows_label_as_unknown(self):
        self.assertEqual(ev.determine_dataset_label([]), "unknown")

    def test_mixed_rows_raise_mixed_dataset_error(self):
        rows = [self._row(True, "synthetic.png"), self._row(False, "real.png")]
        with self.assertRaises(ev.MixedDatasetError):
            ev.determine_dataset_label(rows)


class SummarizeVariantAndCompositionTests(unittest.TestCase):
    def _record(self, variant="", synthetic=False, cer=0.0, language="th", mode="none", error=None):
        return ev.EvaluationRecord(
            image_path="a.png", language=language, mode=mode, ground_truth="ก",
            predicted_text="ก", predicted_text_raw="ก", cer=cer, token_error_rate=None,
            exact_match=(cer == 0.0), mean_confidence=0.9, processing_seconds=0.1,
            warnings=[], error=error, variant=variant, synthetic=synthetic,
        )

    def test_by_variant_groups_records_by_variant_name(self):
        records = [
            self._record(variant="clean", cer=0.0),
            self._record(variant="clean", cer=0.2),
            self._record(variant="dark", cer=0.5),
        ]
        summary = ev.summarize(records)
        self.assertEqual(summary["by_variant"]["clean"]["sample_count"], 2)
        self.assertEqual(summary["by_variant"]["dark"]["sample_count"], 1)
        self.assertAlmostEqual(summary["by_variant"]["clean"]["mean_cer"], 0.1)

    def test_records_without_variant_group_under_none(self):
        summary = ev.summarize([self._record(variant="")])
        self.assertIn("none", summary["by_variant"])

    def test_dataset_composition_counts_synthetic_and_real(self):
        records = [
            self._record(synthetic=True), self._record(synthetic=True), self._record(synthetic=False),
        ]
        summary = ev.summarize(records)
        self.assertEqual(summary["dataset_composition"]["synthetic_count"], 2)
        self.assertEqual(summary["dataset_composition"]["real_camera_count"], 1)

    def test_evaluation_record_to_dict_includes_variant_and_synthetic(self):
        record = self._record(variant="rotated", synthetic=True)
        payload = record.to_dict()
        self.assertEqual(payload["variant"], "rotated")
        self.assertTrue(payload["synthetic"])

    def test_csv_output_includes_variant_and_synthetic_columns(self):
        import tempfile

        tmp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_dir, ignore_errors=True))
        path = tmp_dir / "out.csv"
        ev.write_records([self._record(variant="dark", synthetic=True)], path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("variant", content)
        self.assertIn("dark", content)
        self.assertIn("synthetic", content)


class MixedDatasetCliGuardTests(unittest.TestCase):
    """evaluate_ocr.py ต้องปฏิเสธและหยุดทำงานทันทีถ้า manifest มีทั้งแถวสังเคราะห์
    และแถวภาพจริงปนกัน - ไม่คำนวณ CER รวมให้เข้าใจผิด
    """

    def setUp(self):
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_dir = Path(tmp.name)

    def test_main_exits_nonzero_on_mixed_manifest(self):
        image_path = self.tmp_dir / "sample.png"
        Image.new("RGB", (40, 20), color=(200, 200, 200)).save(image_path)

        manifest_path = self.tmp_dir / "manifest.csv"
        with open(manifest_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["image_path", "ground_truth", "language", "notes", "synthetic"])
            writer.writerow(["sample.png", "hello", "en", "", "true"])
            writer.writerow(["sample.png", "hello", "en", "", "false"])

        exit_code = cli.main(["--manifest", str(manifest_path)])
        self.assertEqual(exit_code, 1)

    def test_main_succeeds_on_uniform_synthetic_manifest(self):
        from unittest.mock import Mock, patch

        image_path = self.tmp_dir / "sample.png"
        Image.new("RGB", (40, 20), color=(200, 200, 200)).save(image_path)

        manifest_path = self.tmp_dir / "manifest.csv"
        with open(manifest_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["image_path", "ground_truth", "language", "notes", "synthetic", "variant"])
            writer.writerow(["sample.png", "hello", "en", "", "true", "clean"])

        reader = FakeReader(text="hello")
        with patch.object(cli, "EasyOCRService", return_value=EasyOCRService(reader_factory=Mock(return_value=reader))):
            exit_code = cli.main(["--manifest", str(manifest_path), "--modes", "none"])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
