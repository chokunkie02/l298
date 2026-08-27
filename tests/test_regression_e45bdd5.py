"""Regression tests สำหรับ commit e45bdd5 ("fix: liblouis fallback, UI contrast,
hardware auto playback and 3s duration") ที่ทำให้เกิดการถดถอย 3 เรื่องฝั่ง Python:

  1. app._hardware_real_mode_enabled() เปิดโดยดีฟอลต์ (ตัด flag ที่สองทิ้ง)
  2. liblouis_translator fallback ไป LegacyDictionaryTranslator เงียบ ๆ
  3. DEFAULT_WATCHDOG_SECONDS ถูกดันจาก 4 -> 10 โดยไม่มีหลักฐานความปลอดภัย

เทสต์เหล่านี้ตรึงพฤติกรรมที่ถูกต้อง (safety-restored) ไว้ - ไม่มีการเปิดพอร์ต
Serial จริง ไม่มีการตั้ง env flag ฮาร์ดแวร์ใด ๆ
"""

import importlib
import os
import unittest
from unittest.mock import patch

import app as app_module
import braille_hardware_session
import liblouis_translator
from braille_hardware import (
    SerialBrailleHardwareTransport,
    UnavailableBrailleHardwareTransport,
)


class HardwareSafetyGateFlagCombinations(unittest.TestCase):
    """โหมดฮาร์ดแวร์จริงต้องมี **ทั้งสอง** flag เสมอ (ครบทุก 4 คู่)"""

    _FLAGS = ("BRAILLE_HARDWARE_ENABLED", "BRAILLE_HARDWARE_SAFETY_CONFIRMED")

    def _run_with_env(self, enabled, safety):
        env = dict(os.environ)
        for name in self._FLAGS:
            env.pop(name, None)
        if enabled is not None:
            env["BRAILLE_HARDWARE_ENABLED"] = enabled
        if safety is not None:
            env["BRAILLE_HARDWARE_SAFETY_CONFIRMED"] = safety
        env.pop("BRAILLE_HARDWARE_MOCK", None)
        with patch.dict(os.environ, env, clear=True):
            return app_module._hardware_real_mode_enabled(), app_module._build_hardware_transport()

    def test_neither_flag_is_unavailable(self):
        enabled, transport = self._run_with_env(None, None)
        self.assertFalse(enabled)
        self.assertIsInstance(transport, UnavailableBrailleHardwareTransport)

    def test_only_enabled_flag_is_unavailable(self):
        enabled, transport = self._run_with_env("1", None)
        self.assertFalse(enabled)
        self.assertIsInstance(transport, UnavailableBrailleHardwareTransport)

    def test_only_safety_confirmed_flag_is_unavailable(self):
        enabled, transport = self._run_with_env(None, "1")
        self.assertFalse(enabled)
        self.assertIsInstance(transport, UnavailableBrailleHardwareTransport)

    def test_both_flags_enables_serial_transport(self):
        enabled, transport = self._run_with_env("1", "1")
        self.assertTrue(enabled)
        self.assertIsInstance(transport, SerialBrailleHardwareTransport)
        # ยังไม่พร้อมจริงเพราะไม่มี ser_conn เปิดอยู่ (ไม่แตะพอร์ตจริง)
        self.assertFalse(transport.is_available())

    def test_enabled_flag_set_to_zero_is_disabled(self):
        enabled, _ = self._run_with_env("0", "1")
        self.assertFalse(enabled)

    def test_open_serial_port_alone_never_implies_safety(self):
        # แม้ ser_conn จะเปิดอยู่ ถ้าไม่มี flag ครบ transport ต้องไม่พร้อมใช้งาน
        class FakeSer:
            is_open = True

        env = {k: v for k, v in os.environ.items() if k not in self._FLAGS}
        env.pop("BRAILLE_HARDWARE_MOCK", None)
        with patch.dict(os.environ, env, clear=True), patch.object(app_module, "ser_conn", FakeSer()):
            transport = app_module._build_hardware_transport()
        self.assertIsInstance(transport, UnavailableBrailleHardwareTransport)


class WatchdogDefaultRestored(unittest.TestCase):
    def test_default_watchdog_is_conservative_four_seconds(self):
        self.assertEqual(braille_hardware_session.DEFAULT_WATCHDOG_SECONDS, 4.0)

    def test_default_watchdog_is_within_bounds(self):
        self.assertGreaterEqual(
            braille_hardware_session.DEFAULT_WATCHDOG_SECONDS,
            braille_hardware_session.MIN_WATCHDOG_SECONDS,
        )
        self.assertLessEqual(
            braille_hardware_session.DEFAULT_WATCHDOG_SECONDS,
            braille_hardware_session.MAX_WATCHDOG_SECONDS,
        )

    def test_watchdog_value_remains_configurable_and_bounded(self):
        mgr = braille_hardware_session.HardwarePlaybackSessionManager()
        self.assertEqual(mgr._clamp_watchdog(2.0), 2.0)
        self.assertEqual(mgr._clamp_watchdog(999), braille_hardware_session.MAX_WATCHDOG_SECONDS)
        self.assertEqual(mgr._clamp_watchdog(0), braille_hardware_session.MIN_WATCHDOG_SECONDS)


class LiblouisNeverFallsBackToLegacy(unittest.TestCase):
    def test_no_binding_no_cli_returns_unavailable_not_legacy(self):
        from braille_translation import UnavailableBrailleTranslator

        with patch.object(liblouis_translator, "_python_binding_module_available", return_value=False), \
             patch.object(liblouis_translator, "_cli_tool_path", return_value=None):
            translator = liblouis_translator.create_default_translator()
        self.assertIsInstance(translator, UnavailableBrailleTranslator)

    def test_create_default_translator_source_has_no_legacy_import(self):
        import inspect

        source = inspect.getsource(liblouis_translator.create_default_translator)
        # docstring อาจกล่าวถึงชื่อคลาสได้ แต่ต้องไม่มี import จริง
        self.assertNotIn("from legacy_braille_dictionary import", source)
        self.assertNotIn("LegacyDictionaryTranslator(", source)

    def test_module_does_not_import_legacy_dictionary_at_all(self):
        import ast
        import pathlib

        tree = ast.parse(pathlib.Path(liblouis_translator.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertNotEqual(node.module, "legacy_braille_dictionary")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotEqual(alias.name, "legacy_braille_dictionary")

    def test_app_translate_route_returns_503_when_translator_unavailable(self):
        from braille_translation import UnavailableBrailleTranslator

        client = app_module.app.test_client()
        unavailable = UnavailableBrailleTranslator(table="th-g1.utb", reason="no liblouis")
        with patch.object(app_module, "braille_translator", unavailable):
            resp = client.post("/api/braille/translate", json={"text": "hello"})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.get_json()["error"]["code"], "translator_unavailable")


if __name__ == "__main__":
    unittest.main()
