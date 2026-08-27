"""Step 6: ขอบเขตส่งข้อมูลไปยังฮาร์ดแวร์เบรลล์ (hardware transport boundary)

โมดูลนี้ **แยกอิสระ** จาก playback, OCR, Liblouis และ Flask routes โดยสิ้นเชิง
ไม่ import สิ่งใดจาก app.py / ocr_service / braille_translation - มีหน้าที่เดียว
คือรับ "รูปแบบจุด 6 บิตที่ตรวจสอบแล้ว" หนึ่งเซลล์ แล้วส่งออกไปยัง transport ที่
กำหนด (Serial จริง, mock สำหรับเทสต์, หรือ transport ที่ไม่พร้อมใช้งาน)

=== ความหมายของ "สำเร็จ" (ดู README หัวข้อ Step 6) ===
เฟิร์มแวร์ปัจจุบัน **ไม่มี ACK ที่ยืนยันได้** จึงต้องแยกสี่ระดับให้ชัดเจน:
  - accepted_by_server     : เซิร์ฟเวอร์รับคำขอและผ่าน validation
  - written_to_serial      : เขียน bytes ลง OS serial buffer + flush() แล้ว
  - acknowledged_by_device : **unknown เสมอ** จนกว่าจะมี ACK parsing จริง
  - physically_displayed   : **unknown เสมอ** - bytes ที่เขียนไม่ได้พิสูจน์ว่า
                             เซลล์ถูกยกจุดขึ้นจริงบนฮาร์ดแวร์

ห้ามสร้างพฤติกรรม ACK ปลอม ห้ามรายงานว่า "ESP32 แสดงผลสำเร็จ" เพียงเพราะ
write()/flush() คืนค่าปกติ
"""

from __future__ import annotations

import logging
import re
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# --- ค่าคงที่ของโปรโตคอล (ยืนยันจากซอร์สโค้ดเดิม app.py: f"{pattern}\n") -------

#: รูปแบบที่ยอมรับได้เพียงอย่างเดียว: อักขระ '0'/'1' จำนวน 6 ตัวพอดี เรียงตาม
#: ลำดับจุด 1,2,3,4,5,6 (ตรงกับ braille_models.bit_pattern_from_bitmask)
PATTERN_RE = re.compile(r"^[01]{6}$")

#: คำสั่งล้างเซลล์ (ทุกจุดลง) - เก็บเป็นค่าคงที่มีชื่อ ห้าม hardcode "000000"
#: กระจายในโค้ด **คำเตือน**: การที่เฟิร์มแวร์ตีความ pattern นี้ว่า "ปลดพลังงาน
#: ทุกจุดอย่างปลอดภัย" ยัง **ไม่ได้รับการยืนยัน** จาก repo evidence
CLEAR_PATTERN = "000000"

#: ตัวคั่นบรรทัดที่ต่อท้าย 6 บิตเสมอ (LF) - ตรงกับ app.py เดิม
LINE_DELIMITER = b"\n"

#: baud rate ที่ยืนยันจาก app.DEFAULT_BAUD เดิม
DEFAULT_HARDWARE_BAUD = 115200

#: ลำดับจุดมาตรฐาน - ใช้ยืนยันว่า encode ไม่สลับลำดับ
DOT_ORDER = (1, 2, 3, 4, 5, 6)

#: รูปแบบสำหรับโหมดตรวจสอบลำดับจุดด้วยมือ (แต่ละจุดทีละจุด + ล้าง) - ไม่รวม
#: "111111" (all-on) โดยเจตนา
MANUAL_VERIFICATION_PATTERNS = (
    "100000",
    "010000",
    "001000",
    "000100",
    "000010",
    "000001",
    CLEAR_PATTERN,
)


# --- error แบบมีโครงสร้าง ------------------------------------------------------


class HardwareTransportError(Exception):
    """base ของ error ทุกชนิดในชั้น transport - พก ``code`` แบบ machine-readable
    เสมอ ไม่มี stack trace หรือ raw device path หลุดไปถึง response
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class InvalidPatternError(HardwareTransportError):
    def __init__(self, message: str = "รูปแบบจุดต้องเป็นอักขระ 0/1 จำนวน 6 ตัวพอดี"):
        super().__init__("invalid_pattern", message)


class TransportUnavailableError(HardwareTransportError):
    def __init__(self, message: str = "ช่องทางส่งข้อมูลไปยังฮาร์ดแวร์ยังไม่พร้อมใช้งาน"):
        super().__init__("serial_not_connected", message)


class WriteFailedError(HardwareTransportError):
    def __init__(self, message: str = "เขียนข้อมูลลงพอร์ต Serial ไม่สำเร็จ"):
        super().__init__("write_failed", message)


class ClearFailedError(HardwareTransportError):
    def __init__(self, message: str = "ส่งคำสั่งล้างเซลล์ไม่สำเร็จ"):
        super().__init__("clear_failed", message)


# --- ฟังก์ชัน validate / encode (บริสุทธิ์ ทดสอบง่าย) --------------------------


def validate_pattern(pattern: Any) -> str:
    """คืน pattern เดิมถ้าถูกต้อง มิฉะนั้น raise InvalidPatternError

    ยอมรับเฉพาะ ``str`` ที่ตรง ``^[01]{6}$`` เท่านั้น - ปฏิเสธ Unicode Braille,
    ข้อความ OCR, bytes, ตัวเลข, ความยาวผิด, อักขระอื่น
    """
    if not isinstance(pattern, str) or PATTERN_RE.match(pattern) is None:
        raise InvalidPatternError(
            f"รูปแบบจุดไม่ถูกต้อง ต้องเป็นสตริง '0'/'1' 6 หลัก (ได้รับชนิด "
            f"{type(pattern).__name__})"
        )
    return pattern


def encode_pattern(pattern: Any) -> bytes:
    """แปลงรูปแบบจุด 6 บิตเป็น payload ไบต์ที่ส่งจริง: ASCII 6 บิต + LF

    รักษาลำดับจุด 1..6 ตามสตริงต้นฉบับ (ไม่กลับด้าน ไม่ padding) ผลลัพธ์ยาว 7
    ไบต์เสมอ เช่น ``encode_pattern("101010") == b"101010\\n"``
    """
    valid = validate_pattern(pattern)
    return valid.encode("ascii") + LINE_DELIMITER


# --- abstraction ------------------------------------------------------------


class BrailleHardwareTransport(ABC):
    """สัญญา (contract) ของช่องทางส่งข้อมูลหนึ่งเซลล์ไปยังฮาร์ดแวร์

    ทุก implementation ต้อง:
      - ยอมรับเฉพาะรูปแบบ ``^[01]{6}$`` (ใช้ ``encode_pattern``)
      - เข้ารหัสเป็น ASCII 6 บิต + LF เท่านั้น
      - serialize การเขียนด้วย lock
      - ไม่ยอมรับข้อความ OCR หรือ Unicode Braille โดยตรง
      - **ไม่** อ้างว่า bytes ที่เขียน = เซลล์แสดงผลจริง
    """

    #: ป้ายกำกับชนิด transport (สำหรับ log/response) - override ในคลาสลูก
    kind: str = "abstract"

    @abstractmethod
    def is_available(self) -> bool:
        """True เฉพาะเมื่อพร้อมส่งข้อมูลจริง ณ ขณะนี้"""

    @abstractmethod
    def display_pattern(self, pattern: str) -> dict[str, Any]:
        """ส่งหนึ่งเซลล์ (complete-state pattern) ไปยังฮาร์ดแวร์

        คืน dict สถานะที่ **ไม่** อ้าง ACK หรือการแสดงผลจริง:
        ``{"written_to_serial": bool, "bytes_written": int, "pattern": str,
        "acknowledged_by_device": None, "physically_displayed": None}``
        """

    @abstractmethod
    def clear(self) -> dict[str, Any]:
        """ส่ง :data:`CLEAR_PATTERN` (best-effort ปลดทุกจุด)"""

    @abstractmethod
    def close(self) -> None:
        """ปิดทรัพยากรที่ถือครองอยู่ (best-effort ส่ง clear ก่อนปิดถ้าทำได้)"""

    # alias ให้เรียก disconnect() ได้เหมือน close()
    def disconnect(self) -> None:
        self.close()

    @staticmethod
    def _result(pattern: str, bytes_written: int, *, written: bool = True) -> dict[str, Any]:
        return {
            "pattern": pattern,
            "written_to_serial": written,
            "bytes_written": bytes_written,
            # ไม่มี ACK parsing → ไม่รู้ทั้งคู่ ห้ามตั้งเป็น True เด็ดขาด
            "acknowledged_by_device": None,
            "physically_displayed": None,
        }


class UnavailableBrailleHardwareTransport(BrailleHardwareTransport):
    """transport ที่ไม่พร้อมใช้งาน - ทุกการส่งข้อมูล raise error แบบมีโครงสร้าง

    ใช้เป็นค่าเริ่มต้นของระบบ เมื่อยังไม่ยืนยันความปลอดภัยของโปรโตคอล/การล้าง
    เซลล์ (ดู README) หรือเมื่อ pyserial/พอร์ตไม่พร้อม
    """

    kind = "unavailable"

    def __init__(self, reason: str = "ยังไม่เปิดใช้งานโหมดฮาร์ดแวร์จริง หรือยังไม่ยืนยันความปลอดภัยของโปรโตคอล"):
        self.reason = reason

    def is_available(self) -> bool:
        return False

    def display_pattern(self, pattern: str) -> dict[str, Any]:
        validate_pattern(pattern)  # ยังคง validate เพื่อพฤติกรรมสม่ำเสมอ
        raise TransportUnavailableError(self.reason)

    def clear(self) -> dict[str, Any]:
        raise TransportUnavailableError(self.reason)

    def close(self) -> None:
        return None


class MockBrailleHardwareTransport(BrailleHardwareTransport):
    """transport จำลองแบบ deterministic สำหรับเทสต์ - ไม่มี I/O จริงใด ๆ

    บันทึกทุก payload ไบต์ที่ "เขียน" ลง ``self.writes`` (list ของ bytes) เพื่อให้
    เทสต์ยืนยันได้ว่า payload ตรงเป๊ะ เช่น ``b"101010\\n"`` และการเขียนถูก
    serialize ด้วย lock จริง
    """

    kind = "mock"

    def __init__(self, *, available: bool = True):
        self._available = available
        self._lock = threading.Lock()
        self.writes: list[bytes] = []
        self.closed = False
        self.clear_calls = 0
        #: ตั้งเป็น exception instance เพื่อจำลองความล้มเหลวของการเขียน/ล้าง
        self.fail_next_write: Optional[Exception] = None
        self.fail_next_clear: Optional[Exception] = None
        #: ใช้พิสูจน์ว่าการเขียนถูก serialize จริง (นับ concurrency สูงสุด)
        self._in_write = 0
        self.max_concurrent_writes = 0

    def set_available(self, value: bool) -> None:
        self._available = bool(value)

    def is_available(self) -> bool:
        return self._available and not self.closed

    def _write_locked(self, payload: bytes, failure: Optional[Exception]) -> None:
        with self._lock:
            self._in_write += 1
            self.max_concurrent_writes = max(self.max_concurrent_writes, self._in_write)
            try:
                if failure is not None:
                    raise failure
                self.writes.append(payload)
            finally:
                self._in_write -= 1

    def display_pattern(self, pattern: str) -> dict[str, Any]:
        payload = encode_pattern(pattern)
        if not self.is_available():
            raise TransportUnavailableError()
        failure, self.fail_next_write = self.fail_next_write, None
        try:
            self._write_locked(payload, failure)
        except HardwareTransportError:
            raise
        except Exception as exc:  # noqa: BLE001 - จำลอง OSError ของ pyserial
            raise WriteFailedError(f"การเขียนจำลองล้มเหลว: {exc}") from exc
        return self._result(pattern, len(payload))

    def clear(self) -> dict[str, Any]:
        self.clear_calls += 1
        payload = encode_pattern(CLEAR_PATTERN)
        if not self.is_available():
            raise TransportUnavailableError()
        failure, self.fail_next_clear = self.fail_next_clear, None
        try:
            self._write_locked(payload, failure)
        except HardwareTransportError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ClearFailedError(f"การล้างจำลองล้มเหลว: {exc}") from exc
        return self._result(CLEAR_PATTERN, len(payload))

    def close(self) -> None:
        # best-effort clear ก่อนปิด (เลียนแบบ transport จริง)
        if self.is_available():
            try:
                self.clear()
            except HardwareTransportError:
                pass
        self.closed = True


class SerialBrailleHardwareTransport(BrailleHardwareTransport):
    """transport production ที่ **ใช้ซ้ำ** การเชื่อมต่อ Serial เดิมของแอป

    ไม่สร้าง ``serial.Serial`` ของตัวเอง ไม่มี logic เปิดพอร์ตซ้ำซ้อนกับ
    ``app.init_serial`` - รับ callable สองตัวผ่าน dependency injection:

      - ``get_serial()``   -> คืน pyserial handle ปัจจุบัน (หรือ None)
      - ``write_lock``     -> threading.Lock เดียวกับที่ /send ใช้ (serialize)

    ``enabled_check()`` (ไม่บังคับ) -> คืน True เฉพาะเมื่อผู้ควบคุมเปิด flag
    ความปลอดภัยครบแล้ว (ดู app: BRAILLE_HARDWARE_ENABLED + _SAFETY_CONFIRMED)
    """

    kind = "serial"

    def __init__(
        self,
        get_serial: Callable[[], Any],
        write_lock: threading.Lock,
        *,
        enabled_check: Optional[Callable[[], bool]] = None,
    ):
        self._get_serial = get_serial
        self._write_lock = write_lock
        self._enabled_check = enabled_check or (lambda: True)

    def is_available(self) -> bool:
        if not self._enabled_check():
            return False
        ser = self._get_serial()
        return ser is not None and getattr(ser, "is_open", False)

    def _write(self, payload: bytes) -> None:
        ser = self._get_serial()
        if not self._enabled_check() or ser is None or not getattr(ser, "is_open", False):
            raise TransportUnavailableError()
        # serialize กับ /send เดิม - ไม่มีการเขียนพอร์ตพร้อมกันสองเส้นทาง
        with self._write_lock:
            try:
                ser.write(payload)
                ser.flush()
            except HardwareTransportError:
                raise
            except Exception as exc:  # noqa: BLE001 - SerialException/OSError
                raise WriteFailedError("เขียนข้อมูลลงพอร์ต Serial ไม่สำเร็จ (สาย USB อาจหลุด)") from exc

    def display_pattern(self, pattern: str) -> dict[str, Any]:
        payload = encode_pattern(pattern)
        self._write(payload)
        logger.info("hardware cell written to serial (%d bytes)", len(payload))
        return self._result(pattern, len(payload))

    def clear(self) -> dict[str, Any]:
        payload = encode_pattern(CLEAR_PATTERN)
        try:
            self._write(payload)
        except WriteFailedError as exc:
            raise ClearFailedError(str(exc)) from exc
        logger.info("hardware clear pattern written to serial")
        return self._result(CLEAR_PATTERN, len(payload))

    def close(self) -> None:
        # best-effort clear ก่อนปิด - แต่ไม่ปิด handle เอง เพราะ handle เป็นของ
        # app (ใช้ร่วมกับ /send) การปิดเป็นหน้าที่ของ app.init_serial เท่านั้น
        try:
            if self.is_available():
                self.clear()
        except HardwareTransportError:
            pass
