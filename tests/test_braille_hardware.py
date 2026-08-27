"""Step 6: เทสต์ชั้น transport (braille_hardware.py) - ไม่แตะพอร์ต Serial จริง

ครอบคลุม: payload ไบต์ที่ตรงเป๊ะ, การปฏิเสธรูปแบบผิด, ลำดับจุด 1..6,
การ serialize การเขียนด้วย lock, ค่าคงที่ clear, transport ที่ไม่พร้อมใช้งาน,
และ SerialBrailleHardwareTransport ที่ใช้ handle จำลอง (ไม่ใช่พอร์ตจริง)
"""

import threading
import unittest

from braille_hardware import (
    CLEAR_PATTERN,
    DOT_ORDER,
    MANUAL_VERIFICATION_PATTERNS,
    ClearFailedError,
    InvalidPatternError,
    MockBrailleHardwareTransport,
    SerialBrailleHardwareTransport,
    TransportUnavailableError,
    UnavailableBrailleHardwareTransport,
    WriteFailedError,
    encode_pattern,
    validate_pattern,
)


class EncodeValidateTests(unittest.TestCase):
    def test_exact_payload_bytes(self):
        self.assertEqual(encode_pattern("101010"), b"101010\n")
        self.assertEqual(encode_pattern(CLEAR_PATTERN), b"000000\n")
        self.assertEqual(encode_pattern("111111"), b"111111\n")

    def test_payload_is_seven_ascii_bytes_with_trailing_lf(self):
        payload = encode_pattern("100001")
        self.assertEqual(len(payload), 7)
        self.assertEqual(payload[-1:], b"\n")
        self.assertTrue(all(b in (0x30, 0x31) for b in payload[:6]))

    def test_dot_order_is_preserved_left_to_right(self):
        # dot 1 = อักขระตัวแรก, dot 6 = อักขระตัวสุดท้าย
        self.assertEqual(encode_pattern("100000"), b"100000\n")  # dot 1
        self.assertEqual(encode_pattern("000001"), b"000001\n")  # dot 6
        self.assertEqual(DOT_ORDER, (1, 2, 3, 4, 5, 6))

    def test_rejects_malformed_patterns(self):
        for bad in ["", "12345", "1234567", "10101", "1010102", "abcdef",
                    "10 010", "  0000", "٠٠٠٠٠٠", None, 101010, b"101010",
                    "10101\n", "10101a"]:
            with self.assertRaises(InvalidPatternError):
                validate_pattern(bad)
            with self.assertRaises(InvalidPatternError):
                encode_pattern(bad)

    def test_rejects_unicode_braille_and_ocr_text(self):
        with self.assertRaises(InvalidPatternError):
            encode_pattern("⠁")
        with self.assertRaises(InvalidPatternError):
            encode_pattern("สวัสดี")

    def test_clear_pattern_constant(self):
        self.assertEqual(CLEAR_PATTERN, "000000")

    def test_manual_verification_patterns_never_include_all_on(self):
        self.assertNotIn("111111", MANUAL_VERIFICATION_PATTERNS)
        self.assertIn(CLEAR_PATTERN, MANUAL_VERIFICATION_PATTERNS)
        self.assertEqual(
            set(MANUAL_VERIFICATION_PATTERNS),
            {"100000", "010000", "001000", "000100", "000010", "000001", "000000"},
        )


class MockTransportTests(unittest.TestCase):
    def test_display_pattern_records_exact_payload(self):
        t = MockBrailleHardwareTransport()
        result = t.display_pattern("101010")
        self.assertEqual(t.writes, [b"101010\n"])
        self.assertTrue(result["written_to_serial"])
        self.assertIsNone(result["acknowledged_by_device"])
        self.assertIsNone(result["physically_displayed"])

    def test_clear_sends_clear_pattern(self):
        t = MockBrailleHardwareTransport()
        t.clear()
        self.assertEqual(t.writes, [b"000000\n"])
        self.assertEqual(t.clear_calls, 1)

    def test_rejects_invalid_pattern_before_write(self):
        t = MockBrailleHardwareTransport()
        with self.assertRaises(InvalidPatternError):
            t.display_pattern("bad")
        self.assertEqual(t.writes, [])

    def test_unavailable_mock_raises_structured_error(self):
        t = MockBrailleHardwareTransport(available=False)
        self.assertFalse(t.is_available())
        with self.assertRaises(TransportUnavailableError):
            t.display_pattern("101010")

    def test_write_failure_is_wrapped_as_write_failed(self):
        t = MockBrailleHardwareTransport()
        t.fail_next_write = OSError("cable unplugged")
        with self.assertRaises(WriteFailedError):
            t.display_pattern("101010")

    def test_clear_failure_is_wrapped_as_clear_failed(self):
        t = MockBrailleHardwareTransport()
        t.fail_next_clear = OSError("boom")
        with self.assertRaises(ClearFailedError):
            t.clear()

    def test_writes_are_serialized_under_concurrency(self):
        t = MockBrailleHardwareTransport()
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            for _ in range(50):
                t.display_pattern("101010")

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        self.assertEqual(len(t.writes), 8 * 50)
        self.assertEqual(t.max_concurrent_writes, 1, "การเขียนต้องถูก serialize ด้วย lock")

    def test_close_best_effort_clears_then_marks_closed(self):
        t = MockBrailleHardwareTransport()
        t.close()
        self.assertTrue(t.closed)
        self.assertEqual(t.writes[-1], b"000000\n")
        self.assertFalse(t.is_available())


class UnavailableTransportTests(unittest.TestCase):
    def test_is_never_available_and_raises_serial_not_connected(self):
        t = UnavailableBrailleHardwareTransport()
        self.assertFalse(t.is_available())
        with self.assertRaises(TransportUnavailableError) as ctx:
            t.display_pattern("101010")
        self.assertEqual(ctx.exception.code, "serial_not_connected")
        with self.assertRaises(TransportUnavailableError):
            t.clear()
        t.close()  # ต้องไม่ throw


class _FakeSerial:
    def __init__(self, is_open=True):
        self.is_open = is_open
        self.written = []
        self.flushed = 0
        self.raise_on_write = None

    def write(self, payload):
        if self.raise_on_write:
            raise self.raise_on_write
        self.written.append(payload)

    def flush(self):
        self.flushed += 1


class SerialTransportTests(unittest.TestCase):
    def _make(self, ser, enabled=True):
        lock = threading.Lock()
        return SerialBrailleHardwareTransport(
            get_serial=lambda: ser, write_lock=lock, enabled_check=lambda: enabled
        )

    def test_available_only_when_enabled_and_port_open(self):
        self.assertTrue(self._make(_FakeSerial(is_open=True), enabled=True).is_available())
        self.assertFalse(self._make(_FakeSerial(is_open=False), enabled=True).is_available())
        self.assertFalse(self._make(_FakeSerial(is_open=True), enabled=False).is_available())
        self.assertFalse(self._make(None, enabled=True).is_available())

    def test_display_pattern_writes_exact_payload_and_flushes(self):
        ser = _FakeSerial()
        t = self._make(ser)
        t.display_pattern("101010")
        self.assertEqual(ser.written, [b"101010\n"])
        self.assertEqual(ser.flushed, 1)

    def test_clear_writes_clear_pattern(self):
        ser = _FakeSerial()
        self._make(ser).clear()
        self.assertEqual(ser.written, [b"000000\n"])

    def test_write_failure_becomes_write_failed_error(self):
        ser = _FakeSerial()
        ser.raise_on_write = OSError("unplugged")
        with self.assertRaises(WriteFailedError):
            self._make(ser).display_pattern("101010")

    def test_clear_failure_becomes_clear_failed_error(self):
        ser = _FakeSerial()
        ser.raise_on_write = OSError("unplugged")
        with self.assertRaises(ClearFailedError):
            self._make(ser).clear()

    def test_disabled_transport_raises_unavailable(self):
        with self.assertRaises(TransportUnavailableError):
            self._make(_FakeSerial(), enabled=False).display_pattern("101010")

    def test_never_accepts_ocr_text(self):
        with self.assertRaises(InvalidPatternError):
            self._make(_FakeSerial()).display_pattern("hello world")


if __name__ == "__main__":
    unittest.main()
