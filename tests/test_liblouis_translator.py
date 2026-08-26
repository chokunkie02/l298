"""ทดสอบ liblouis_translator.py ด้วย mock ทั้งหมด - ไม่ต้องติดตั้ง Liblouis จริง

ครอบคลุม: การเลือก adapter (python binding มาก่อน CLI มาก่อน unavailable),
LiblouisPythonAdapter (mock `louis` module ปลอมใน sys.modules), และ
LiblouisSubprocessAdapter (mock subprocess.run + shutil.which) รวมถึงความ
ปลอดภัยของ subprocess (argument list, shell=False, timeout)
"""

import subprocess
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

import liblouis_translator as lt
from braille_translation import (
    InternalTranslationError,
    TranslationTimeoutError,
    UnavailableBrailleTranslator,
)


def _install_fake_louis_module(**overrides):
    """สร้าง fake module ชื่อ 'louis' แล้วใส่ใน sys.modules ชั่วคราว (ใช้เป็น
    context manager ผ่าน patch.dict) จำลอง Liblouis python binding
    """
    fake = types.ModuleType("louis")
    fake.translateString = overrides.get("translateString", MagicMock(return_value="⠁⠃"))
    fake.version = overrides.get("version", MagicMock(return_value="3.29.0"))
    if "checkTable" in overrides:
        fake.checkTable = overrides["checkTable"]
    return fake


class AdapterSelectionTests(unittest.TestCase):
    def test_prefers_python_binding_when_available(self):
        with patch.object(lt, "_python_binding_module_available", return_value=True), \
             patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"):
            translator = lt.create_default_translator()
        self.assertIsInstance(translator, lt.LiblouisPythonAdapter)

    def test_falls_back_to_cli_when_only_cli_available(self):
        with patch.object(lt, "_python_binding_module_available", return_value=False), \
             patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"):
            translator = lt.create_default_translator()
        self.assertIsInstance(translator, lt.LiblouisSubprocessAdapter)

    def test_returns_unavailable_when_neither_present(self):
        with patch.object(lt, "_python_binding_module_available", return_value=False), \
             patch.object(lt, "_cli_tool_path", return_value=None):
            translator = lt.create_default_translator()
        self.assertIsInstance(translator, UnavailableBrailleTranslator)
        self.assertFalse(translator.is_available())

    def test_default_table_is_th_g1(self):
        self.assertEqual(lt.DEFAULT_THAI_TABLE, "th-g1.utb")


class LiblouisPythonAdapterTests(unittest.TestCase):
    def test_is_available_reflects_module_presence(self):
        adapter = lt.LiblouisPythonAdapter()
        with patch.object(lt, "_python_binding_module_available", return_value=True):
            self.assertTrue(adapter.is_available())
        with patch.object(lt, "_python_binding_module_available", return_value=False):
            self.assertFalse(adapter.is_available())

    def test_translate_line_calls_translateString_with_table_and_text(self):
        fake_module = _install_fake_louis_module(
            translateString=MagicMock(return_value="⠁⠃")
        )
        adapter = lt.LiblouisPythonAdapter(table="th-g1.utb")
        with patch.dict(sys.modules, {"louis": fake_module}):
            result = adapter.translate_line("hi")
        self.assertEqual(result, "⠁⠃")
        fake_module.translateString.assert_called_once_with(["th-g1.utb"], "hi")

    def test_translate_line_wraps_unexpected_exceptions(self):
        def boom(*args, **kwargs):
            raise RuntimeError("liblouis internal panic with sensitive path /etc/secret")

        fake_module = _install_fake_louis_module(translateString=boom)
        adapter = lt.LiblouisPythonAdapter()
        with patch.dict(sys.modules, {"louis": fake_module}):
            with self.assertRaises(InternalTranslationError) as ctx:
                adapter.translate_line("hi")
        # ข้อความ error ที่ผู้ใช้เห็นต้องไม่มี stack trace หรือรายละเอียดภายในหลุดออกมา
        self.assertNotIn("/etc/secret", str(ctx.exception))
        self.assertNotIn("RuntimeError", str(ctx.exception))

    def test_engine_version_reads_louis_version(self):
        fake_module = _install_fake_louis_module(version=MagicMock(return_value="3.29.0"))
        adapter = lt.LiblouisPythonAdapter()
        with patch.dict(sys.modules, {"louis": fake_module}), \
             patch.object(lt, "_python_binding_module_available", return_value=True):
            self.assertEqual(adapter.engine_version(), "3.29.0")

    def test_engine_version_none_when_unavailable(self):
        adapter = lt.LiblouisPythonAdapter()
        with patch.object(lt, "_python_binding_module_available", return_value=False):
            self.assertIsNone(adapter.engine_version())

    def test_check_table_uses_checkTable_when_present(self):
        fake_module = _install_fake_louis_module(checkTable=MagicMock(return_value=True))
        adapter = lt.LiblouisPythonAdapter(table="th-g1.utb")
        with patch.dict(sys.modules, {"louis": fake_module}), \
             patch.object(lt, "_python_binding_module_available", return_value=True):
            self.assertTrue(adapter.check_table())
        fake_module.checkTable.assert_called_once_with(["th-g1.utb"])

    def test_check_table_false_when_checkTable_says_invalid(self):
        fake_module = _install_fake_louis_module(checkTable=MagicMock(return_value=False))
        adapter = lt.LiblouisPythonAdapter()
        with patch.dict(sys.modules, {"louis": fake_module}), \
             patch.object(lt, "_python_binding_module_available", return_value=True):
            self.assertFalse(adapter.check_table())

    def test_check_table_falls_back_to_probe_translate_when_no_checkTable(self):
        fake_module = _install_fake_louis_module(translateString=MagicMock(return_value=" "))
        self.assertFalse(hasattr(fake_module, "checkTable"))
        adapter = lt.LiblouisPythonAdapter()
        with patch.dict(sys.modules, {"louis": fake_module}), \
             patch.object(lt, "_python_binding_module_available", return_value=True):
            self.assertTrue(adapter.check_table())

    def test_check_table_probe_fallback_returns_false_on_exception(self):
        def boom(*args, **kwargs):
            raise RuntimeError("bad table")

        fake_module = _install_fake_louis_module(translateString=boom)
        adapter = lt.LiblouisPythonAdapter()
        with patch.dict(sys.modules, {"louis": fake_module}), \
             patch.object(lt, "_python_binding_module_available", return_value=True):
            self.assertFalse(adapter.check_table())

    def test_check_table_none_when_module_unavailable(self):
        adapter = lt.LiblouisPythonAdapter()
        with patch.object(lt, "_python_binding_module_available", return_value=False):
            self.assertIsNone(adapter.check_table())

    def test_engine_name_identifies_python_binding(self):
        adapter = lt.LiblouisPythonAdapter()
        self.assertEqual(adapter.engine_name(), "liblouis-python")

    def test_table_name_matches_constructor_argument(self):
        adapter = lt.LiblouisPythonAdapter(table="custom-table.utb")
        self.assertEqual(adapter.table_name(), "custom-table.utb")


class LiblouisSubprocessAdapterTests(unittest.TestCase):
    def test_is_available_reflects_cli_presence(self):
        adapter = lt.LiblouisSubprocessAdapter()
        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"):
            self.assertTrue(adapter.is_available())
        with patch.object(lt, "_cli_tool_path", return_value=None):
            self.assertFalse(adapter.is_available())

    def test_translate_line_invokes_subprocess_with_argument_list_and_no_shell(self):
        adapter = lt.LiblouisSubprocessAdapter(table="th-g1.utb", timeout=5.0)
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="⠁⠃\n", stderr="")

        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"), \
             patch("subprocess.run", return_value=completed) as mock_run:
            result = adapter.translate_line("hi")

        self.assertEqual(result, "⠁⠃")
        args, kwargs = mock_run.call_args
        # ต้องระบุ display table "-d unicode.dis" อย่างชัดเจนเสมอ (ยืนยันกับ
        # Liblouis 3.38.0 จริงแล้วว่าถ้าไม่ระบุ จะไม่ได้ Unicode Braille กลับมา)
        self.assertEqual(args[0], ["/usr/bin/lou_translate", "-d", "unicode.dis", "th-g1.utb"])
        self.assertEqual(kwargs["input"], "hi")
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 5.0)
        self.assertNotIsInstance(args[0], str)  # ต้องเป็น list ไม่ใช่ shell string เดียว

    def test_translate_line_uses_unicode_display_table_constant_not_literal(self):
        # ยืนยันว่า argument ที่ 2 (index 2) ตรงกับค่าคงที่ UNICODE_DISPLAY_TABLE
        # เสมอ ไม่ใช่สตริง "unicode.dis" ที่กระจัดกระจายอยู่หลายที่ในโค้ด
        adapter = lt.LiblouisSubprocessAdapter(table="th-g1.utb")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="⠁\n", stderr="")
        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"), \
             patch("subprocess.run", return_value=completed) as mock_run:
            adapter.translate_line("x")
        args, _ = mock_run.call_args
        self.assertEqual(args[0][1], "-d")
        self.assertEqual(args[0][2], lt.UNICODE_DISPLAY_TABLE)
        self.assertEqual(lt.UNICODE_DISPLAY_TABLE, "unicode.dis")

    def test_translate_line_display_table_flag_precedes_table_name(self):
        adapter = lt.LiblouisSubprocessAdapter(table="custom-table.utb")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="⠁\n", stderr="")
        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"), \
             patch("subprocess.run", return_value=completed) as mock_run:
            adapter.translate_line("x")
        args, _ = mock_run.call_args
        self.assertEqual(args[0], ["/usr/bin/lou_translate", "-d", "unicode.dis", "custom-table.utb"])

    def test_timeout_expired_raises_translation_timeout_error(self):
        adapter = lt.LiblouisSubprocessAdapter(table="th-g1.utb", timeout=2.0)
        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"), \
             patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="lou_translate", timeout=2.0)):
            with self.assertRaises(TranslationTimeoutError):
                adapter.translate_line("hi")

    def test_nonzero_return_code_raises_internal_error_without_leaking_stderr(self):
        adapter = lt.LiblouisSubprocessAdapter(table="th-g1.utb")
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="secret internal path /etc/shadow"
        )
        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"), \
             patch("subprocess.run", return_value=completed):
            with self.assertRaises(InternalTranslationError) as ctx:
                adapter.translate_line("hi")
        self.assertNotIn("/etc/shadow", str(ctx.exception))

    def test_translate_line_raises_when_cli_not_found(self):
        adapter = lt.LiblouisSubprocessAdapter()
        with patch.object(lt, "_cli_tool_path", return_value=None):
            with self.assertRaises(InternalTranslationError):
                adapter.translate_line("hi")

    def test_check_table_uses_lou_checktable_when_present(self):
        adapter = lt.LiblouisSubprocessAdapter(table="th-g1.utb")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        def which_side_effect(name):
            return f"/usr/bin/{name}" if name in ("lou_translate", "lou_checktable") else None

        with patch.object(lt, "_cli_tool_path", side_effect=lambda candidates: which_side_effect(candidates[0])), \
             patch("subprocess.run", return_value=completed) as mock_run:
            result = adapter.check_table()

        self.assertTrue(result)
        args, _ = mock_run.call_args
        self.assertEqual(args[0], ["/usr/bin/lou_checktable", "th-g1.utb"])

    def test_check_table_false_on_nonzero_exit(self):
        adapter = lt.LiblouisSubprocessAdapter(table="bad-table.utb")
        completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_checktable"), \
             patch("subprocess.run", return_value=completed):
            self.assertFalse(adapter.check_table())

    def test_check_table_none_when_cli_entirely_unavailable(self):
        adapter = lt.LiblouisSubprocessAdapter()
        with patch.object(lt, "_cli_tool_path", return_value=None):
            self.assertIsNone(adapter.check_table())

    def test_engine_name_identifies_cli(self):
        adapter = lt.LiblouisSubprocessAdapter()
        self.assertEqual(adapter.engine_name(), "liblouis-cli")

    def test_input_text_passed_via_stdin_not_argv(self):
        adapter = lt.LiblouisSubprocessAdapter(table="th-g1.utb")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="⠁\n", stderr="")
        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"), \
             patch("subprocess.run", return_value=completed) as mock_run:
            adapter.translate_line("some text that must not appear as an argv element")
        args, kwargs = mock_run.call_args
        self.assertNotIn("some text that must not appear as an argv element", args[0])
        self.assertEqual(kwargs["input"], "some text that must not appear as an argv element")

    def test_raw_successful_output_contains_unicode_braille_characters(self):
        # จำลองผลลัพธ์จริงที่ยืนยันแล้วบนเครื่องนี้ (Liblouis 3.38.0):
        # "hello" -> "⠓⠑⠇⠇⠕" - ตรวจว่าทุกตัวอักษรที่ translate_line() คืนมาอยู่
        # ในช่วง Unicode Braille Patterns (U+2800-U+28FF) จริง ไม่ใช่ข้อความปกติ
        # ที่หลุดผ่านมาโดยไม่ได้เข้ารหัส (ปัญหาเดิมก่อนเพิ่ม -d unicode.dis)
        adapter = lt.LiblouisSubprocessAdapter(table="th-g1.utb")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="⠓⠑⠇⠇⠕\n", stderr="")
        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"), \
             patch("subprocess.run", return_value=completed):
            result = adapter.translate_line("hello")

        self.assertTrue(len(result) > 0)
        for char in result:
            self.assertTrue(0x2800 <= ord(char) <= 0x28FF, f"{char!r} ไม่ใช่ Unicode Braille")

    def test_output_without_display_table_would_not_be_unicode_braille(self):
        # เอกสารเชิงเทสต์: จำลองพฤติกรรมเดิมที่ผิด (ไม่ระบุ -d) เพื่อยืนยันว่า
        # ถ้า lou_translate คืนข้อความธรรมดากลับมา (ไม่ใช่เบรลล์) โค้ดชั้นบน
        # (braille_models.convert_unicode_braille_string) จะตรวจพบและรายงาน
        # เป็น non_braille_output ไม่ใช่ตีความผิดเงียบ ๆ - ยืนยันว่าการแก้ไขนี้
        # จำเป็นจริง ไม่ใช่แค่ทางเลือก
        from braille_models import convert_unicode_braille_string

        plain_text_output = "hello"  # พฤติกรรมเดิมก่อนแก้ไข (ไม่มี -d unicode.dis)
        cells, diagnostics = convert_unicode_braille_string(plain_text_output)
        self.assertEqual(cells, [])
        self.assertEqual(len(diagnostics), 5)
        self.assertTrue(all(d.code == "non_braille_output" for d in diagnostics))

    def test_check_table_probe_fallback_also_uses_display_table(self):
        # เมื่อไม่มี lou_checktable (fallback ไปแปลข้อความสั้น ๆ ทดสอบ) ต้องยังคง
        # เรียกผ่าน translate_line() เดิม จึงได้ -d unicode.dis ด้วยเสมอ
        adapter = lt.LiblouisSubprocessAdapter(table="th-g1.utb")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="⠀\n", stderr="")

        def which_side_effect(candidates):
            return "/usr/bin/lou_translate" if candidates[0] == "lou_translate" else None

        with patch.object(lt, "_cli_tool_path", side_effect=which_side_effect), \
             patch("subprocess.run", return_value=completed) as mock_run:
            result = adapter.check_table()

        self.assertTrue(result)
        args, _ = mock_run.call_args
        self.assertIn("-d", args[0])
        self.assertIn("unicode.dis", args[0])


class NoHardwareCouplingTests(unittest.TestCase):
    """liblouis_translator.py ต้องไม่ยุ่งกับ Serial/ESP32 เลยไม่ว่ากรณีใด -
    การแก้ไขนี้ (เพิ่ม -d unicode.dis) ต้องไม่เปิดช่องทางใหม่ให้เชื่อมต่อ
    ฮาร์ดแวร์โดยไม่ตั้งใจ
    """

    def test_module_has_no_serial_or_esp32_imports_or_references(self):
        import ast
        import pathlib

        source = pathlib.Path(lt.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module.split(".")[0])

        self.assertNotIn("serial", imported_modules)
        self.assertNotIn("flask", imported_modules)
        self.assertNotIn("ser_conn", source)
        self.assertNotIn("app.route", source)

    def test_translate_line_never_writes_to_any_serial_port(self):
        # ยืนยันด้วยพฤติกรรมจริง: ระหว่างแปลข้อความ subprocess.run ต้องถูกเรียก
        # เพียงครั้งเดียว (ไปยัง lou_translate เท่านั้น) ไม่มีการเรียก serial
        # write หรือ subprocess อื่นใดแอบแฝงอยู่
        adapter = lt.LiblouisSubprocessAdapter(table="th-g1.utb")
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="⠓⠑⠇⠇⠕\n", stderr="")
        with patch.object(lt, "_cli_tool_path", return_value="/usr/bin/lou_translate"), \
             patch("subprocess.run", return_value=completed) as mock_run:
            adapter.translate_line("hello")
        self.assertEqual(mock_run.call_count, 1)
        called_executable = mock_run.call_args[0][0][0]
        self.assertIn("lou_translate", called_executable)


if __name__ == "__main__":
    unittest.main()
