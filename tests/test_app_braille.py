"""ทดสอบ POST /api/braille/translate ใน app.py: การ serialize response, error
ทุกหมวดหมู่ (missing/invalid/empty/too-long/unavailable/table/timeout/invalid
output/internal), และยืนยันว่าเส้นทางนี้ไม่ยุ่งกับ Serial/ESP32/legacy dictionary
เลยไม่ว่ากรณีใด ใช้ FakeBrailleTranslator ผ่าน dependency injection (patch
app.braille_translator) ไม่ต้องติดตั้ง Liblouis จริง
"""

import ast
import pathlib
import unittest
from unittest.mock import patch

import app as app_module
from braille_translation import (
    FakeBrailleTranslator,
    InternalTranslationError,
    TranslationTimeoutError,
    UnavailableBrailleTranslator,
)


class BrailleTranslateApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def _patch_translator(self, translator):
        return patch.object(app_module, "braille_translator", translator)

    def test_missing_text_field_returns_structured_400(self):
        response = self.client.post("/api/braille/translate", json={})
        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_text")

    def test_non_json_body_returns_structured_400(self):
        response = self.client.post("/api/braille/translate", data="not json", content_type="text/plain")
        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["code"], "invalid_request_body")

    def test_invalid_text_type_returns_structured_400(self):
        response = self.client.post("/api/braille/translate", json={"text": 123})
        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["code"], "invalid_text_type")

    def test_empty_text_returns_structured_400(self):
        response = self.client.post("/api/braille/translate", json={"text": "   "})
        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["code"], "empty_text")

    def test_text_too_long_returns_structured_413(self):
        fake = FakeBrailleTranslator(default_output="⠁")
        with self._patch_translator(fake):
            response = self.client.post("/api/braille/translate", json={"text": "a" * 6000})
        payload = response.get_json()
        self.assertEqual(response.status_code, 413)
        self.assertEqual(payload["error"]["code"], "text_too_long")

    def test_translator_unavailable_returns_structured_503(self):
        unavailable = UnavailableBrailleTranslator(table="th-g1.utb", reason="ไม่พบ Liblouis")
        with self._patch_translator(unavailable):
            response = self.client.post("/api/braille/translate", json={"text": "hello"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["error"]["code"], "translator_unavailable")

    def test_table_missing_returns_structured_503(self):
        fake = FakeBrailleTranslator(table_valid=False)
        with self._patch_translator(fake):
            response = self.client.post("/api/braille/translate", json={"text": "hello"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["error"]["code"], "table_unavailable")

    def test_translation_timeout_returns_structured_504(self):
        fake = FakeBrailleTranslator(raise_on_translate=TranslationTimeoutError("timed out"))
        with self._patch_translator(fake):
            response = self.client.post("/api/braille/translate", json={"text": "hello"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 504)
        self.assertEqual(payload["error"]["code"], "translation_timeout")

    def test_invalid_translator_output_returns_structured_502(self):
        fake = FakeBrailleTranslator(default_output="XYZ")  # ไม่ใช่ braille เลย
        with self._patch_translator(fake):
            response = self.client.post("/api/braille/translate", json={"text": "hello"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(payload["error"]["code"], "invalid_translator_output")

    def test_internal_translation_error_returns_structured_500(self):
        fake = FakeBrailleTranslator(raise_on_translate=InternalTranslationError("boom"))
        with self._patch_translator(fake):
            response = self.client.post("/api/braille/translate", json={"text": "hello"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(payload["error"]["code"], "translation_failed")

    def test_error_messages_never_contain_traceback_or_python_internals(self):
        fake = FakeBrailleTranslator(raise_on_translate=InternalTranslationError("boom"))
        with self._patch_translator(fake):
            response = self.client.post("/api/braille/translate", json={"text": "hello"})
        body_text = response.get_data(as_text=True)
        self.assertNotIn("Traceback", body_text)
        self.assertNotIn("File \"", body_text)

    def test_successful_translation_response_shape(self):
        fake = FakeBrailleTranslator(
            default_output="⠿", engine="liblouis-python", version="3.29.0", table="th-g1.utb"
        )
        with self._patch_translator(fake):
            response = self.client.post("/api/braille/translate", json={"text": "x"})
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["cell_count"], 1)
        self.assertEqual(payload["cells"][0]["bit_pattern"], "111111")
        self.assertEqual(payload["cells"][0]["unicode_braille"], "⠿")
        self.assertEqual(payload["cells"][0]["dot_numbers"], [1, 2, 3, 4, 5, 6])
        self.assertEqual(payload["engine"], "liblouis-python")
        self.assertEqual(payload["engine_version"], "3.29.0")
        self.assertEqual(payload["table"], "th-g1.utb")
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["line_boundaries"], [])
        self.assertIs(payload["sent_to_hardware"], False)

        expected_keys = {
            "ok", "source_text", "normalized_text", "cells", "line_boundaries",
            "cell_count", "diagnostics", "engine", "engine_version", "table",
            "changed_by_normalization", "sent_to_hardware",
        }
        self.assertEqual(set(payload.keys()), expected_keys)

    def test_sent_to_hardware_is_always_false(self):
        fake = FakeBrailleTranslator(default_output="⠁")
        with self._patch_translator(fake):
            response = self.client.post("/api/braille/translate", json={"text": "x"})
        self.assertIs(response.get_json()["sent_to_hardware"], False)

    def test_multiline_text_produces_line_boundaries(self):
        fake = FakeBrailleTranslator(line_outputs={"a": "⠁", "bb": "⠃⠃"})
        with self._patch_translator(fake):
            response = self.client.post("/api/braille/translate", json={"text": "a\nbb"})
        payload = response.get_json()
        self.assertEqual(payload["cell_count"], 3)
        self.assertEqual(payload["line_boundaries"], [1])

    def test_when_neither_liblouis_binding_nor_cli_present_returns_translator_unavailable(self):
        # เดิมเทสต์นี้ยิงคำขอจริงโดยพึ่งพาว่าเครื่องที่รันเทสต์ไม่มี Liblouis
        # ติดตั้งอยู่ - เมื่อติดตั้ง Liblouis 3.38.0 ลงเครื่องแล้ว เทสต์แบบนั้น
        # จะ fail เพราะ translator กลายเป็นพร้อมใช้งานจริง (200 แทน 503) จึง
        # เปลี่ยนมา mock สภาพแวดล้อมให้ "ไม่มี Liblouis" แบบ deterministic แทน -
        # ไม่พึ่งพาว่าเครื่องที่รันเทสต์ติดตั้ง Liblouis จริงหรือไม่ ทดสอบทั้ง
        # เส้นทางเลือก adapter (create_default_translator) และเส้นทาง API จริง
        import liblouis_translator as lt_module

        with patch.object(lt_module, "_python_binding_module_available", return_value=False), \
             patch.object(lt_module, "_cli_tool_path", return_value=None):
            unavailable_translator = lt_module.create_default_translator()

        self.assertFalse(unavailable_translator.is_available())

        with self._patch_translator(unavailable_translator):
            response = self.client.post("/api/braille/translate", json={"text": "hello"})

        payload = response.get_json()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(payload["error"]["code"], "translator_unavailable")

    def test_when_only_python_binding_missing_falls_back_to_cli_not_unavailable(self):
        # ตรวจ logic การเลือก adapter อีกด้าน: ถ้ามี CLI แต่ไม่มี python binding
        # ต้องไม่กลายเป็น unavailable (ต้องเลือก CLI adapter แทน)
        import liblouis_translator as lt_module

        with patch.object(lt_module, "_python_binding_module_available", return_value=False), \
             patch.object(lt_module, "_cli_tool_path", return_value="/usr/bin/lou_translate"):
            translator = lt_module.create_default_translator()

        self.assertIsInstance(translator, lt_module.LiblouisSubprocessAdapter)
        self.assertNotIsInstance(translator, UnavailableBrailleTranslator)


class BrailleRouteNoHardwareCouplingTests(unittest.TestCase):
    """เส้นทาง /api/braille/translate ต้องไม่เรียก Serial/ESP32 หรือ legacy
    dictionary เองไม่ว่ากรณีใด - ตรวจทั้งจากพฤติกรรมจริง (mock ser_conn) และจาก
    การอ่านซอร์สโค้ดของฟังก์ชัน route โดยตรง
    """

    def setUp(self):
        self.client = app_module.app.test_client()

    def test_translation_never_touches_ser_conn(self):
        fake = FakeBrailleTranslator(default_output="⠁")
        original_ser_conn = app_module.ser_conn
        with patch.object(app_module, "braille_translator", fake), \
             patch.object(app_module, "init_serial") as mock_init_serial:
            response = self.client.post("/api/braille/translate", json={"text": "hello"})
        self.assertEqual(response.status_code, 200)
        mock_init_serial.assert_not_called()
        self.assertEqual(app_module.ser_conn, original_ser_conn)

    def test_translate_braille_function_source_has_no_serial_calls(self):
        import inspect

        source = inspect.getsource(app_module.translate_braille)
        self.assertNotIn("ser_conn", source)
        self.assertNotIn("init_serial", source)
        self.assertNotIn("THAI_BRAILLE_MAP", source)
        self.assertNotIn("LegacyDictionaryTranslator", source)

    def test_app_module_imports_liblouis_factory_not_legacy_translator_class(self):
        source = pathlib.Path(app_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported_names.update(alias.name for alias in node.names)
        self.assertIn("create_default_translator", imported_names)
        self.assertNotIn("LegacyDictionaryTranslator", imported_names)


if __name__ == "__main__":
    unittest.main()
