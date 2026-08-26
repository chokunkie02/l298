"""ทดสอบ legacy_braille_dictionary.py: พจนานุกรม hardcode เดิม (ยังไม่ตรวจสอบ),
LegacyDictionaryTranslator (ต้องเปิดใช้งานด้วยมือเท่านั้น), และการเปรียบเทียบ
กับพจนานุกรมฝั่ง frontend (static/script.js) เพื่อบันทึกความแตกต่างที่ยืนยันแล้ว

**หมายเหตุสำคัญ**: เทสต์นี้ไม่ได้ยืนยันว่าค่าใดในพจนานุกรม "ถูกต้อง" ตาม
มาตรฐานอักษรเบรลล์ไทย เพียงบันทึกโครงสร้าง/ความสอดคล้องภายในระหว่างสอง
พจนานุกรมที่มีอยู่ในโค้ดเดิมเท่านั้น (ดู legacy_braille_dictionary.py สำหรับ
คำเตือนแบบเต็ม)
"""

import ast
import pathlib
import re
import unittest

import legacy_braille_dictionary as legacy
from braille_models import bitmask_from_bit_pattern


def _extract_frontend_dict() -> dict[str, str]:
    """Parse ค่า BRAILLE_DICT จาก static/script.js ด้วย regex ธรรมดา (ไม่ใช้
    JS parser เต็มรูปแบบ) เพียงพอสำหรับรูปแบบ object literal แบบง่ายที่ใช้อยู่
    """
    script_path = pathlib.Path(__file__).resolve().parent.parent / "static" / "script.js"
    source = script_path.read_text(encoding="utf-8")

    match = re.search(r"const BRAILLE_DICT = \{(.*?)\n\s*\};", source, re.S)
    if not match:
        raise AssertionError("ไม่พบ BRAILLE_DICT ใน static/script.js - รูปแบบไฟล์อาจเปลี่ยนไป")

    body = match.group(1)
    entries = re.findall(r"'([^']+)':\s*'([01]{6})'", body)
    return dict(entries)


class LegacyDictionaryContentTests(unittest.TestCase):
    """บันทึกเนื้อหาปัจจุบันของพจนานุกรม backend อย่างชัดเจน (ไม่ใช่การยืนยัน
    ความถูกต้อง) เพื่อให้การเปลี่ยนแปลงในอนาคตต้องแก้เทสต์นี้อย่างตั้งใจ
    """

    def test_covers_all_44_thai_consonants(self):
        thai_consonants = [c for c in legacy.THAI_BRAILLE_MAP if "ก" <= c <= "ฮ"]
        self.assertEqual(len(thai_consonants), 44)

    def test_covers_english_a_to_z(self):
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            self.assertIn(letter, legacy.THAI_BRAILLE_MAP)

    def test_covers_digits_0_to_9(self):
        for digit in "0123456789":
            self.assertIn(digit, legacy.THAI_BRAILLE_MAP)

    def test_does_not_cover_thai_vowels_or_tone_marks(self):
        # บันทึกข้อจำกัดที่ทราบแล้ว: ไม่มีสระ/วรรณยุกต์ไทยเลยในพจนานุกรมนี้
        thai_vowels_and_tones = "ะัาำิีึืุูเแโใไ่้๊๋์ๆฯ"
        for char in thai_vowels_and_tones:
            self.assertNotIn(char, legacy.THAI_BRAILLE_MAP)

    def test_all_values_are_six_character_binary_strings(self):
        for char, pattern in legacy.THAI_BRAILLE_MAP.items():
            with self.subTest(char=char):
                self.assertEqual(len(pattern), 6)
                self.assertTrue(set(pattern).issubset({"0", "1"}))
                bitmask_from_bit_pattern(pattern)  # ต้องไม่ raise

    def test_total_entry_count(self):
        # 44 พยัญชนะไทย + 26 อังกฤษ + 10 ตัวเลข = 80 (ฃ และ ฅ ใช้ pattern ซ้ำกับ
        # ข/ค แต่ยังนับเป็น key แยกกัน)
        self.assertEqual(len(legacy.THAI_BRAILLE_MAP), 80)


class LegacyVsFrontendDictionaryComparisonTests(unittest.TestCase):
    """เปรียบเทียบพจนานุกรม backend (legacy_braille_dictionary.py) กับ frontend
    (static/script.js BRAILLE_DICT) - บันทึกความแตกต่างที่ยืนยันแล้วทั้งหมด
    """

    @classmethod
    def setUpClass(cls):
        cls.frontend_dict = _extract_frontend_dict()

    def test_frontend_dict_is_nonempty_and_was_parsed_correctly(self):
        self.assertGreater(len(self.frontend_dict), 0)
        self.assertIn("ก", self.frontend_dict)
        self.assertIn("A", self.frontend_dict)

    def test_every_key_shared_by_both_dictionaries_has_the_same_value(self):
        # ผลตรวจสอบที่ยืนยันแล้ว: ค่าที่ overlap กันทั้งหมดตรงกันทุกตัว (ไม่มี
        # ความขัดแย้งของค่า) - ถ้าเทสต์นี้ล้มเหลวในอนาคต แปลว่ามีคนแก้ไขค่าใดค่า
        # หนึ่งโดยไม่แก้อีกฝั่ง ต้องตรวจสอบทันที
        shared_keys = set(self.frontend_dict) & set(legacy.THAI_BRAILLE_MAP)
        self.assertGreater(len(shared_keys), 0, "ควรมีตัวอักษรที่ทั้งสองฝั่งมีร่วมกัน")
        mismatches = {
            key: (self.frontend_dict[key], legacy.THAI_BRAILLE_MAP[key])
            for key in shared_keys
            if self.frontend_dict[key] != legacy.THAI_BRAILLE_MAP[key]
        }
        self.assertEqual(mismatches, {}, f"พบค่าขัดแย้งกันระหว่าง frontend/backend: {mismatches}")

    def test_frontend_is_a_strict_subset_of_backend_coverage(self):
        # ผลตรวจสอบที่ยืนยันแล้ว: frontend ไม่มีตัวอักษรใดที่ backend ไม่มี
        extra_in_frontend = set(self.frontend_dict) - set(legacy.THAI_BRAILLE_MAP)
        self.assertEqual(extra_in_frontend, set())

    def test_backend_has_more_thai_consonants_than_frontend(self):
        # ผลตรวจสอบที่ยืนยันแล้ว (นับจริงจากไฟล์ทั้งสอง): backend มีพยัญชนะไทย
        # ครบ 44 ตัว frontend มีแค่ 30 ตัว (ขาด ฃ ฅ ฆ ฎ ฏ ฐ ฑ ฒ ณ ธ ศ ษ ฬ ฮ
        # เทียบกับ backend - 14 ตัวที่ขาดไป)
        frontend_consonants = {c for c in self.frontend_dict if "ก" <= c <= "ฮ"}
        backend_consonants = {c for c in legacy.THAI_BRAILLE_MAP if "ก" <= c <= "ฮ"}
        self.assertEqual(len(frontend_consonants), 30)
        self.assertEqual(len(backend_consonants), 44)
        self.assertEqual(backend_consonants - frontend_consonants, set("ฃฅฆฎฏฐฑฒณธศษฬฮ"))
        self.assertTrue(frontend_consonants.issubset(backend_consonants))

    def test_backend_has_full_english_alphabet_frontend_only_has_a_through_j(self):
        frontend_english = {c for c in self.frontend_dict if c.isalpha() and c.isascii()}
        backend_english = {c for c in legacy.THAI_BRAILLE_MAP if c.isalpha() and c.isascii()}
        self.assertEqual(frontend_english, set("ABCDEFGHIJ"))
        self.assertEqual(backend_english, set("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))

    def test_backend_has_digits_0_and_6_to_9_that_frontend_lacks(self):
        frontend_digits = {c for c in self.frontend_dict if c.isdigit()}
        backend_digits = {c for c in legacy.THAI_BRAILLE_MAP if c.isdigit()}
        self.assertEqual(frontend_digits, set("12345"))
        self.assertEqual(backend_digits, set("0123456789"))


class LegacyDictionaryTranslatorTests(unittest.TestCase):
    def test_disabled_by_default(self):
        translator = legacy.LegacyDictionaryTranslator()
        self.assertFalse(translator.is_available())

    def test_translate_line_raises_when_not_explicitly_enabled(self):
        translator = legacy.LegacyDictionaryTranslator()
        with self.assertRaises(legacy.LegacyDictionaryDisabledError):
            translator.translate_line("ก")

    def test_translate_line_works_when_explicitly_enabled(self):
        translator = legacy.LegacyDictionaryTranslator(enabled=True)
        result = translator.translate_line("A")
        self.assertEqual(len(result), 1)
        self.assertEqual(ord(result[0]) - 0x2800, bitmask_from_bit_pattern("100000"))

    def test_unmapped_characters_are_skipped_not_erroring(self):
        translator = legacy.LegacyDictionaryTranslator(enabled=True)
        # 'ก' มีในพจนานุกรม แต่สระ/วรรณยุกต์ไม่มี - ตัวที่ไม่มีถูกข้าม ไม่ raise
        result = translator.translate_line("กะ")
        self.assertEqual(len(result), 1)  # เฉพาะ 'ก' เท่านั้นที่แปลได้

    def test_engine_name_marks_result_as_unverified(self):
        translator = legacy.LegacyDictionaryTranslator(enabled=True)
        self.assertIn("UNVERIFIED", translator.engine_name())

    def test_check_table_returns_none_meaning_skip_not_valid(self):
        translator = legacy.LegacyDictionaryTranslator(enabled=True)
        self.assertIsNone(translator.check_table())


class NoAutomaticProductionUsageTests(unittest.TestCase):
    """ยืนยันว่า braille_translation.py และ liblouis_translator.py (เส้นทาง
    production) ไม่ import legacy_braille_dictionary เลย - ป้องกัน fallback
    แบบเงียบ ๆ ที่โจทย์ห้ามไว้อย่างเด็ดขาด
    """

    def _imports(self, module) -> set[str]:
        source = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    def test_braille_translation_does_not_import_legacy_dictionary(self):
        import braille_translation

        self.assertNotIn("legacy_braille_dictionary", self._imports(braille_translation))

    def test_liblouis_translator_does_not_import_legacy_dictionary(self):
        import liblouis_translator

        self.assertNotIn("legacy_braille_dictionary", self._imports(liblouis_translator))

    def test_app_creates_default_translator_via_liblouis_factory_not_legacy(self):
        import app as app_module

        # translator ที่ app.py สร้างต้องไม่ใช่ LegacyDictionaryTranslator
        self.assertNotIsInstance(app_module.braille_translator, legacy.LegacyDictionaryTranslator)


if __name__ == "__main__":
    unittest.main()
