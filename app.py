import atexit
import os
import sys
import logging
import threading
from io import BytesIO

from flask import Flask, render_template, request, jsonify
import serial
import serial.tools.list_ports
from werkzeug.exceptions import RequestEntityTooLarge

from braille_hardware import (
    CLEAR_PATTERN,
    MANUAL_VERIFICATION_PATTERNS,
    HardwareTransportError,
    MockBrailleHardwareTransport,
    SerialBrailleHardwareTransport,
    UnavailableBrailleHardwareTransport,
)
from braille_hardware_session import (
    DEFAULT_WATCHDOG_SECONDS,
    HardwarePlaybackSessionManager,
    HardwareSessionError,
)

from ocr_service import (
    EasyOCRService,
    OCRInitializationError,
    OCRProcessingError,
    OCR_LANGUAGES,
    DEFAULT_LOW_CONFIDENCE_THRESHOLD,
)
from image_preprocessing import (
    DEFAULT_PREPROCESSING_MODE,
    ImageDecodeError,
    ImageTooLargeError,
    compute_quality_diagnostics,
    preprocess_image,
)
from legacy_braille_dictionary import THAI_BRAILLE_MAP
from braille_translation import (
    BrailleTranslationError,
    EmptyTextError,
    InternalTranslationError,
    InvalidInputTypeError,
    InvalidTranslatorOutputError,
    TableUnavailableError,
    TextTooLongError,
    TranslationTimeoutError,
    TranslatorUnavailableError,
    translate_text,
    translation_response_dict,
)
from liblouis_translator import create_default_translator

# Force UTF-8 encoding for Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Configure logging
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

# Reader ภายในบริการนี้สร้างแบบ lazy เมื่อมี OCR request แรกเท่านั้น
ocr_service = EasyOCRService()

# Default Serial Settings
DEFAULT_PORT = "COM3"
DEFAULT_BAUD = 115200
PORT_WEB = 5050

# Global serial connection reference
ser_conn = None
active_port = DEFAULT_PORT

# Lock เดียวสำหรับ serialize ทุกการเขียนพอร์ต Serial - ใช้ร่วมกันระหว่าง /send
# เดิม และ hardware transport ของ Step 6 (ไม่มีการเขียนพอร์ตพร้อมกันสองเส้นทาง)
serial_write_lock = threading.Lock()


def _hardware_flag(name):
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _hardware_real_mode_enabled():
    """โหมดฮาร์ดแวร์จริงเปิดได้เฉพาะเมื่อผู้ควบคุมตั้ง **ทั้งสอง** flag:

      BRAILLE_HARDWARE_ENABLED=1          - ยอมให้เส้นทางฮาร์ดแวร์ทำงาน
      BRAILLE_HARDWARE_SAFETY_CONFIRMED=1 - ยืนยันว่าผ่านการทดสอบฮาร์ดแวร์แบบ
                                           มีผู้ดูแลแล้ว (โปรโตคอล + การล้างเซลล์
                                           ปลอดภัย ดู README หัวข้อ Step 6)

    ค่าเริ่มต้น = ปิด → ใช้ transport ที่ไม่พร้อมใช้งาน ไม่มีการแตะพอร์ตจริง
    """
    return _hardware_flag("BRAILLE_HARDWARE_ENABLED") and _hardware_flag(
        "BRAILLE_HARDWARE_SAFETY_CONFIRMED"
    )


def _build_hardware_transport():
    """เลือก transport ตามสภาพแวดล้อม - เรียกใหม่ได้เมื่อ flag เปลี่ยน (เทสต์)"""
    if os.environ.get("BRAILLE_HARDWARE_MOCK", "").strip().lower() in ("1", "true", "yes", "on"):
        return MockBrailleHardwareTransport(available=True)
    if not _hardware_real_mode_enabled():
        return UnavailableBrailleHardwareTransport()
    return SerialBrailleHardwareTransport(
        get_serial=lambda: ser_conn,
        write_lock=serial_write_lock,
        enabled_check=_hardware_real_mode_enabled,
    )


hardware_transport = _build_hardware_transport()
hardware_session_manager = HardwarePlaybackSessionManager()


@atexit.register
def _shutdown_hardware_session():
    # best-effort clear ตอน process ปิด (ทำเท่าที่ทำได้ - ป้องกัน crash/USB หลุด
    # ไม่ได้ ต้องมี watchdog ระดับเฟิร์มแวร์เสริม)
    try:
        hardware_session_manager.shutdown()
    except Exception:  # noqa: BLE001
        pass


HARDWARE_ERROR_STATUS = {
    "serial_not_connected": 409,
    "unverified_port": 409,
    "hardware_mode_disabled": 409,
    "session_not_active": 409,
    "stale_session": 409,
    "invalid_pattern": 400,
    "write_failed": 502,
    "clear_failed": 502,
    "watchdog_expired": 409,
    "session_conflict": 409,
    "hardware_ack_unavailable": 501,
}


def _hardware_error(code, message, status_code=None):
    """error แบบมีโครงสร้างของเส้นทางฮาร์ดแวร์ - ไม่มี stack trace หรือ raw
    device path หลุดไปถึง client
    """
    if status_code is None:
        status_code = HARDWARE_ERROR_STATUS.get(code, 400)
    return jsonify({
        "ok": False,
        "error": {"code": code, "message": message},
        "ack_supported": False,
        "acknowledged_by_device": None,
        "physically_displayed": None,
    }), status_code


def list_hardware_ports():
    """รายการพอร์ต Serial พร้อม metadata จาก PySerial - **ไม่** เดาชนิดอุปกรณ์

    ไม่มีการสร้างพอร์ต COM3/COM4 ปลอม ไม่ตั้งชื่อว่า ESP32 พอร์ตที่ชื่อคล้าย
    /dev/cu.wlan-debug ถูกทำเครื่องหมายว่าไม่เกี่ยวข้อง/ยังไม่ยืนยันชนิด
    """
    ports = []
    for p in serial.tools.list_ports.comports():
        device = p.device
        ports.append({
            "device": device,
            "description": (p.description or None) if p.description != "n/a" else None,
            "hwid": (p.hwid or None) if p.hwid != "n/a" else None,
            "manufacturer": getattr(p, "manufacturer", None),
            # ยังไม่มี handshake ยืนยันตัวตน → ป้ายกำกับกลาง ๆ เสมอ
            "identity_label": "อุปกรณ์ Serial ที่ยังไม่ได้ยืนยันชนิด",
            "likely_unrelated": "wlan-debug" in device or "Bluetooth" in device,
        })
    return ports

SUPPORTED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/webp",
}


def _has_supported_image_signature(image_bytes):
    """ตรวจชนิดภาพจาก magic bytes โดยไม่บันทึกไฟล์ลงดิสก์"""
    return any((
        image_bytes.startswith(b"\xff\xd8\xff"),
        image_bytes.startswith(b"\x89PNG\r\n\x1a\n"),
        image_bytes.startswith((b"GIF87a", b"GIF89a")),
        image_bytes.startswith(b"BM"),
        image_bytes.startswith((b"II*\x00", b"MM\x00*")),
        len(image_bytes) >= 12
        and image_bytes.startswith(b"RIFF")
        and image_bytes[8:12] == b"WEBP",
    ))


def _is_valid_image(image_bytes):
    if not image_bytes or not _has_supported_image_signature(image_bytes):
        return False

    # Pillow เป็น dependency ของ EasyOCR ใช้ verify เมื่อพร้อมใช้งาน โดยไม่ decode
    # หรือแก้ไขภาพ หาก dependency ยังไม่ได้ติดตั้งให้ magic bytes เป็นด่านตรวจขั้นต่ำ
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return True

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return False
    return True


def _ocr_error(code, message, status_code):
    return jsonify({
        "ok": False,
        "text": "",
        "segments": [],
        "mean_confidence": None,
        "mean_confidence_note": (
            "mean_confidence คือค่าเฉลี่ยเลขคณิตของ confidence ทุก segment "
            "ไม่ใช่ค่ารับประกันความแม่นยำของ OCR"
        ),
        "low_confidence": False,
        "low_confidence_threshold": DEFAULT_LOW_CONFIDENCE_THRESHOLD,
        "languages": list(OCR_LANGUAGES),
        "message": message,
        "error": {
            "code": code,
            "message": message,
        },
    }), status_code


def list_available_ports():
    """Returns a list of available COM ports on the system."""
    ports = serial.tools.list_ports.comports()
    return [p.device for p in ports]

def init_serial(port_name=DEFAULT_PORT, baud_rate=DEFAULT_BAUD):
    """Safely initialize or re-initialize serial connection."""
    global ser_conn, active_port
    active_port = port_name

    # Close existing connection if open
    if ser_conn:
        try:
            ser_conn.close()
        except Exception as e:
            logging.warning(f"Error closing previous port: {e}")

    try:
        ser_conn = serial.Serial(port_name, baud_rate, timeout=1)
        logging.info(f"Successfully connected to ESP32 on {port_name} at {baud_rate} baud.")
        return True, f"Connected to {port_name}"
    except Exception as e:
        ser_conn = None
        err_msg = f"Cannot open port {port_name}: {str(e)}"
        logging.error(err_msg)
        return False, err_msg

# Thai Braille Mapping Reference Dictionary (6-dot Binary Representation)
# ย้ายไปอยู่ที่ legacy_braille_dictionary.py แล้ว (Step 4) - ดูคำเตือนเรื่องความ
# ถูกต้องที่ยังไม่ได้ตรวจสอบในไฟล์นั้น ตัวแปรนี้ import เข้ามาเพื่อคง endpoint
# /api/braille_dictionary เดิมไว้สำหรับการทดสอบฮาร์ดแวร์ด้วยมือเท่านั้น ไม่ถูก
# ใช้โดยเส้นทางแปล OCR -> เบรลล์ (/api/braille/translate ด้านล่างใช้ Liblouis
# เท่านั้น ไม่มีการ fallback มาที่พจนานุกรมนี้)

# Translator สำหรับ POST /api/braille/translate สร้างครั้งเดียวตอน import
# (ตรวจสภาพแวดล้อมแบบเบาเท่านั้น ไม่โหลดตารางจริงจนกว่าจะมีคำขอแปลจริง)
braille_translator = create_default_translator()

BRAILLE_TRANSLATION_ERROR_STATUS = {
    InvalidInputTypeError: ("invalid_text_type", 400),
    EmptyTextError: ("empty_text", 400),
    TextTooLongError: ("text_too_long", 413),
    TranslatorUnavailableError: ("translator_unavailable", 503),
    TableUnavailableError: ("table_unavailable", 503),
    TranslationTimeoutError: ("translation_timeout", 504),
    InvalidTranslatorOutputError: ("invalid_translator_output", 502),
    InternalTranslationError: ("translation_failed", 500),
}


def _braille_error(code, message, status_code):
    """คืน error แบบมีโครงสร้างเสมอ ไม่มี stack trace หรือ shell output ดิบใด ๆ
    หลุดไปถึง browser (รายละเอียดดิบถูก log ไว้ฝั่งเซิร์ฟเวอร์แล้วในจุดที่เกิด)
    """
    return jsonify({
        "ok": False,
        "cells": [],
        "cell_count": 0,
        "diagnostics": [],
        "line_boundaries": [],
        "sent_to_hardware": False,
        "message": message,
        "error": {
            "code": code,
            "message": message,
        },
    }), status_code


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.errorhandler(RequestEntityTooLarge)
def handle_oversized_upload(_error):
    return _ocr_error(
        "image_too_large",
        "ไฟล์ภาพมีขนาดใหญ่เกิน 10 เมกะไบต์ กรุณาเลือกภาพที่มีขนาดเล็กลง",
        413,
    )


@app.route("/api/ocr", methods=["POST"])
def recognize_image():
    """ตรวจไฟล์ภาพในหน่วยความจำและส่งให้บริการ EasyOCR"""
    uploaded_image = request.files.get("image")
    if uploaded_image is None:
        return _ocr_error(
            "missing_image",
            "ไม่พบไฟล์ภาพ กรุณาถ่ายหรือเลือกภาพใหม่",
            400,
        )

    if uploaded_image.mimetype not in SUPPORTED_IMAGE_MIME_TYPES:
        return _ocr_error(
            "unsupported_image_type",
            "ไฟล์ที่เลือกไม่ใช่ชนิดภาพที่รองรับ กรุณาถ่ายหรือเลือกภาพใหม่",
            415,
        )

    image_bytes = uploaded_image.read()
    if not _is_valid_image(image_bytes):
        return _ocr_error(
            "invalid_image",
            "ไม่สามารถอ่านไฟล์นี้เป็นภาพได้ กรุณาถ่ายหรือเลือกภาพใหม่",
            400,
        )

    # ค่าเริ่มต้นของ production คือแก้ EXIF orientation + resize อย่างปลอดภัยเท่านั้น
    # ยังไม่ใช้ CLAHE หรือ adaptive threshold จนกว่าจะมีข้อมูลประเมินผลจริงยืนยัน
    # ว่าช่วยเพิ่มความแม่นยำ (ดู evaluate_ocr.py และ evaluation/README.md)
    try:
        processed_image, preprocessing_info = preprocess_image(
            image_bytes, mode=DEFAULT_PREPROCESSING_MODE
        )
    except ImageTooLargeError as error:
        return _ocr_error("image_too_large", str(error), 413)
    except ImageDecodeError as error:
        return _ocr_error("invalid_image", str(error), 400)

    image_quality = compute_quality_diagnostics(processed_image)

    try:
        result = ocr_service.recognize(processed_image)
    except OCRInitializationError as error:
        logging.error("EasyOCR initialization failed")
        return _ocr_error("ocr_initialization_failed", str(error), 503)
    except OCRProcessingError as error:
        logging.error("EasyOCR inference failed")
        return _ocr_error("ocr_processing_failed", str(error), 500)

    result["image_quality"] = image_quality.to_dict()
    result["preprocessing"] = preprocessing_info.to_dict()
    return jsonify(result)


@app.route("/api/status", methods=["GET"])
def get_status():
    """Returns current serial connection status and available COM ports."""
    ports = list_available_ports()
    is_connected = ser_conn is not None and ser_conn.is_open
    return jsonify({
        "connected": is_connected,
        "active_port": active_port,
        "available_ports": ports
    })

@app.route("/api/connect", methods=["POST"])
def connect_port():
    """Allows dynamic switching or reconnecting to a specified COM port."""
    data = request.get_json() or {}
    target_port = data.get("port", active_port)
    success, message = init_serial(target_port)
    return jsonify({"success": success, "message": message, "active_port": active_port})

@app.route("/send", methods=["POST"])
@app.route("/api/send", methods=["POST"])
def send_pattern():
    """Validates 6-digit binary pattern and sends to ESP32 over Serial with auto-recovery."""
    global ser_conn, active_port
    data = request.get_json() or {}
    pattern = data.get("pattern", "").strip()

    # Validation Rule 1: Length must be 6
    if len(pattern) != 6:
        return jsonify({
            "success": False,
            "message": f"ความยาวข้อความต้องเป็น 6 หลักเท่านั้น (ได้รับ {len(pattern)} หลัก)"
        }), 400

    # Validation Rule 2: Must contain only '0' and '1'
    if not all(c in ('0', '1') for c in pattern):
        return jsonify({
            "success": False,
            "message": "รูปแบบข้อมูลไม่ถูกต้อง ต้องเป็นเลข 0 และ 1 เท่านั้น"
        }), 400

    # If connection handle is closed or missing, try reconnecting
    if ser_conn is None or not ser_conn.is_open:
        success, err = init_serial(active_port)
        if not success:
            return jsonify({
                "success": False,
                "message": f"ไม่สามารถเชื่อมต่อ ESP32 ผ่านพอร์ต {active_port} ได้ กรุณากดปุ่ม Reconnect (🔄) ด้านบนขวา"
            }), 500

    payload = f"{pattern}\n".encode("utf-8")

    # Try sending payload with auto-reconnect logic if handle was broken due to cable unplug
    # (serial_write_lock ทำให้การเขียนพอร์ตจาก /send และ hardware transport ของ
    #  Step 6 ไม่ทับซ้อนกัน - พฤติกรรมภายนอกของ /send เดิมไม่เปลี่ยน)
    try:
        with serial_write_lock:
            ser_conn.write(payload)
            ser_conn.flush()
        logging.info(f"Sent to ESP32 ({active_port}): {pattern}")
        return jsonify({
            "success": True,
            "message": f"ส่งข้อมูล {pattern} ไปยัง ESP32 ({active_port}) สำเร็จ!",
            "pattern": pattern
        })
    except Exception as initial_err:
        logging.warning(f"Write failed ({initial_err}), attempting auto-reconnect on {active_port}...")
        # Close broken handle
        try:
            if ser_conn:
                ser_conn.close()
        except Exception:
            pass
        ser_conn = None

        # Re-initialize serial port
        reconnect_success, msg = init_serial(active_port)
        if reconnect_success:
            try:
                with serial_write_lock:
                    ser_conn.write(payload)
                    ser_conn.flush()
                logging.info(f"Retry sent to ESP32 ({active_port}): {pattern}")
                return jsonify({
                    "success": True,
                    "message": f"เชื่อมต่อสายใหม่และส่งข้อมูล {pattern} สำเร็จ!",
                    "pattern": pattern
                })
            except Exception as retry_err:
                return jsonify({
                    "success": False,
                    "message": f"การส่งข้อมูลล้มเหลว: {str(retry_err)}"
                }), 500
        else:
            return jsonify({
                "success": False,
                "message": f"สาย USB ถูกถอด กรุณากดปุ่ม Reconnect (🔄) ที่มุมบนขวาของหน้าเว็บอีกครั้ง"
            }), 500

@app.route("/api/braille_dictionary", methods=["GET"])
def get_dictionary():
    """Returns Thai & English Braille mapping dictionary."""
    return jsonify(THAI_BRAILLE_MAP)


@app.route("/api/braille/translate", methods=["POST"])
def translate_braille():
    """แปลงข้อความที่ผู้ใช้ยืนยันแล้ว (จาก OCR หรือแหล่งอื่น) เป็นลำดับเซลล์
    เบรลล์ 6 จุดด้วย Liblouis (ดู braille_translation.py/liblouis_translator.py)

    **ไม่ส่งข้อมูลไปยัง Serial/ESP32 ในขั้นตอนนี้เลย** (Step 4 หยุดอยู่ที่การ
    แปลงเป็นโครงสร้างข้อมูลเท่านั้น sent_to_hardware เป็น False เสมอในคำตอบ)
    ไม่มีการ fallback ไปยัง legacy_braille_dictionary หากไม่มี Liblouis - จะ
    คืน error แบบมีโครงสร้าง (translator_unavailable) แทน
    """
    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        return _braille_error("invalid_request_body", "ต้องส่งข้อมูลแบบ JSON ที่มีฟิลด์ text", 400)

    if "text" not in payload:
        return _braille_error("missing_text", "ไม่พบฟิลด์ text ในคำขอ", 400)

    text = payload.get("text")

    try:
        translation = translate_text(text, braille_translator)
    except tuple(BRAILLE_TRANSLATION_ERROR_STATUS.keys()) as error:
        code, status_code = BRAILLE_TRANSLATION_ERROR_STATUS[type(error)]
        logging.warning("Braille translation rejected (%s): %s", code, error)
        return _braille_error(code, str(error), status_code)
    except BrailleTranslationError as error:
        # กันไว้สำหรับ subclass ใหม่ในอนาคตที่ยังไม่ได้ map สถานะไว้ข้างบน
        logging.error("Unmapped BrailleTranslationError", exc_info=True)
        return _braille_error("translation_failed", str(error), 500)

    response = translation_response_dict(translation, sent_to_hardware=False)
    response["ok"] = True
    return jsonify(response)


# ============================================================================
# Step 6: เส้นทางฮาร์ดแวร์แบบมีการ์ด (guarded hardware playback)
# ----------------------------------------------------------------------------
# ทุกเส้นทางนี้ทำงานผ่าน hardware_transport + hardware_session_manager เท่านั้น
# ไม่แตะ ser_conn โดยตรง ไม่รับข้อความ OCR ไม่ log เนื้อหาเอกสาร ค่าเริ่มต้นของ
# transport คือ "ไม่พร้อมใช้งาน" จนกว่าจะตั้ง env flag ความปลอดภัยครบ
# ============================================================================


def _hardware_status_payload():
    status = hardware_session_manager.status()
    status["ok"] = True
    status["real_mode_enabled"] = _hardware_real_mode_enabled()
    # รายงาน transport ระดับโมดูลเสมอ (แม้ยังไม่มีเซสชัน) เพื่อให้ UI รู้ว่า
    # เส้นทางฮาร์ดแวร์พร้อมหรือไม่ก่อนกดเริ่มเซสชัน
    status["transport_kind"] = getattr(hardware_transport, "kind", None)
    status["transport_available"] = bool(hardware_transport.is_available())
    status["clear_pattern"] = CLEAR_PATTERN
    status["serial_payload_example"] = "b'101010\\n' (ASCII 6 บิต + LF, 115200 baud)"
    status["ack_note"] = (
        "เฟิร์มแวร์ปัจจุบันไม่มี ACK ที่ยืนยันได้ - 'written_to_serial' ไม่ได้แปลว่า "
        "'ESP32 แสดงผลสำเร็จ'"
    )
    return status


@app.route("/api/hardware/status", methods=["GET"])
def hardware_status():
    return jsonify(_hardware_status_payload())


@app.route("/api/hardware/ports", methods=["GET"])
def hardware_ports():
    return jsonify({
        "ok": True,
        "ports": list_hardware_ports(),
        "note": "ต้องเลือกพอร์ตเอง ระบบไม่เลือกอัตโนมัติและไม่เดาว่าพอร์ตใดเป็น ESP32",
    })


@app.route("/api/hardware/playback/start", methods=["POST"])
def hardware_playback_start():
    data = request.get_json(silent=True) or {}
    if not _hardware_real_mode_enabled() and not isinstance(
        hardware_transport, MockBrailleHardwareTransport
    ):
        return _hardware_error(
            "hardware_mode_disabled",
            "โหมดฮาร์ดแวร์จริงยังไม่เปิดใช้งานบนเซิร์ฟเวอร์นี้ (ต้องตั้ง BRAILLE_HARDWARE_ENABLED "
            "และ BRAILLE_HARDWARE_SAFETY_CONFIRMED หลังผ่านการทดสอบฮาร์ดแวร์แบบมีผู้ดูแล)",
        )
    if not data.get("hardware_playback_opt_in") is True:
        return _hardware_error(
            "hardware_mode_disabled",
            "ต้องยืนยันการเปิดโหมดฮาร์ดแวร์จริงอย่างชัดเจน (hardware_playback_opt_in=true)",
        )
    watchdog_seconds = data.get("watchdog_seconds", DEFAULT_WATCHDOG_SECONDS)
    try:
        result = hardware_session_manager.start(
            hardware_transport, watchdog_seconds=watchdog_seconds
        )
    except HardwareSessionError as exc:
        return _hardware_error(exc.code, exc.message, exc.status_code)
    result["ok"] = True
    return jsonify(result)


@app.route("/api/hardware/playback/cell", methods=["POST"])
def hardware_playback_cell():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    generation = data.get("generation")
    pattern = data.get("bit_pattern") or data.get("pattern") or ""
    transient_gap = bool(data.get("transient_gap"))
    real_cell_index = data.get("real_cell_index")
    if not isinstance(session_id, str) or not session_id:
        return _hardware_error("session_not_active", "ต้องระบุ session_id ของเซสชันที่กำลังทำงานอยู่")
    try:
        result = hardware_session_manager.send_cell(
            session_id,
            generation,
            pattern,
            real_cell_index=real_cell_index,
            transient_gap=transient_gap,
        )
    except HardwareSessionError as exc:
        return _hardware_error(exc.code, exc.message, exc.status_code)
    result["ok"] = True
    result["message_for_ui"] = (
        "ส่งคำสั่งผ่าน Serial แล้ว แต่ยังไม่ได้รับการยืนยันจากอุปกรณ์"
    )
    return jsonify(result)


@app.route("/api/hardware/playback/stop", methods=["POST"])
def hardware_playback_stop():
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    try:
        result = hardware_session_manager.stop(session_id if isinstance(session_id, str) else None)
    except HardwareSessionError as exc:
        return _hardware_error(exc.code, exc.message, exc.status_code)
    result["ok"] = True
    return jsonify(result)


@app.route("/api/hardware/verify/cell", methods=["POST"])
def hardware_verify_cell():
    """โหมดตรวจสอบลำดับจุดด้วยมือ - ทดสอบทีละรูปแบบ ไม่ใช่การเล่นอัตโนมัติ

    ยอมรับเฉพาะรูปแบบใน MANUAL_VERIFICATION_PATTERNS (จุดเดียว + ล้าง) - **ไม่มี**
    "111111" (all-on) ใช้กลไกเซสชัน + watchdog เดียวกันเพื่อจำกัดเวลาการจ่าย
    พลังงาน ผู้ใช้ต้องกดสั่งแต่ละรูปแบบเอง
    """
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    generation = data.get("generation")
    pattern = data.get("bit_pattern") or data.get("pattern") or ""
    if pattern not in MANUAL_VERIFICATION_PATTERNS:
        return _hardware_error(
            "invalid_pattern",
            "โหมดตรวจสอบด้วยมือรับได้เฉพาะรูปแบบจุดเดียว (100000..000001) และรูปแบบล้าง (000000)",
        )
    if not isinstance(session_id, str) or not session_id:
        return _hardware_error("session_not_active", "ต้องเริ่มเซสชันตรวจสอบก่อน (ใช้ /api/hardware/playback/start)")
    try:
        result = hardware_session_manager.send_cell(
            session_id, generation, pattern, real_cell_index=0
        )
    except HardwareSessionError as exc:
        return _hardware_error(exc.code, exc.message, exc.status_code)
    result["ok"] = True
    result["verification_note"] = (
        "ตรวจสอบเฉพาะลำดับจุดเชิงตรรกะ (dot 1-6) เท่านั้น ไม่ได้ยืนยันหมายเลขขา GPIO ของ ESP32"
    )
    return jsonify(result)


if __name__ == "__main__":
    print("=" * 60)
    print(" Starting Braille LED Controller Web Application...")
    print(f" Initializing Serial Connection on {DEFAULT_PORT}...")
    print("=" * 60)
    
    # Attempt initial connection
    init_serial(DEFAULT_PORT)
    
    print(f"\n Web Interface is running at: http://127.0.0.1:{PORT_WEB}\n")
    app.run(host="0.0.0.0", port=PORT_WEB, debug=False, use_reloader=False)
