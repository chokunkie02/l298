# Braille LED Controller และ OCR

แอป Flask นี้ควบคุม Braille LED ผ่าน ESP32 และมีขั้นตอน OCR ที่อ่านข้อความภาษาไทยและภาษาอังกฤษจากภาพด้วย EasyOCR ผล OCR จะถูกอ่านออกเสียงในเบราว์เซอร์และต้องได้รับการยืนยันจากผู้ใช้ แต่การยืนยันใน Step 2 เป็นสถานะภายในหน้าเว็บเท่านั้น ระบบจะไม่ส่งข้อความ OCR ไปยัง ESP32

## ติดตั้งและเริ่มแอป

ใช้ virtual environment ของโครงการเสมอ:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

จากนั้นเปิด `http://127.0.0.1:5050`

บน Windows ให้เปิด virtual environment ด้วย `.venv\Scripts\activate` ก่อนใช้คำสั่งติดตั้งและเริ่มแอป

## พฤติกรรมของโมเดล EasyOCR

- Reader ใช้ภาษา `th` และ `en` และทำงานด้วย CPU ตามค่าเริ่มต้น
- Reader ถูกสร้างแบบ lazy เมื่อมีคำขอ OCR ครั้งแรก และ Reader เดียวถูกใช้ร่วมกันตลอดอายุของโปรเซส Flask
- ระบบตั้ง `low_confidence` เมื่อค่าเฉลี่ยเลขคณิตของ confidence ต่ำกว่า `0.60` ค่านี้เป็นเพียงสัญญาณเตือน ไม่ใช่ค่ารับประกันความแม่นยำ
- การเรียก OCR ครั้งแรกอาจดาวน์โหลดไฟล์น้ำหนักโมเดลและอาจใช้เวลาหลายนาทีตามความเร็วเครือข่าย
- โดยปกติ EasyOCR เก็บโมเดลไว้ที่ `~/.EasyOCR/model` หากกำหนด `EASYOCR_MODULE_PATH` หรือ `MODULE_PATH` ตำแหน่งจะเปลี่ยนตามตัวแปรนั้น
- การประมวลผลด้วย CPU อาจใช้เวลาหลายวินาทีต่อภาพ
- หากการดาวน์โหลดหรือเริ่มโมเดลล้มเหลว API จะคืนข้อผิดพลาด JSON แบบมีโครงสร้าง แอปจะไม่หยุดทำงาน แต่ต้องเริ่มแอปใหม่ก่อนลอง initialization อีกครั้ง

รูปภาพอัปโหลดถูกอ่านในหน่วยความจำเท่านั้นและไม่ถูกบันทึกถาวร น้ำหนักโมเดล รูปอัปโหลด cache และ virtual environment ถูกกันออกจาก Git ด้วย `.gitignore`

## ทดสอบ

ชุดทดสอบใช้ Reader จำลอง จึงไม่ดาวน์โหลดโมเดล ไม่ใช้ GPU ไม่ใช้อินเทอร์เน็ต และไม่ทำ OCR จริง:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
node --check static/script.js
node --test "tests/js/**/*.test.js"
python -m compileall -q app.py ocr_service.py tests
git diff --check
```

ชุดทดสอบ `tests/js/` ครอบคลุมพฤติกรรมการอ่านออกเสียง (TTS) และปุ่มยืนยันของขั้นตอน OCR โดยรัน `static/script.js` จริงในบริบท Node `vm` พร้อม DOM และ `speechSynthesis` จำลอง (`tests/js/fake-dom.js`) ไม่ต้องติดตั้งแพ็กเกจ npm ใด ๆ เพิ่มเติม
