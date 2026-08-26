"""ทดสอบ braille_translation.py: normalization (NFC, CRLF/CR, ความยาว, ว่างเปล่า),
line boundaries, orchestration (translate_text) กับ FakeBrailleTranslator,
และ error path ทั้งหมด ไม่ต้องติดตั้ง Liblouis เลย
"""

import ast
import pathlib
import unittest

import braille_translation as bt


class NormalizationTests(unittest.TestCase):
    def test_accepts_plain_string(self):
        result = bt.normalize_text_for_braille("hello")
        self.assertEqual(result.normalized_text, "hello")
        self.assertFalse(result.changed_by_normalization)

    def test_rejects_non_string_types(self):
        for bad in (None, 123, 1.5, [], {}, True):
            with self.subTest(bad=bad):
                with self.assertRaises(bt.InvalidInputTypeError):
                    bt.normalize_text_for_braille(bad)

    def test_crlf_normalized_to_lf(self):
        result = bt.normalize_text_for_braille("a\r\nb")
        self.assertEqual(result.normalized_text, "a\nb")
        self.assertTrue(result.changed_by_normalization)

    def test_standalone_cr_normalized_to_lf(self):
        result = bt.normalize_text_for_braille("a\rb")
        self.assertEqual(result.normalized_text, "a\nb")
        self.assertTrue(result.changed_by_normalization)

    def test_mixed_crlf_and_cr_and_lf(self):
        result = bt.normalize_text_for_braille("a\r\nb\rc\nd")
        self.assertEqual(result.normalized_text, "a\nb\nc\nd")

    def test_nfc_normalization_applied(self):
        import unicodedata

        decomposed = unicodedata.normalize("NFD", "café")
        result = bt.normalize_text_for_braille(decomposed)
        self.assertEqual(result.normalized_text, unicodedata.normalize("NFC", decomposed))

    def test_thai_combining_characters_are_nfc_normalized(self):
        import unicodedata

        composed = "ก้"
        decomposed = unicodedata.normalize("NFD", composed)
        result = bt.normalize_text_for_braille(decomposed)
        self.assertEqual(result.normalized_text, unicodedata.normalize("NFC", composed))

    def test_meaningful_spaces_are_preserved(self):
        result = bt.normalize_text_for_braille("hello   world")
        self.assertEqual(result.normalized_text, "hello   world")

    def test_empty_string_rejected(self):
        with self.assertRaises(bt.EmptyTextError):
            bt.normalize_text_for_braille("")

    def test_whitespace_only_string_rejected(self):
        with self.assertRaises(bt.EmptyTextError):
            bt.normalize_text_for_braille("   \n\t  ")

    def test_text_within_max_length_is_accepted(self):
        bt.normalize_text_for_braille("a" * 100, max_length=100)

    def test_text_over_max_length_rejected(self):
        with self.assertRaises(bt.TextTooLongError):
            bt.normalize_text_for_braille("a" * 101, max_length=100)

    def test_lines_split_on_lf(self):
        result = bt.normalize_text_for_braille("line1\nline2\nline3")
        self.assertEqual(result.lines, ("line1", "line2", "line3"))

    def test_single_line_has_one_element(self):
        result = bt.normalize_text_for_braille("just one line")
        self.assertEqual(result.lines, ("just one line",))

    def test_original_text_preserved_verbatim(self):
        result = bt.normalize_text_for_braille("a\r\nb")
        self.assertEqual(result.original_text, "a\r\nb")


class FakeTranslatorBasicsTests(unittest.TestCase):
    def test_default_output_used_when_no_specific_mapping(self):
        fake = bt.FakeBrailleTranslator(default_output="⠁")
        self.assertEqual(fake.translate_line("anything"), "⠁")

    def test_line_specific_output_takes_precedence(self):
        fake = bt.FakeBrailleTranslator(line_outputs={"hi": "⠓⠊"}, default_output="⠁")
        self.assertEqual(fake.translate_line("hi"), "⠓⠊")
        self.assertEqual(fake.translate_line("other"), "⠁")

    def test_raises_when_no_output_configured_at_all(self):
        fake = bt.FakeBrailleTranslator()
        with self.assertRaises(bt.InternalTranslationError):
            fake.translate_line("unmapped")

    def test_configurable_raise_on_translate(self):
        fake = bt.FakeBrailleTranslator(raise_on_translate=bt.TranslationTimeoutError("timeout"))
        with self.assertRaises(bt.TranslationTimeoutError):
            fake.translate_line("x")


class OrchestrationSuccessTests(unittest.TestCase):
    def test_single_line_single_cell(self):
        fake = bt.FakeBrailleTranslator(default_output="⠿")
        result = bt.translate_text("x", fake)
        self.assertEqual(len(result.cells), 1)
        self.assertEqual(result.cells[0].bit_pattern, "111111")
        self.assertEqual(result.line_boundaries, ())

    def test_multi_cell_from_single_source_character(self):
        # ตัวอักษรต้นทางตัวเดียว แต่ translator คืนหลายเซลล์ (เช่น capital sign)
        fake = bt.FakeBrailleTranslator(line_outputs={"A": "⠠⠁"})
        result = bt.translate_text("A", fake)
        self.assertEqual(len(result.cells), 2)

    def test_multi_line_produces_correct_line_boundaries(self):
        fake = bt.FakeBrailleTranslator(line_outputs={"aa": "⠁⠁", "b": "⠃", "ccc": "⠉⠉⠉"})
        result = bt.translate_text("aa\nb\nccc", fake)
        self.assertEqual(len(result.cells), 6)
        # บรรทัดแรกจบที่เซลล์ index 2 (2 เซลล์), บรรทัดสองจบที่ 3 (1 เซลล์) รวม
        self.assertEqual(result.line_boundaries, (2, 3))

    def test_single_line_has_no_internal_boundaries(self):
        fake = bt.FakeBrailleTranslator(default_output="⠁")
        result = bt.translate_text("solo", fake)
        self.assertEqual(result.line_boundaries, ())

    def test_empty_line_within_multiline_text_produces_zero_cells_for_that_line(self):
        fake = bt.FakeBrailleTranslator(line_outputs={"a": "⠁", "b": "⠃"})
        result = bt.translate_text("a\n\nb", fake)
        self.assertEqual(len(result.cells), 2)
        # บรรทัดว่างตรงกลางไม่เพิ่มเซลล์ แต่ยังนับเป็นขอบเขตบรรทัด
        self.assertEqual(result.line_boundaries, (1, 1))

    def test_engine_table_version_are_propagated(self):
        fake = bt.FakeBrailleTranslator(default_output="⠁", engine="liblouis-python", version="3.29.0", table="th-g1.utb")
        result = bt.translate_text("x", fake)
        self.assertEqual(result.engine, "liblouis-python")
        self.assertEqual(result.engine_version, "3.29.0")
        self.assertEqual(result.table, "th-g1.utb")

    def test_cell_count_property(self):
        fake = bt.FakeBrailleTranslator(default_output="⠁⠂⠃")
        result = bt.translate_text("x", fake)
        self.assertEqual(result.cell_count, 3)

    def test_diagnostics_from_dots_78_do_not_fail_the_whole_request(self):
        char_with_dot7 = chr(0x2800 + 0b01000001)
        fake = bt.FakeBrailleTranslator(default_output=char_with_dot7)
        result = bt.translate_text("x", fake)
        self.assertEqual(len(result.cells), 1)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].code, "unsupported_dots_7_or_8")


class OrchestrationErrorTests(unittest.TestCase):
    def test_translator_unavailable(self):
        unavailable = bt.UnavailableBrailleTranslator(table="th-g1.utb", reason="ไม่พบ Liblouis")
        with self.assertRaises(bt.TranslatorUnavailableError):
            bt.translate_text("x", unavailable)

    def test_table_unavailable(self):
        fake = bt.FakeBrailleTranslator(table_valid=False)
        with self.assertRaises(bt.TableUnavailableError):
            bt.translate_text("x", fake)

    def test_table_check_none_is_treated_as_skip_not_failure(self):
        fake = bt.FakeBrailleTranslator(table_valid=None, default_output="⠁")
        result = bt.translate_text("x", fake)  # ไม่ควร raise
        self.assertEqual(result.cell_count, 1)

    def test_translation_timeout_propagates(self):
        fake = bt.FakeBrailleTranslator(raise_on_translate=bt.TranslationTimeoutError("timeout"))
        with self.assertRaises(bt.TranslationTimeoutError):
            bt.translate_text("x", fake)

    def test_internal_translation_error_propagates(self):
        fake = bt.FakeBrailleTranslator(raise_on_translate=bt.InternalTranslationError("boom"))
        with self.assertRaises(bt.InternalTranslationError):
            bt.translate_text("x", fake)

    def test_fully_invalid_output_for_nonblank_line_raises(self):
        fake = bt.FakeBrailleTranslator(default_output="XYZ")  # ไม่มีตัวอักษรใดเป็น braille เลย
        with self.assertRaises(bt.InvalidTranslatorOutputError):
            bt.translate_text("hello", fake)

    def test_partially_invalid_output_yields_warning_not_failure(self):
        fake = bt.FakeBrailleTranslator(default_output="⠁X⠂")
        result = bt.translate_text("hi", fake)
        self.assertEqual(len(result.cells), 2)
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].code, "non_braille_output")

    def test_empty_text_raises_before_touching_translator(self):
        fake = bt.FakeBrailleTranslator()  # ไม่มี output กำหนดไว้ - จะ raise ถ้าถูกเรียก
        with self.assertRaises(bt.EmptyTextError):
            bt.translate_text("   ", fake)

    def test_too_long_text_raises_before_touching_translator(self):
        fake = bt.FakeBrailleTranslator()
        with self.assertRaises(bt.TextTooLongError):
            bt.translate_text("a" * 10, fake, max_length=5)

    def test_invalid_type_raises_before_touching_translator(self):
        fake = bt.FakeBrailleTranslator()
        with self.assertRaises(bt.InvalidInputTypeError):
            bt.translate_text(None, fake)


class ResponseSerializationTests(unittest.TestCase):
    def test_translation_response_dict_shape(self):
        fake = bt.FakeBrailleTranslator(default_output="⠿", engine="fake", version="1.0", table="t.utb")
        translation = bt.translate_text("x", fake)
        payload = bt.translation_response_dict(translation)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["sent_to_hardware"])
        self.assertEqual(payload["cell_count"], 1)
        self.assertEqual(payload["engine"], "fake")
        self.assertEqual(payload["table"], "t.utb")
        expected_keys = {
            "ok", "source_text", "normalized_text", "cells", "line_boundaries",
            "cell_count", "diagnostics", "engine", "engine_version", "table",
            "changed_by_normalization", "sent_to_hardware",
        }
        self.assertEqual(set(payload.keys()), expected_keys)

    def test_sent_to_hardware_always_false_by_default(self):
        fake = bt.FakeBrailleTranslator(default_output="⠁")
        translation = bt.translate_text("x", fake)
        payload = bt.translation_response_dict(translation)
        self.assertIs(payload["sent_to_hardware"], False)


class NoSerialOrHardwareCouplingTests(unittest.TestCase):
    """braille_translation.py ต้องไม่มีโค้ดที่ยุ่งกับ Serial/ESP32/Flask/EasyOCR
    เลย ตรวจจาก AST import statements จริง ไม่ใช่การห้ามคำแบบเหมารวม (docstring
    ของโมดูลนี้อ้างถึง Serial/ESP32/Liblouis ตรง ๆ เพื่ออธิบายสถาปัตยกรรม ซึ่ง
    เป็นคำอธิบายที่ดี ไม่ใช่การเชื่อมต่อจริง)
    """

    def test_module_has_no_hardware_or_web_framework_imports(self):
        source = pathlib.Path(bt.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module.split(".")[0])

        self.assertNotIn("serial", imported_modules)
        self.assertNotIn("flask", imported_modules)
        self.assertNotIn("easyocr", imported_modules)
        self.assertNotIn("app", imported_modules)
        self.assertNotIn("subprocess", imported_modules)  # subprocess อยู่ใน liblouis_translator.py เท่านั้น
        self.assertNotIn("ser_conn", source)
        self.assertNotIn("app.route", source)

    def test_does_not_import_liblouis_translator_or_legacy_dictionary(self):
        # orchestration ต้องไม่ผูกติดกับ implementation ใด ๆ โดยตรง (dependency
        # injection เท่านั้น) - ป้องกัน accidental coupling / fallback ที่ซ่อนอยู่
        source = pathlib.Path(bt.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        self.assertNotIn("liblouis_translator", imported_modules)
        self.assertNotIn("legacy_braille_dictionary", imported_modules)


if __name__ == "__main__":
    unittest.main()
