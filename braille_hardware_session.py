"""Step 6: เซสชันการเล่นเบรลล์ไปยังฮาร์ดแวร์แบบมีการ์ด (guarded playback session)

รับผิดชอบ "สถานะเซสชันฝั่งเซิร์ฟเวอร์" เท่านั้น - ไม่รู้จัก Flask, OCR, Liblouis
หรือ DOM รับ :class:`BrailleHardwareTransport` เข้ามาแล้วบังคับกติกาความปลอดภัย:

  - เปิดได้ครั้งละ 1 เซสชันเท่านั้น
  - ทุกคำขอต้องพก session_id + generation ที่ตรงกับเซสชันปัจจุบัน
  - เริ่มเซสชันต้องล้างเซลล์ก่อนเสมอ
  - แยก "ช่องว่างชั่วคราวระหว่างเซลล์" (ไม่เพิ่ม real-cell index) ออกจาก
    "เซลล์ว่างจริง" (เป็นเซลล์ที่มี index)
  - watchdog ฝั่ง host: ทุกคำขอเซลล์ที่ถูกต้อง refresh เส้นตาย ถ้าเลยเส้นตาย
    -> ยกเลิกเซสชัน + best-effort clear + บันทึก safety event (ไม่มีข้อความ OCR)
  - stop: ยกเลิกเซสชัน "ก่อน" ทำงานอื่น แล้ว best-effort clear เพียงครั้งเดียว

**ข้อจำกัดที่ต้องระบุให้ชัด**: watchdog ฝั่ง host ป้องกันไม่ได้เมื่อเครื่อง
คอมพิวเตอร์แครช สาย USB หลุด หรือไฟดับ - ยังต้องมี watchdog ระดับเฟิร์มแวร์
สำหรับ actuator ที่ร้อนเกินได้
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from typing import Any, Callable, Optional

from braille_hardware import (
    CLEAR_PATTERN,
    BrailleHardwareTransport,
    HardwareTransportError,
    validate_pattern,
)

logger = logging.getLogger(__name__)

#: เส้นตาย watchdog เริ่มต้น (วินาที) - ปรับได้ตอน start()
DEFAULT_WATCHDOG_SECONDS = 4.0
#: เส้นตายสูงสุดที่ยอมให้ตั้ง - กันการตั้งค่ายาวจนไร้ความหมาย
MAX_WATCHDOG_SECONDS = 30.0
MIN_WATCHDOG_SECONDS = 1.0


class HardwareSessionError(Exception):
    """error ของชั้นเซสชัน - พก ``code`` แบบ machine-readable เสมอ"""

    def __init__(self, code: str, message: str, *, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class _Session:
    __slots__ = (
        "id",
        "generation",
        "real_cell_index",
        "watchdog_seconds",
        "deadline",
        "watchdog_timer",
        "created_at",
        "alive",
        "cells_sent",
        "last_event",
    )

    def __init__(self, session_id: str, watchdog_seconds: float, now: float):
        self.id = session_id
        self.generation = 0
        self.real_cell_index = -1  # ยังไม่ส่งเซลล์จริงเลย
        self.watchdog_seconds = watchdog_seconds
        self.deadline = now + watchdog_seconds
        self.watchdog_timer: Optional[Any] = None
        self.created_at = now
        self.alive = True
        self.cells_sent = 0
        self.last_event = "started"


class HardwarePlaybackSessionManager:
    """จัดการเซสชันเดียว + watchdog เดียว - thread-safe ด้วย RLock

    :param timer_factory: callable(delay_seconds, callback) -> timer object ที่มี
        ``.start()`` และ ``.cancel()`` (ค่าเริ่มต้น :class:`threading.Timer`)
        เทสต์ inject fake timer เพื่อควบคุมเวลาแบบ deterministic
    :param monotonic: callable() -> float (ค่าเริ่มต้น :func:`time.monotonic`)
    :param safety_event_sink: callable(dict) รับ safety event (ห้ามมีข้อความ OCR)
    """

    def __init__(
        self,
        *,
        timer_factory: Optional[Callable[[float, Callable[[], None]], Any]] = None,
        monotonic: Optional[Callable[[], float]] = None,
        safety_event_sink: Optional[Callable[[dict], None]] = None,
    ):
        self._lock = threading.RLock()
        self._session: Optional[_Session] = None
        self._transport: Optional[BrailleHardwareTransport] = None
        self._timer_factory = timer_factory or (lambda delay, cb: threading.Timer(delay, cb))
        self._monotonic = monotonic or time.monotonic
        self._safety_events: list[dict] = []
        self._safety_event_sink = safety_event_sink

    # --- สถานะ ------------------------------------------------------------

    @property
    def safety_events(self) -> list[dict]:
        return list(self._safety_events)

    def status(self) -> dict[str, Any]:
        with self._lock:
            transport = self._transport
            available = bool(transport and transport.is_available())
            session = self._session
            if session is None or not session.alive:
                return {
                    "active": False,
                    "session_id": None,
                    "generation": None,
                    "real_cell_index": None,
                    "transport_available": available,
                    "transport_kind": getattr(transport, "kind", None),
                    # ไม่มี ACK parsing → บอกตรง ๆ ว่าอุปกรณ์ยืนยันไม่ได้
                    "acknowledged_by_device": None,
                    "physically_displayed": None,
                    "ack_supported": False,
                    "watchdog_seconds": None,
                    "safety_event_count": len(self._safety_events),
                }
            return {
                "active": True,
                "session_id": session.id,
                "generation": session.generation,
                "real_cell_index": session.real_cell_index,
                "cells_sent": session.cells_sent,
                "transport_available": available,
                "transport_kind": getattr(transport, "kind", None),
                "acknowledged_by_device": None,
                "physically_displayed": None,
                "ack_supported": False,
                "watchdog_seconds": session.watchdog_seconds,
                "watchdog_deadline_in": round(session.deadline - self._monotonic(), 3),
                "last_event": session.last_event,
                "safety_event_count": len(self._safety_events),
            }

    # --- เริ่มเซสชัน -----------------------------------------------------

    def start(
        self,
        transport: BrailleHardwareTransport,
        *,
        watchdog_seconds: float = DEFAULT_WATCHDOG_SECONDS,
    ) -> dict[str, Any]:
        with self._lock:
            if not transport.is_available():
                raise HardwareSessionError(
                    "serial_not_connected",
                    "ต้องเลือกและเชื่อมต่อพอร์ต Serial และเปิดโหมดฮาร์ดแวร์จริงก่อนเริ่มเซสชัน",
                    status_code=409,
                )
            if self._session is not None and self._session.alive:
                raise HardwareSessionError(
                    "session_conflict",
                    "มีเซสชันการเล่นฮาร์ดแวร์ที่กำลังทำงานอยู่แล้ว กรุณาหยุดเซสชันเดิมก่อน",
                    status_code=409,
                )

            watchdog_seconds = self._clamp_watchdog(watchdog_seconds)

            # ล้างเซลล์ก่อนเริ่มเสมอ - ถ้าล้างไม่ได้ ถือว่าเริ่มเซสชันไม่ได้
            try:
                transport.clear()
            except HardwareTransportError as exc:
                raise HardwareSessionError(
                    "clear_failed",
                    f"ล้างเซลล์ก่อนเริ่มเซสชันไม่สำเร็จ: {exc.message}",
                    status_code=502,
                ) from exc

            session = _Session(self._new_id(), watchdog_seconds, self._monotonic())
            self._session = session
            self._transport = transport
            self._arm_watchdog(session)
            logger.info("hardware playback session started id=%s", session.id)
            return {
                "session_id": session.id,
                "generation": session.generation,
                "watchdog_seconds": watchdog_seconds,
                "cleared_before_start": True,
                "ack_supported": False,
            }

    # --- ส่งเซลล์ -------------------------------------------------------

    def send_cell(
        self,
        session_id: str,
        generation: int,
        pattern: str,
        *,
        real_cell_index: Optional[int] = None,
        transient_gap: bool = False,
    ) -> dict[str, Any]:
        """ส่งหนึ่ง complete-state pattern

        ต้องระบุ **อย่างใดอย่างหนึ่ง**:
          - ``transient_gap=True``  -> ช่องว่างชั่วคราวระหว่างเซลล์ ส่ง
            :data:`CLEAR_PATTERN` แต่ **ไม่เพิ่ม** real_cell_index
          - ``real_cell_index=N``   -> เซลล์จริงลำดับที่ N (เซลล์ว่างจริงก็มา
            ทางนี้ ส่ง CLEAR_PATTERN ได้ แต่ยังนับเป็น index)
        """
        with self._lock:
            session = self._require_session(session_id, generation)

            if transient_gap and real_cell_index is not None:
                raise HardwareSessionError(
                    "invalid_pattern",
                    "ระบุได้อย่างเดียว: ช่องว่างชั่วคราว หรือ เซลล์จริงที่มี index",
                    status_code=400,
                )
            if not transient_gap and real_cell_index is None:
                raise HardwareSessionError(
                    "invalid_pattern",
                    "ต้องระบุ real_cell_index หรือ transient_gap อย่างใดอย่างหนึ่ง",
                    status_code=400,
                )

            if transient_gap:
                effective_pattern = CLEAR_PATTERN
            else:
                if not isinstance(real_cell_index, int) or real_cell_index < 0:
                    raise HardwareSessionError(
                        "invalid_pattern", "real_cell_index ต้องเป็นจำนวนเต็ม >= 0", status_code=400
                    )
                # ปฏิเสธ index ที่ถอยหลังหรือกระโดดข้าม (อนุญาตซ้ำ index เดิมได้
                # เพื่อรองรับการส่งสถานะซ้ำ แต่ห้ามข้ามหรือย้อน)
                if real_cell_index > session.real_cell_index + 1:
                    raise HardwareSessionError(
                        "stale_session",
                        f"ลำดับเซลล์ไม่ต่อเนื่อง (คาดหวัง <= {session.real_cell_index + 1} ได้รับ {real_cell_index})",
                        status_code=409,
                    )
                if real_cell_index < session.real_cell_index:
                    raise HardwareSessionError(
                        "stale_session",
                        f"ปฏิเสธ callback ของเซลล์ที่ล้าสมัย (index {real_cell_index} < {session.real_cell_index})",
                        status_code=409,
                    )
                try:
                    effective_pattern = validate_pattern(pattern)
                except HardwareTransportError as exc:
                    raise HardwareSessionError("invalid_pattern", exc.message, status_code=400) from exc

            transport = self._transport
            assert transport is not None
            try:
                result = transport.display_pattern(effective_pattern)
            except HardwareTransportError as exc:
                raise HardwareSessionError(exc.code, exc.message, status_code=502) from exc

            if not transient_gap:
                session.real_cell_index = max(session.real_cell_index, real_cell_index)  # type: ignore[arg-type]
                session.last_event = "cell"
            else:
                session.last_event = "transient_gap"
            session.cells_sent += 1

            # ทุกคำขอที่ถูกต้อง refresh เส้นตาย watchdog
            self._refresh_watchdog(session)

            return {
                "accepted_by_server": True,
                "written_to_serial": result.get("written_to_serial", True),
                "bytes_written": result.get("bytes_written"),
                "pattern": effective_pattern,
                "session_id": session.id,
                # generation ใหม่หลัง refresh - client ต้องใช้ค่านี้ในคำขอถัดไป
                "generation": session.generation,
                "real_cell_index": session.real_cell_index if not transient_gap else None,
                "transient_gap": transient_gap,
                # ยังไม่มี ACK parsing → unknown เสมอ
                "acknowledged_by_device": None,
                "physically_displayed": None,
                "ack_supported": False,
            }

    # --- หยุดเซสชัน ----------------------------------------------------

    def stop(self, session_id: Optional[str] = None) -> dict[str, Any]:
        """ยกเลิกเซสชัน "ก่อน" ทำงานอื่น แล้ว best-effort clear เพียงครั้งเดียว

        คืน status แบบมีโครงสร้างเสมอ แม้การล้างจะล้มเหลว
        """
        with self._lock:
            session = self._session
            if session is None or not session.alive:
                return {"stopped": True, "was_active": False, "cleared": False}

            if session_id is not None and session_id != session.id:
                raise HardwareSessionError(
                    "stale_session", "session_id ไม่ตรงกับเซสชันปัจจุบัน", status_code=409
                )

            transport = self._transport
            # 1) ยกเลิกก่อน - timer เก่าที่ยิงหลังจากนี้จะไม่ทำอะไร (generation เปลี่ยน)
            self._invalidate_locked(reason="stopped")

            # 2) best-effort clear ครั้งเดียว
            cleared = False
            clear_error: Optional[str] = None
            if transport is not None:
                try:
                    transport.clear()
                    cleared = True
                except HardwareTransportError as exc:
                    clear_error = exc.message
                    logger.warning("stop(): clear failed: %s", exc.message)

            return {
                "stopped": True,
                "was_active": True,
                "cleared": cleared,
                "clear_error": clear_error,
            }

    def shutdown(self) -> None:
        """เรียกตอน Flask process ปิด - best-effort clear ถ้าทำได้"""
        try:
            self.stop()
        except Exception:  # noqa: BLE001 - shutdown ต้องไม่ throw
            logger.exception("hardware session shutdown clear failed")

    # --- ภายใน ---------------------------------------------------------

    @staticmethod
    def _clamp_watchdog(seconds: float) -> float:
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            seconds = DEFAULT_WATCHDOG_SECONDS
        return max(MIN_WATCHDOG_SECONDS, min(MAX_WATCHDOG_SECONDS, seconds))

    @staticmethod
    def _new_id() -> str:
        return secrets.token_hex(8)

    def _require_session(self, session_id: str, generation: int) -> _Session:
        session = self._session
        if session is None or not session.alive:
            raise HardwareSessionError(
                "session_not_active", "ไม่มีเซสชันการเล่นฮาร์ดแวร์ที่กำลังทำงานอยู่", status_code=409
            )
        if session_id != session.id:
            raise HardwareSessionError(
                "stale_session", "session_id ไม่ถูกต้องหรือหมดอายุแล้ว", status_code=409
            )
        try:
            generation = int(generation)
        except (TypeError, ValueError):
            raise HardwareSessionError("stale_session", "generation ไม่ถูกต้อง", status_code=409)
        if generation != session.generation:
            raise HardwareSessionError(
                "stale_session",
                f"generation ล้าสมัย (คาดหวัง {session.generation} ได้รับ {generation})",
                status_code=409,
            )
        return session

    def _arm_watchdog(self, session: _Session) -> None:
        gen_at_arm = session.generation
        session_id = session.id

        def _fire() -> None:
            self._on_watchdog_expiry(session_id, gen_at_arm)

        timer = self._timer_factory(session.watchdog_seconds, _fire)
        session.watchdog_timer = timer
        # daemon เพื่อไม่ค้าง process ตอนปิด (เฉพาะ threading.Timer จริง)
        if isinstance(timer, threading.Timer):
            timer.daemon = True
        timer.start()

    def _cancel_watchdog(self, session: _Session) -> None:
        timer = session.watchdog_timer
        session.watchdog_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:  # noqa: BLE001
                pass

    def _refresh_watchdog(self, session: _Session) -> None:
        # เพิ่ม generation เพื่อทำให้ callback ของ timer เก่าเป็นโมฆะ แล้ว arm ใหม่
        self._cancel_watchdog(session)
        session.generation += 1
        session.deadline = self._monotonic() + session.watchdog_seconds
        self._arm_watchdog(session)

    def _on_watchdog_expiry(self, session_id: str, gen_at_arm: int) -> None:
        with self._lock:
            session = self._session
            # timer เก่าของเซสชันอื่น/generation เก่า -> เพิกเฉย
            if session is None or not session.alive or session.id != session_id:
                return
            if session.generation != gen_at_arm:
                return

            transport = self._transport
            logger.warning("hardware watchdog expired for session=%s", session_id)
            self._invalidate_locked(reason="watchdog_expired")

            cleared = False
            if transport is not None:
                try:
                    transport.clear()
                    cleared = True
                except HardwareTransportError as exc:
                    logger.error("watchdog clear failed: %s", exc.message)

            event = {
                "type": "watchdog_expired",
                "session_id": session_id,
                "cleared": cleared,
                "at": self._monotonic(),
                # จงใจ: ไม่มีข้อความ OCR หรือเนื้อหาเอกสารใด ๆ ใน safety event
            }
            self._safety_events.append(event)
            if self._safety_event_sink is not None:
                try:
                    self._safety_event_sink(dict(event))
                except Exception:  # noqa: BLE001
                    logger.exception("safety_event_sink raised")

    def _invalidate_locked(self, *, reason: str) -> None:
        session = self._session
        if session is None:
            return
        self._cancel_watchdog(session)
        session.alive = False
        session.generation += 1  # callback ที่ยิงหลังจากนี้เป็นโมฆะทั้งหมด
        session.last_event = reason
        self._session = None
        # ไม่ล้าง self._transport ที่นี่ - ให้ผู้เรียก (stop/watchdog) ใช้ก่อน
