import os
import sys
import logging
from io import BytesIO

from flask import Flask, render_template, request, jsonify
import serial
import serial.tools.list_ports
from werkzeug.exceptions import RequestEntityTooLarge

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
    try:
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

if __name__ == "__main__":
    print("=" * 60)
    print(" Starting Braille LED Controller Web Application...")
    print(f" Initializing Serial Connection on {DEFAULT_PORT}...")
    print("=" * 60)
    
    # Attempt initial connection
    init_serial(DEFAULT_PORT)
    
    print(f"\n Web Interface is running at: http://127.0.0.1:{PORT_WEB}\n")
    app.run(host="0.0.0.0", port=PORT_WEB, debug=False, use_reloader=False)
