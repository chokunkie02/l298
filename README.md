# 🚀 คู่มือการใช้งานและรายงานการพัฒนาระบบ ESP32-CAM + COE.PSU Image Capture Server

> **สำหรับผู้พัฒนาที่มาทำต่อ:** อ่านส่วน **"⚡ Quick Start (เสียบสาย เปิดเซิร์ฟ เทสได้ทันทีใน 3 ขั้นตอน)"** ด้านล่างเพื่อเริ่มทดสอบระบบได้ทันทีครับ!

---

## 📌 1. ภาพรวมระบบ (System Architecture)

ระบบประกอบด้วย 3 ส่วนหลักที่สื่อสารกันผ่านเครือข่าย Local Wi-Fi Hotspot (`Chokun02`):

```text
             ┌──────────────────┐
             │    COE.PSU       │
             │                  │
             │ S1 S2 S3 S4 S5   │
             └────────┬─────────┘
                      │
                      │ อ่านค่า ADC (GPIO36)
                      ↓
             ┌──────────────────┐
             │      ESP32       │
             │ Button Manager   │
             └────────┬─────────┘
                      │
                 HTTP GET /capture (Port 8080)
                      │
                      ↓
             ┌──────────────────┐
             │   ESP32-CAM      │
             │ (AI Thinker)     │
             └────────┬─────────┘
                      │
                Camera Capture (เคลียร์ Buffer เก่า)
                      │
                      ↓
              Raw JPEG Binary Bytes
                      │
                HTTP POST /upload (Port 5001)
                      │
                      ↓
             ┌──────────────────┐
             │  Computer Server │
             │  (Python Flask)  │
             └────────┬─────────┘
                      │
           บันทึกไฟล์ภาพ .jpg อัตโนมัติลงใน
             server/uploads/img_YYYYMMDD_HHMMSS.jpg
```

1. **บอร์ด COE.PSU (ESP32)**: อ่านค่าปุ่มกด S1-S5 ผ่านวงจร Resistor Ladder (ADC) บน GPIO36 เมื่อกด S1 จะส่งคำสั่ง HTTP GET `/capture` ไปยัง ESP32-CAM (Port 8080)
2. **ESP32-CAM (AI Thinker)**: เปิด WebServer Port 80 (หน้าเว็บดูภาพ) และ Port 8080 (Command Server `/capture`) เมื่อรับคำสั่ง จะทำการทิ้ง Frame Buffer เก่า ถ่ายภาพ JPEG ใหม่ แล้วยิง HTTP POST แบบ Raw Binary Bytes ไปที่ Python Server บนคอมพิวเตอร์
3. **Python Flask Server (คอมพิวเตอร์)**: รันที่พอร์ต **5001** (`0.0.0.0:5001`) รับภาพ JPEG บันทึกลงโฟลเดอร์ `server/uploads/` และตอบกลับ JSON สรุปผล

---

## ⚡ Quick Start: สำหรับผู้พัฒนาที่มาทำต่อ (เสียบสาย เปิดเซิร์ฟ เทสได้เลย!)

### 🔹 ขั้นตอนที่ 1: การเปิด Wi-Fi Hotspot และตรวจสอบ IP
1. เปิด **Wi-Fi Hotspot บนมือถือ**:
   * **SSID:** `Chokun02`
   * **Password:** `chokun02`
2. นำ **คอมพิวเตอร์** เชื่อมต่อ Wi-Fi Hotspot `Chokun02`
3. เปิด CMD บนคอมพิวเตอร์ พิมพ์ `ipconfig` เพื่อดู IPv4 Address ของเครื่องคอมพิวเตอร์ (เช่น `172.29.241.183`)

---

### 🔹 ขั้นตอนที่ 2: สั่งรัน Python Flask Server (คอมพิวเตอร์)
เปิด Windows CMD แล้วพิมพ์คำสั่ง:
```cmd
cd C:\Users\kt856\Downloads\jumpb\server
python app.py
```
* **พอร์ตใช้งาน:** `http://0.0.0.0:5001`
* **โฟลเดอร์เก็บบันทึกรูป:** `C:\Users\kt856\Downloads\jumpb\server\uploads\`

---

### 🔹 ขั้นตอนที่ 3: แฟลชโค้ดเข้า ESP32-CAM (Arduino IDE)
1. เปิดไฟล์ซอร์สโค้ด:
   📁 [`server/CameraWebServer/CameraWebServer.ino`](file:///c:/Users/kt856/Downloads/jumpb/server/CameraWebServer/CameraWebServer.ino)
2. ตรวจสอบการตั้งค่าใน Arduino IDE:
   * **Board:** `ESP32 Wrover Module`
   * **Partition Scheme:** `Huge APP (3MB No OTA/1MB SPIFFS)`
   * **PSRAM:** `Enabled`
3. ตรวจสอบตัวแปร IP ในไฟล์ `CameraWebServer.ino` (บรรทัดที่ 18) ให้ตรงกับ IP คอมพิวเตอร์ของคุณ:
   ```cpp
   const char *flaskServerUrl = "http://172.29.241.183:5001/upload";
   ```
4. ต่อสาย **IO0 เข้ากับ GND** -> กด **Upload** -> เมื่อเสร็จ ถอดสาย IO0 ออกจาก GND -> กดปุ่ม **RESET**

---

### 🧪 ขั้นตอนการทดสอบรวดเร็ว (3 วิธี)

#### **วิธีที่ A: กดปุ่ม S1 บนบอร์ด COE.PSU (ใช้งานจริง)**
1. กดปุ่ม **S1** ที่บอร์ด COE.PSU
2. สังเกต Serial Monitor ของ ESP32-CAM จะขึ้นข้อความ:
   `[SUCCESS] Photo sent to Flask Server successfully!`
3. ตรวจสอบไฟล์รูปภาพใหม่ที่โผล่ขึ้นมาในโฟลเดอร์ `server/uploads/`

#### **วิธีที่ B: สั่งถ่ายภาพผ่าน Web Browser / cURL (ไม่ต้องใช้ COE.PSU)**
เปิด CMD แล้วพิมพ์คำสั่งสั่งให้ ESP32-CAM ถ่ายภาพทันที:
```cmd
curl.exe http://172.29.241.201:8080/capture
```

#### **วิธีที่ C: ทดสอบส่งภาพเข้า Server โดยตรง (ไม่ต้องใช้กล้อง)**
```cmd
curl.exe -X POST --data-binary "test bytes" -H "Content-Type: image/jpeg" http://172.29.241.183:5001/upload
```

---

## 📖 รายงานทางเทคนิคและการแก้ปัญหา (Technical Reference)

### 📊 1. ตารางค่า ADC ของปุ่มกด S1-S5 (บอร์ด COE.PSU)
ปุ่มกดต่อกับวงจร Resistor Ladder อ่านค่าผ่าน ADC (GPIO36):

| ปุ่ม | ค่า ADC Raw (ประมาณ) | ช่วง Threshold แนะนำ |
| :--- | :---: | :---: |
| **S1** | **3900** | 3500 – 4095 |
| **S2** | **3200** | 2900 – 3499 |
| **S3** | **2600** | 2250 – 2899 |
| **S4** | **1900** | 1500 – 2249 |
| **S5** | **1100** | 700 – 1499 |

---

### 🛠️ 2. สรุปปัญหาทางเทคนิคที่พบและแนวทางแก้ไข (Troubleshooting Matrix)

| ปัญหาที่พบ | สาเหตุ | วิธีแก้ไข |
| :--- | :--- | :--- |
| `include nested depth 200` | `#include "board_config.h"` เรียกตัวเองซ้ำ | ลบ include ซ้ำออกจาก `board_config.h` ให้ include เฉพาะ `camera_pins.h` |
| `cam_hal: FB-OVF` | ใช้ Resolution สูงเกินไปจน RAM ล้น | ปรับเป็น `FRAMESIZE_QVGA` (320x240) หรือ `FRAMESIZE_VGA` พร้อมเปิด PSRAM |
| กดถ่ายครั้งที่ 2 ได้ภาพแรก (ภาพดีเลย์) | มี Frame Buffer เก่าค้างในกล้อง | เพิ่มลูปวนคืน Frame Buffer เก่า 2 รอบก่อนดึงภาพถ่ายใหม่ (`esp_camera_fb_get()` + `esp_camera_fb_return()`) |
| ภาพถ่ายกลับหัว | ทิศทางการติดกล้อง | ตั้งค่า `s->set_vflip(s, 1)` ในโค้ด |
| ติดต่อ Server ไม่ติด (404/Timeout) | 1. IP คอมกับ ESP32 อยู่คนละ Subnet<br>2. พอร์ต 5000 ชนกับโปรเซสระบบ | 1. ให้คอมเกาะ Hotspot `Chokun02` เหมือน ESP32<br>2. เปลี่ยนพอร์ตเป็น `5001` |
| Upload ค้าง `Connecting.....` | บอร์ดไม่เข้าโหมด Download | ต่อสาย IO0 เข้า GND ก่อนกด Upload และถอดออกเมื่อ Upload เสร็จ |

---

## 📂 โครงสร้างโฟลเดอร์โปรเจกต์ (Directory Structure)

```text
jumpb/
├── README.md                              # เอกสารคู่มือและการพัฒนาระบบฉบับสมบูรณ์
├── server/
│   ├── app.py                             # Python Flask HTTP Server (Port 5001)
│   ├── requirements.txt                   # รายการ Dependency (flask)
│   ├── uploads/                           # โฟลเดอร์เก็บบันทึกไฟล์รูปภาพ JPEG
│   └── CameraWebServer/
│       └── CameraWebServer.ino            # ซอร์สโค้ด Arduino สำหรับ ESP32-CAM
└── (ไฟล์โค้ดสำหรับระบบ Braille Translator)
```
