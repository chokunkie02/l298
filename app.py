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
THAI_BRAILLE_MAP = {
    # Thai Consonants (พยัญชนะไทย)
    "ก": "110000", "ข": "101000", "ฃ": "101000", "ค": "100100", "ฅ": "100100",
    "ฆ": "100110", "ง": "010110", "จ": "110100", "ฉ": "101100", "ช": "100111",
    "ซ": "101001", "ฌ": "010111", "ญ": "011011", "ฎ": "111010", "ฏ": "111110",
    "ฐ": "101011", "ฑ": "011100", "ฒ": "011111", "ณ": "001111", "ด": "100110",
    "ต": "011010", "ถ": "011100", "ท": "011101", "ธ": "011001", "น": "101110",
    "บ": "111000", "ป": "111100", "ผ": "110010", "ฝ": "110011", "พ": "110110",
    "ฟ": "110101", "ภ": "110111", "ม": "101101", "ย": "101111", "ร": "111010",
    "ล": "111000", "ว": "011101", "ศ": "111001", "ษ": "111011", "ส": "011100",
    "ห": "110010", "ฬ": "111011", "อ": "011011", "ฮ": "011111",

    # English Letters (A-Z)
    "A": "100000", "B": "110000", "C": "100100", "D": "100110", "E": "100010",
    "F": "110100", "G": "110110", "H": "110010", "I": "010100", "J": "010110",
    "K": "101000", "L": "111000", "M": "101100", "N": "101110", "O": "101010",
    "P": "111100", "Q": "111110", "R": "111010", "S": "011100", "T": "011110",
    "U": "101001", "V": "111001", "W": "010111", "X": "101101", "Y": "101111", "Z": "101011",

    # Numbers (0-9)
    "1": "100000", "2": "110000", "3": "100100", "4": "100110", "5": "100010",
    "6": "110100", "7": "110110", "8": "110010", "9": "010100", "0": "010110"
}

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

    try:
        result = ocr_service.recognize(image_bytes)
    except OCRInitializationError as error:
        logging.error("EasyOCR initialization failed")
        return _ocr_error("ocr_initialization_failed", str(error), 503)
    except OCRProcessingError as error:
        logging.error("EasyOCR inference failed")
        return _ocr_error("ocr_processing_failed", str(error), 500)

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

if __name__ == "__main__":
    print("=" * 60)
    print(" Starting Braille LED Controller Web Application...")
    print(f" Initializing Serial Connection on {DEFAULT_PORT}...")
    print("=" * 60)
    
    # Attempt initial connection
    init_serial(DEFAULT_PORT)
    
    print(f"\n Web Interface is running at: http://127.0.0.1:{PORT_WEB}\n")
    app.run(host="0.0.0.0", port=PORT_WEB, debug=False, use_reloader=False)
