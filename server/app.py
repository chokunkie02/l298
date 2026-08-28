import os
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

# กำหนดโฟลเดอร์สำหรับบันทึกรูปภาพที่ส่งมาจาก ESP32-CAM
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/", methods=["GET"])
def index():
    """Endpoint สำหรับตรวจสอบสถานะของ Server"""
    return jsonify({
        "status": "online",
        "message": "ESP32-CAM Image Server is running"
    }), 200


@app.route("/upload", methods=["POST"])
def upload_image():
    """Endpoint รับภาพ JPEG แบบ raw binary bytes จาก HTTP POST body"""
    # อ่านข้อมูล raw binary bytes จาก request body โดยตรง (ไม่ผ่าน multipart/form-data)
    image_bytes = request.get_data()

    if not image_bytes:
        print("[WARNING] Received empty request body")
        return jsonify({
            "success": False,
            "message": "No image data received"
        }), 400

    file_size = len(image_bytes)

    # ตั้งชื่อไฟล์อัตโนมัติด้วย Timestamp (ปีเดือนวัน_ชั่วโมงนาทีวินาที)
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
    filename = f"img_{timestamp_str}.jpg"
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    # บันทึกไฟล์ raw binary ลงโฟลเดอร์ uploads/
    with open(filepath, "wb") as f:
        f.write(image_bytes)

    # แสดง Log บน CMD
    print(f"[LOG] Received image: {filename} | Size: {file_size} bytes ({file_size / 1024:.2f} KB)")

    # ตอบกลับ JSON ให้ ESP32-CAM
    return jsonify({
        "success": True,
        "message": "image received",
        "filename": filename,
        "size": file_size
    }), 200


if __name__ == "__main__":
    print("=" * 60)
    print(" Starting ESP32-CAM Image Server...")
    print(f" Images will be saved to: {UPLOAD_FOLDER}")
    print(" Binding to: http://0.0.0.0:5000 (LAN accessible)")
    print("=" * 60)
    # Host 0.0.0.0 เพื่อให้ ESP32-CAM ในเครือข่าย Local Wi-Fi (Hotspot) เข้าถึงได้
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)
