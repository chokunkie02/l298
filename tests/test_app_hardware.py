"""Step 6: เทสต์เส้นทาง Flask ฮาร์ดแวร์ - mock transport เสมอ ไม่แตะพอร์ตจริง

รวมถึงการยืนยันว่า /send เดิมยังทำงานเข้ากันได้ย้อนหลัง และเส้นทางฮาร์ดแวร์ใหม่
ปิดอยู่โดยค่าเริ่มต้น
"""

import unittest
from unittest.mock import patch

import app as app_module
from braille_hardware import MockBrailleHardwareTransport
from braille_hardware_session import HardwarePlaybackSessionManager


class FakeTimer:
    def __init__(self, registry, delay, cb):
        self.delay, self.callback, self.cancelled, self.fired = delay, cb, False, False
        registry.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled and not self.fired:
            self.fired = True
            self.callback()


class HardwareApiTestBase(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        self.transport = MockBrailleHardwareTransport(available=True)
        self.timers = []
        self.manager = HardwarePlaybackSessionManager(
            timer_factory=lambda d, cb: FakeTimer(self.timers, d, cb)
        )
        self._patches = [
            patch.object(app_module, "hardware_transport", self.transport),
            patch.object(app_module, "hardware_session_manager", self.manager),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def start_session(self, **body):
        body.setdefault("hardware_playback_opt_in", True)
        return self.client.post("/api/hardware/playback/start", json=body)


class DefaultDisabledTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_status_reports_hardware_disabled_by_default(self):
        r = self.client.get("/api/hardware/status")
        data = r.get_json()
        self.assertFalse(data["real_mode_enabled"])
        self.assertFalse(data["active"])
        self.assertFalse(data["ack_supported"])

    def test_start_rejected_when_real_mode_disabled(self):
        r = self.client.post(
            "/api/hardware/playback/start", json={"hardware_playback_opt_in": True}
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error"]["code"], "hardware_mode_disabled")

    def test_no_env_flags_means_unavailable_transport(self):
        self.assertFalse(app_module._hardware_real_mode_enabled())


class OptInAndSessionTests(HardwareApiTestBase):
    def test_start_requires_explicit_opt_in(self):
        r = self.client.post("/api/hardware/playback/start", json={})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.get_json()["error"]["code"], "hardware_mode_disabled")

    def test_start_clears_hardware_and_returns_session(self):
        r = self.start_session()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.transport.writes, [b"000000\n"])
        data = r.get_json()
        self.assertIn("session_id", data)
        self.assertFalse(data["ack_supported"])

    def test_only_one_session_at_a_time(self):
        self.start_session()
        r = self.start_session()
        self.assertEqual(r.get_json()["error"]["code"], "session_conflict")

    def test_cell_requires_valid_session_id(self):
        self.start_session()
        r = self.client.post(
            "/api/hardware/playback/cell",
            json={"session_id": "nope", "generation": 0, "bit_pattern": "101010", "real_cell_index": 0},
        )
        self.assertEqual(r.get_json()["error"]["code"], "stale_session")

    def test_cell_success_response_does_not_claim_ack_or_physical_display(self):
        s = self.start_session().get_json()
        r = self.client.post(
            "/api/hardware/playback/cell",
            json={
                "session_id": s["session_id"],
                "generation": s["generation"],
                "bit_pattern": "101010",
                "real_cell_index": 0,
            },
        )
        data = r.get_json()
        self.assertEqual(self.transport.writes[-1], b"101010\n")
        self.assertIsNone(data["acknowledged_by_device"])
        self.assertIsNone(data["physically_displayed"])
        self.assertEqual(
            data["message_for_ui"],
            "ส่งคำสั่งผ่าน Serial แล้ว แต่ยังไม่ได้รับการยืนยันจากอุปกรณ์",
        )

    def test_cell_rejects_ocr_text_pattern(self):
        s = self.start_session().get_json()
        r = self.client.post(
            "/api/hardware/playback/cell",
            json={
                "session_id": s["session_id"],
                "generation": s["generation"],
                "bit_pattern": "สวัสดี",
                "real_cell_index": 0,
            },
        )
        self.assertEqual(r.get_json()["error"]["code"], "invalid_pattern")

    def test_stop_invalidates_and_clears(self):
        s = self.start_session().get_json()
        r = self.client.post("/api/hardware/playback/stop", json={"session_id": s["session_id"]})
        data = r.get_json()
        self.assertTrue(data["stopped"])
        self.assertTrue(data["cleared"])
        self.assertFalse(self.client.get("/api/hardware/status").get_json()["active"])

    def test_stop_returns_structured_status_even_if_clear_fails(self):
        s = self.start_session().get_json()
        self.transport.fail_next_clear = OSError("boom")
        r = self.client.post("/api/hardware/playback/stop", json={"session_id": s["session_id"]})
        data = r.get_json()
        self.assertTrue(data["stopped"])
        self.assertFalse(data["cleared"])

    def test_watchdog_expiry_clears_and_ends_session(self):
        self.start_session()
        live = [t for t in self.timers if not t.cancelled and not t.fired]
        clears_before = self.transport.clear_calls
        live[-1].fire()
        self.assertEqual(self.transport.clear_calls - clears_before, 1)
        self.assertFalse(self.client.get("/api/hardware/status").get_json()["active"])

    def test_transient_gap_does_not_advance_real_index(self):
        s = self.start_session().get_json()
        gen = self.client.get("/api/hardware/status").get_json()["generation"]
        self.client.post(
            "/api/hardware/playback/cell",
            json={"session_id": s["session_id"], "generation": gen, "bit_pattern": "101010", "real_cell_index": 0},
        )
        gen = self.client.get("/api/hardware/status").get_json()["generation"]
        self.client.post(
            "/api/hardware/playback/cell",
            json={"session_id": s["session_id"], "generation": gen, "transient_gap": True},
        )
        self.assertEqual(self.transport.writes[-1], b"000000\n")
        self.assertEqual(self.client.get("/api/hardware/status").get_json()["real_cell_index"], 0)


class ManualVerificationTests(HardwareApiTestBase):
    def test_rejects_all_on_pattern(self):
        s = self.start_session().get_json()
        r = self.client.post(
            "/api/hardware/verify/cell",
            json={"session_id": s["session_id"], "generation": s["generation"], "bit_pattern": "111111"},
        )
        self.assertEqual(r.get_json()["error"]["code"], "invalid_pattern")

    def test_accepts_single_dot_pattern(self):
        s = self.start_session().get_json()
        r = self.client.post(
            "/api/hardware/verify/cell",
            json={"session_id": s["session_id"], "generation": s["generation"], "bit_pattern": "001000"},
        )
        data = r.get_json()
        self.assertEqual(self.transport.writes[-1], b"001000\n")
        self.assertIn("ไม่ได้ยืนยันหมายเลขขา GPIO", data["verification_note"])


class PortSafetyTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_port_list_does_not_fabricate_com_ports(self):
        class P:
            def __init__(self, device, description="n/a", hwid="n/a"):
                self.device, self.description, self.hwid = device, description, hwid
                self.manufacturer = None

        with patch("serial.tools.list_ports.comports", return_value=[]):
            data = self.client.get("/api/hardware/ports").get_json()
        self.assertEqual(data["ports"], [])
        self.assertNotIn("COM3", str(data))
        self.assertNotIn("COM4", str(data))

    def test_wlan_debug_is_not_labeled_esp32(self):
        class P:
            device = "/dev/cu.wlan-debug"
            description = "n/a"
            hwid = "n/a"
            manufacturer = None

        with patch("serial.tools.list_ports.comports", return_value=[P()]):
            data = self.client.get("/api/hardware/ports").get_json()
        port = data["ports"][0]
        self.assertNotIn("ESP32", port["identity_label"])
        self.assertTrue(port["likely_unrelated"])
        self.assertEqual(port["identity_label"], "อุปกรณ์ Serial ที่ยังไม่ได้ยืนยันชนิด")


class LegacySendBackwardCompatTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_send_still_validates_length(self):
        r = self.client.post("/send", json={"pattern": "123"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("6 หลัก", r.get_json()["message"])

    def test_send_still_validates_binary_only(self):
        r = self.client.post("/send", json={"pattern": "12345a"})
        self.assertEqual(r.status_code, 400)

    def test_send_writes_exact_legacy_payload_through_lock(self):
        class FakeSer:
            is_open = True

            def __init__(self):
                self.written = []

            def write(self, p):
                self.written.append(p)

            def flush(self):
                pass

        fake = FakeSer()
        with patch.object(app_module, "ser_conn", fake):
            r = self.client.post("/send", json={"pattern": "101010"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fake.written, [b"101010\n"])

    def test_send_source_still_has_no_ack_parsing(self):
        import inspect

        source = inspect.getsource(app_module.send_pattern)
        self.assertNotIn(".read(", source)
        self.assertNotIn("readline", source)


if __name__ == "__main__":
    unittest.main()
