"""Step 6: เทสต์ HardwarePlaybackSessionManager - fake timer + fake clock ทั้งหมด

ไม่มีการรอเวลาจริง ไม่แตะพอร์ต Serial ใช้ MockBrailleHardwareTransport เสมอ
"""

import unittest

from braille_hardware import MockBrailleHardwareTransport
from braille_hardware_session import (
    HardwarePlaybackSessionManager,
    HardwareSessionError,
)


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeTimer:
    """เลียนแบบ threading.Timer: เก็บ callback ไว้ ให้เทสต์เรียก fire() เอง"""

    def __init__(self, registry, delay, callback):
        self.registry = registry
        self.delay = delay
        self.callback = callback
        self.cancelled = False
        self.started = False
        self.fired = False
        registry.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if self.cancelled or self.fired:
            return
        self.fired = True
        self.callback()


class SessionManagerTestBase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.timers = []
        self.mgr = HardwarePlaybackSessionManager(
            timer_factory=lambda delay, cb: FakeTimer(self.timers, delay, cb),
            monotonic=self.clock,
        )
        self.transport = MockBrailleHardwareTransport(available=True)

    def start(self, **kw):
        return self.mgr.start(self.transport, **kw)

    def active_timer(self):
        live = [t for t in self.timers if t.started and not t.cancelled and not t.fired]
        return live[-1] if live else None


class StartTests(SessionManagerTestBase):
    def test_start_requires_available_transport(self):
        self.transport.set_available(False)
        with self.assertRaises(HardwareSessionError) as ctx:
            self.start()
        self.assertEqual(ctx.exception.code, "serial_not_connected")

    def test_start_clears_hardware_before_session(self):
        self.start()
        self.assertEqual(self.transport.writes, [b"000000\n"])
        self.assertEqual(self.transport.clear_calls, 1)

    def test_start_returns_session_id_and_generation(self):
        result = self.start()
        self.assertIn("session_id", result)
        self.assertEqual(result["generation"], 0)
        self.assertTrue(result["cleared_before_start"])
        self.assertFalse(result["ack_supported"])

    def test_only_one_active_session(self):
        self.start()
        with self.assertRaises(HardwareSessionError) as ctx:
            self.start()
        self.assertEqual(ctx.exception.code, "session_conflict")

    def test_new_session_allowed_after_stop(self):
        s1 = self.start()
        self.mgr.stop()
        s2 = self.start()
        self.assertNotEqual(s1["session_id"], s2["session_id"])

    def test_watchdog_seconds_are_clamped(self):
        self.assertEqual(self.start(watchdog_seconds=999)["watchdog_seconds"], 30.0)
        self.mgr.stop()
        self.assertEqual(self.start(watchdog_seconds=0)["watchdog_seconds"], 1.0)

    def test_start_arms_exactly_one_watchdog_timer(self):
        self.start()
        started = [t for t in self.timers if t.started and not t.cancelled]
        self.assertEqual(len(started), 1)


class CellTests(SessionManagerTestBase):
    def setUp(self):
        super().setUp()
        s = self.start()
        self.sid = s["session_id"]
        self.gen = s["generation"]

    def send(self, pattern="101010", **kw):
        return self.mgr.send_cell(self.sid, self.gen, pattern, **kw)

    def test_valid_real_cell_writes_pattern_and_advances_index(self):
        r = self.send("101010", real_cell_index=0)
        self.assertEqual(self.transport.writes[-1], b"101010\n")
        self.assertEqual(r["real_cell_index"], 0)
        self.assertTrue(r["accepted_by_server"])
        self.assertIsNone(r["acknowledged_by_device"])
        self.assertFalse(r["ack_supported"])

    def test_response_never_claims_ack_or_physical_display(self):
        r = self.send("101010", real_cell_index=0)
        self.assertIsNone(r["acknowledged_by_device"])
        self.assertIsNone(r["physically_displayed"])

    def test_rejects_invalid_session_id(self):
        with self.assertRaises(HardwareSessionError) as ctx:
            self.mgr.send_cell("wrong", self.gen, "101010", real_cell_index=0)
        self.assertEqual(ctx.exception.code, "stale_session")

    def test_rejects_stale_generation(self):
        self.send("101010", real_cell_index=0)  # refresh -> generation bumps
        with self.assertRaises(HardwareSessionError) as ctx:
            self.mgr.send_cell(self.sid, 0, "010101", real_cell_index=1)
        self.assertEqual(ctx.exception.code, "stale_session")

    def test_generation_from_response_stays_valid(self):
        r1 = self.send("101010", real_cell_index=0)
        # ต้องใช้ generation ล่าสุด - แต่ในเทสต์เราติดตามผ่าน status()
        gen = self.mgr.status()["generation"]
        r2 = self.mgr.send_cell(self.sid, gen, "010101", real_cell_index=1)
        self.assertEqual(r2["real_cell_index"], 1)

    def test_rejects_out_of_order_index_jump(self):
        with self.assertRaises(HardwareSessionError) as ctx:
            self.send("101010", real_cell_index=5)
        self.assertEqual(ctx.exception.code, "stale_session")

    def test_rejects_backward_index(self):
        gen = self.mgr.status()["generation"]
        self.mgr.send_cell(self.sid, gen, "101010", real_cell_index=0)
        gen = self.mgr.status()["generation"]
        self.mgr.send_cell(self.sid, gen, "010101", real_cell_index=1)
        gen = self.mgr.status()["generation"]
        with self.assertRaises(HardwareSessionError):
            self.mgr.send_cell(self.sid, gen, "101010", real_cell_index=0)

    def test_transient_gap_sends_clear_but_does_not_advance_index(self):
        gen = self.mgr.status()["generation"]
        self.mgr.send_cell(self.sid, gen, "101010", real_cell_index=0)
        gen = self.mgr.status()["generation"]
        r = self.mgr.send_cell(self.sid, gen, "ignored", transient_gap=True)
        self.assertEqual(self.transport.writes[-1], b"000000\n")
        self.assertTrue(r["transient_gap"])
        self.assertEqual(self.mgr.status()["real_cell_index"], 0)

    def test_real_blank_cell_sends_clear_and_keeps_index(self):
        r = self.send("000000", real_cell_index=0)
        self.assertEqual(self.transport.writes[-1], b"000000\n")
        self.assertEqual(r["real_cell_index"], 0)
        self.assertFalse(r["transient_gap"])

    def test_must_specify_gap_or_index(self):
        with self.assertRaises(HardwareSessionError):
            self.send("101010")

    def test_invalid_pattern_rejected(self):
        with self.assertRaises(HardwareSessionError) as ctx:
            self.send("bad", real_cell_index=0)
        self.assertEqual(ctx.exception.code, "invalid_pattern")

    def test_cell_after_stop_is_rejected(self):
        self.mgr.stop()
        with self.assertRaises(HardwareSessionError) as ctx:
            self.send("101010", real_cell_index=0)
        self.assertEqual(ctx.exception.code, "session_not_active")


class StopTests(SessionManagerTestBase):
    def test_stop_invalidates_before_clear(self):
        s = self.start()
        # transport ที่ clear ล้มเหลว - เซสชันต้องถูกยกเลิกไปแล้วก่อน clear
        self.transport.fail_next_clear = OSError("boom")
        result = self.mgr.stop()
        self.assertTrue(result["stopped"])
        self.assertFalse(result["cleared"])
        self.assertIsNotNone(result["clear_error"])
        self.assertFalse(self.mgr.status()["active"])

    def test_stop_sends_clear_exactly_once(self):
        self.start()
        writes_before = len(self.transport.writes)
        self.mgr.stop()
        self.assertEqual(len(self.transport.writes) - writes_before, 1)
        self.assertEqual(self.transport.writes[-1], b"000000\n")

    def test_stop_when_no_session_is_safe(self):
        r = self.mgr.stop()
        self.assertFalse(r["was_active"])

    def test_stop_cancels_watchdog(self):
        self.start()
        timer = self.active_timer()
        self.mgr.stop()
        self.assertTrue(timer.cancelled)

    def test_stale_timer_cannot_fire_after_stop(self):
        self.start()
        timer = self.active_timer()
        self.mgr.stop()
        clears_before = self.transport.clear_calls
        timer.fire()  # จำลอง timer เก่าที่หลุดเข้า event loop
        self.assertEqual(self.transport.clear_calls, clears_before)


class WatchdogTests(SessionManagerTestBase):
    def test_valid_cell_refreshes_watchdog_deadline(self):
        s = self.start()
        first_timer = self.active_timer()
        gen = self.mgr.status()["generation"]
        self.mgr.send_cell(s["session_id"], gen, "101010", real_cell_index=0)
        self.assertTrue(first_timer.cancelled)
        self.assertIsNotNone(self.active_timer())
        self.assertNotEqual(self.active_timer(), first_timer)

    def test_watchdog_expiry_invalidates_and_clears_once(self):
        self.start()
        timer = self.active_timer()
        clears_before = self.transport.clear_calls
        timer.fire()
        self.assertFalse(self.mgr.status()["active"])
        self.assertEqual(self.transport.clear_calls - clears_before, 1)
        events = self.mgr.safety_events
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "watchdog_expired")

    def test_safety_event_contains_no_document_text(self):
        self.start()
        self.active_timer().fire()
        event = self.mgr.safety_events[0]
        self.assertNotIn("text", event)
        self.assertEqual(set(event) - {"type", "session_id", "cleared", "at"}, set())

    def test_old_watchdog_cannot_affect_a_new_session(self):
        s1 = self.start()
        old_timer = self.active_timer()
        self.mgr.stop()
        s2 = self.start()
        clears_before = self.transport.clear_calls
        old_timer.fire()  # timer ของเซสชันเก่า
        # เซสชันใหม่ต้องยังทำงานอยู่ ไม่ถูกล้างโดย callback เก่า
        self.assertTrue(self.mgr.status()["active"])
        self.assertEqual(self.mgr.status()["session_id"], s2["session_id"])
        self.assertEqual(self.transport.clear_calls, clears_before)

    def test_only_one_watchdog_timer_live_at_a_time(self):
        s = self.start()
        gen = self.mgr.status()["generation"]
        self.mgr.send_cell(s["session_id"], gen, "101010", real_cell_index=0)
        gen = self.mgr.status()["generation"]
        self.mgr.send_cell(s["session_id"], gen, "010101", real_cell_index=1)
        live = [t for t in self.timers if t.started and not t.cancelled and not t.fired]
        self.assertEqual(len(live), 1)

    def test_watchdog_expiry_records_clear_failure_without_crashing(self):
        self.start()
        self.transport.fail_next_clear = OSError("boom")
        self.active_timer().fire()
        self.assertFalse(self.mgr.status()["active"])
        self.assertFalse(self.mgr.safety_events[0]["cleared"])


class ShutdownTests(SessionManagerTestBase):
    def test_shutdown_best_effort_clears(self):
        self.start()
        self.mgr.shutdown()
        self.assertEqual(self.transport.writes[-1], b"000000\n")
        self.assertFalse(self.mgr.status()["active"])

    def test_shutdown_never_raises(self):
        self.start()
        self.transport.fail_next_clear = OSError("boom")
        self.mgr.shutdown()  # ต้องไม่ throw


if __name__ == "__main__":
    unittest.main()
