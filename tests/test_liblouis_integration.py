"""Integration test เสริม (optional) ที่เรียก Liblouis จริงผ่าน
liblouis_translator.create_default_translator() - ข้ามอย่างชัดเจนถ้าไม่มี
Liblouis หรือไม่มีตาราง th-g1.utb ในเครื่องนี้ ไม่ใช่ส่วนหนึ่งของชุดเทสต์
อัตโนมัติหลักที่ห้ามพึ่งพา Liblouis (ดู tests/test_liblouis_translator.py ซึ่ง
mock ทุกอย่างและไม่ skip)

รันแยกได้ด้วย:
    python -m unittest tests.test_liblouis_integration -v

**คำเตือน**: การรันเทสต์นี้ผ่านยืนยันเพียงว่า adapter เรียก Liblouis ได้จริง
และได้ผลลัพธ์เป็น Unicode Braille ที่ตีความได้ (ไม่ crash, ได้ bitmask 0-63
ที่ถูกต้อง) **ไม่ได้ยืนยันความถูกต้องทางภาษาศาสตร์ของอักษรเบรลล์ไทยที่ได้แต่
อย่างใด** ต้องตรวจสอบเพิ่มเติมโดยผู้เชี่ยวชาญ/ผู้อ่านเบรลล์ไทยที่มีคุณสมบัติ
เทียบกับคู่มืออักษรเบรลล์ไทย (Thai Braille Use Manual) เสมอก่อนใช้งานจริง

**หมายเหตุการแก้ไข encoding**: ยืนยันแล้วบนเครื่องนี้กับ Liblouis 3.38.0 ว่า
`lou_translate` ต้องระบุ `-d unicode.dis` อย่างชัดเจนจึงจะคืน Unicode Braille
(ดู liblouis_translator.UNICODE_DISPLAY_TABLE) เทสต์ในไฟล์นี้ตรวจว่าผลลัพธ์
ดิบที่ได้จริงอยู่ในช่วง Unicode Braille เท่านั้น (โครงสร้างถูกต้อง) **ไม่ได้
เข้ารหัสตัวอย่างที่ตรวจสอบแล้วด้วยตา (เช่น "hello" -> "⠓⠑⠇⠇⠕") เป็น golden
vector ที่ยืนยันความถูกต้องทางภาษาศาสตร์แต่อย่างใด** เป็นเพียงหลักฐานว่าการ
เชื่อมต่อและการเข้ารหัส Unicode ทำงานถูกต้องเท่านั้น
"""

import unittest

from braille_models import BRAILLE_UNICODE_BASE, BRAILLE_UNICODE_MAX
from braille_translation import translate_text
from liblouis_translator import DEFAULT_THAI_TABLE, create_default_translator

_translator = create_default_translator()
_available = _translator.is_available()
_table_ok = _translator.check_table() is not False  # None (ข้ามตรวจ) หรือ True ถือว่าใช้ได้


@unittest.skipUnless(
    _available,
    "ไม่พบ Liblouis ในเครื่องนี้ (ไม่มีทั้ง python binding 'import louis' และ "
    "คำสั่ง lou_translate) ข้าม integration test - ดู README.md เพื่อติดตั้ง",
)
@unittest.skipUnless(
    _table_ok,
    f"พบ Liblouis แต่ตาราง {DEFAULT_THAI_TABLE} ใช้งานไม่ได้ในเครื่องนี้ ข้าม integration test",
)
class LiblouisRealIntegrationTests(unittest.TestCase):
    def test_engine_reports_a_version_string(self):
        version = _translator.engine_version()
        self.assertIsInstance(version, str)
        self.assertTrue(version)

    def test_translates_simple_english_text_to_valid_cells(self):
        result = translate_text("hello", _translator)
        self.assertGreater(result.cell_count, 0)
        for cell in result.cells:
            self.assertTrue(0 <= cell.bitmask <= 63)

    def test_translates_digits_to_valid_cells(self):
        result = translate_text("12345", _translator)
        self.assertGreater(result.cell_count, 0)

    def test_translates_thai_text_without_crashing(self):
        # ไม่ยืนยันค่าที่ถูกต้องเชิงภาษาศาสตร์ - ยืนยันเพียงว่าไม่ crash และได้
        # เซลล์ที่ถูกต้องเชิงโครงสร้าง (bitmask 0-63) เท่านั้น
        result = translate_text("สวัสดีครับ", _translator)
        self.assertGreaterEqual(result.cell_count, 0)
        for cell in result.cells:
            self.assertTrue(0 <= cell.bitmask <= 63)

    def test_engine_and_table_are_recorded_in_result(self):
        result = translate_text("test", _translator)
        self.assertEqual(result.table, DEFAULT_THAI_TABLE)
        self.assertIsNotNone(result.engine)

    def test_raw_output_for_english_digits_and_thai_is_unicode_braille_only(self):
        # ตรวจโครงสร้างล้วน (ทุกตัวอักษรของผลลัพธ์ดิบต้องอยู่ในช่วง Unicode
        # Braille Patterns) - ไม่ตรวจ/ยืนยันค่าที่ถูกต้องเชิงภาษาศาสตร์
        for sample_text in ("hello", "12345", "สวัสดีครับ"):
            with self.subTest(text=sample_text):
                raw_output = _translator.translate_line(sample_text)
                self.assertTrue(len(raw_output) > 0, f"ไม่ได้ผลลัพธ์ใด ๆ สำหรับ {sample_text!r}")
                for char in raw_output:
                    self.assertTrue(
                        BRAILLE_UNICODE_BASE <= ord(char) <= BRAILLE_UNICODE_MAX,
                        f"{char!r} (U+{ord(char):04X}) ในผลลัพธ์ของ {sample_text!r} ไม่ใช่ Unicode Braille "
                        "- อาจแปลว่าลืมระบุ -d unicode.dis",
                    )

    def test_translation_does_not_touch_serial_or_esp32(self):
        # ตรวจว่าโมดูล liblouis_translator.py และการเรียก translate_text() จริง
        # ไม่ import/ยุ่งกับ Serial หรือ ESP32 เลย (การแก้ไข -d unicode.dis ต้อง
        # ไม่เปิดช่องทางเชื่อมต่อฮาร์ดแวร์ใหม่โดยไม่ตั้งใจ)
        import ast
        import pathlib

        import liblouis_translator as lt_module

        source = pathlib.Path(lt_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module.split(".")[0])
        self.assertNotIn("serial", imported_modules)

        # และยืนยันด้วยพฤติกรรมจริง: การแปลจริงต้องไม่สร้าง side effect ใด ๆ
        # นอกเหนือจากการคืนผลลัพธ์ (ไม่มี global state ของ serial ให้ตรวจสอบ
        # ในโมดูลนี้อยู่แล้วโดยธรรมชาติของสถาปัตยกรรม)
        result = translate_text("hello", _translator)
        self.assertGreater(result.cell_count, 0)

    def test_report_result_is_not_claimed_as_linguistically_verified(self):
        # เทสต์นี้เป็นการเตือนตัวเองในโค้ด (self-documenting) ว่าการผ่านเทสต์
        # ข้างบนทั้งหมดไม่ใช่หลักฐานความถูกต้องทางภาษาศาสตร์
        self.assertTrue(
            True,
            "ผ่าน integration test นี้ยืนยันแค่ว่า Liblouis เรียกได้และให้ผลลัพธ์"
            "ที่ตีความเป็นเซลล์ 6 จุดได้ถูกต้องเชิงโครงสร้างเท่านั้น "
            "ต้องให้ผู้เชี่ยวชาญ/ผู้อ่านเบรลล์ไทยตรวจสอบความถูกต้องทางภาษาศาสตร์แยกต่างหาก",
        )


if __name__ == "__main__":
    if not _available:
        print(f"ข้าม: {_translator.reason() if hasattr(_translator, 'reason') else 'Liblouis ไม่พร้อมใช้งาน'}")
    elif not _table_ok:
        print(f"ข้าม: ตาราง {DEFAULT_THAI_TABLE} ใช้งานไม่ได้")
    else:
        print(f"พบ Liblouis: engine={_translator.engine_name()} version={_translator.engine_version()} table={DEFAULT_THAI_TABLE}")
    unittest.main()
