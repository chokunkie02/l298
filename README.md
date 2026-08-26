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

## การเตรียมภาพก่อน OCR (Preprocessing)

ก่อนส่งภาพเข้า EasyOCR ระบบจะประมวลผลภาพผ่าน `image_preprocessing.py` ซึ่งแยก
ออกจาก Flask route และ `ocr_service.py` โดยเจตนา เพื่อให้ทดสอบและเปรียบเทียบ
แต่ละโหมดได้อิสระ (ดู `evaluate_ocr.py` ด้านล่าง) มี 4 โหมด:

| โหมด                | การทำงาน                                                                 |
|---------------------|---------------------------------------------------------------------------|
| `none`              | decode ภาพ + แก้ EXIF orientation เท่านั้น ไม่ทำอะไรเพิ่ม                    |
| `resize`            | แก้ EXIF orientation + ขยายภาพเล็กเกินไป/ย่อภาพใหญ่เกินไปอย่างปลอดภัย (รักษาสัดส่วนเสมอ) |
| `grayscale_clahe`   | เหมือน `resize` แล้วแปลง grayscale + ปรับ contrast ด้วย CLAHE                |
| `adaptive_threshold`| เหมือน `resize` แล้วแปลง grayscale + ทำ adaptive thresholding (ขาว-ดำ)       |

**ค่าเริ่มต้นของ production คือ `resize` เท่านั้น** (แก้ EXIF orientation +
resize อย่างปลอดภัย) **ยังไม่เปิดใช้ CLAHE หรือ adaptive thresholding เป็นค่า
เริ่มต้น** จนกว่าจะมีข้อมูลวัดผลจริงจาก `evaluate_ocr.py` ยืนยันว่าโหมดใดโหมด
หนึ่งช่วยลด CER ได้จริงเมื่อเทียบกับ ground truth ค่าคงที่ทั้งหมด (ขนาดสูงสุด/
ต่ำสุด, พารามิเตอร์ CLAHE, พารามิเตอร์ threshold) กำหนดไว้เป็นค่าคงที่ที่มีชื่อ
และปรับได้ในไฟล์เดียวกัน พร้อมลำดับการทำงานที่ระบุไว้ชัดเจนใน docstring ของ
โมดูล

ภาพที่มีจำนวนพิกเซลเกิน 40 ล้านพิกเซลจะถูกปฏิเสธก่อน decode จริง (ป้องกัน
decompression bomb) และภาพต้นฉบับที่อัปโหลดจะไม่ถูกเขียนทับหรือบันทึกถาวรเช่นเดิม

## คำเตือนคุณภาพภาพ (Image-Quality Warnings)

การตอบกลับของ `/api/ocr` มีฟิลด์ `image_quality` เพิ่มเข้ามา ประกอบด้วยขนาด
ภาพ ความสว่างเฉลี่ย contrast โดยประมาณ และ blur score (ความแปรปรวนของ
Laplacian) พร้อมรายการคำเตือน (`dark`, `bright`, `low_contrast`, `blurry`)

**ข้อจำกัดสำคัญ**: ค่าทั้งหมดเป็น heuristic ที่คำนวณจากสถิติพิกเซลง่าย ๆ
เท่านั้น **ไม่ใช่การรับประกันว่า OCR จะอ่านผิดหรือถูก** และ **ไม่ปิดกั้นการทำ
OCR หรือการยืนยันผลลัพธ์แต่อย่างใด** เกณฑ์ทั้งหมดปรับได้ผ่านค่าคงที่ใน
`image_preprocessing.py` (`DARK_MEAN_BRIGHTNESS_THRESHOLD` เป็นต้น) หน้าเว็บ
จะประกาศคำเตือนผ่านระบบ aria-live เดิม พร้อมกล่องคำเตือนแบบถาวรที่มีทั้งไอคอน
และข้อความ (ไม่ใช้สีเพียงอย่างเดียวสื่อความหมาย) และยังคงให้ฟัง/ยืนยัน/เลือกภาพ
ใหม่ได้ตามปกติเสมอ

## การประเมินความแม่นยำ OCR (Evaluation)

`evaluate_ocr.py` เป็นเครื่องมือ CLI สำหรับวัด Character Error Rate (CER) บน
ชุดภาพจริงในเครื่อง เทียบทุกโหมด preprocessing ก่อนตัดสินใจเปลี่ยนค่าเริ่มต้น
ของ production ดูรายละเอียดวิธีเตรียมชุดข้อมูลและรูปแบบ manifest ทั้งหมดที่
[`evaluation/README.md`](evaluation/README.md)

```bash
source .venv/bin/activate
python evaluate_ocr.py --manifest evaluation/manifest.csv
```

- **CER คือตัวชี้วัดหลัก โดยเฉพาะภาษาไทย** เพราะภาษาไทยไม่เว้นวรรคระหว่างคำ
  การวัด "ความแม่นยำระดับคำ" ด้วยการตัดคำด้วยช่องว่าง (whitespace-token error
  rate) จึงไม่มีความหมายเท่ากับภาษาอังกฤษ เครื่องมือนี้บันทึกค่าทั้งสองแบบแยก
  กันชัดเจน และไม่เรียก whitespace-token error rate ว่าเป็นความแม่นยำระดับคำ
  ไทยที่แท้จริง
- **mean_confidence ของ EasyOCR ไม่ใช่ตัวแทนของความแม่นยำ** ห้ามใช้เพียงค่านี้
  เลือกว่าโหมดใด "ดีกว่า" ต้องเทียบกับ ground truth ที่พิมพ์ไว้ล่วงหน้าเสมอ
- ชุดข้อมูลจริง (`evaluation/images/`, `evaluation/manifest.csv`) และผลลัพธ์
  (`evaluation/results/`) เป็นข้อมูลส่วนตัวในเครื่องของแต่ละคน **ถูกกันออกจาก
  Git ด้วย `.gitignore`** — track เฉพาะ `evaluation/README.md` และ
  `evaluation/manifest.example.csv` (แม่แบบเท่านั้น ไม่ใช่ข้อมูลจริง)
- ถ้ายังไม่มี `evaluation/manifest.csv` เครื่องมือจะหยุดทำงานพร้อมคำแนะนำ
  ขั้นตอนถัดไป แทนที่จะสร้างผลลัพธ์จำลองขึ้นมาเอง

## ทดสอบ

ชุดทดสอบใช้ Reader จำลอง จึงไม่ดาวน์โหลดโมเดล ไม่ใช้ GPU ไม่ใช้อินเทอร์เน็ต และไม่ทำ OCR จริง:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
node --check static/script.js
node --test "tests/js/**/*.test.js"
python -m compileall -q app.py ocr_service.py image_preprocessing.py ocr_evaluation.py evaluate_ocr.py tests
git diff --check
```

ชุดทดสอบ `tests/js/` ครอบคลุมพฤติกรรมการอ่านออกเสียง (TTS), ปุ่มยืนยัน, และ
คำเตือนคุณภาพภาพของขั้นตอน OCR โดยรัน `static/script.js` จริงในบริบท Node `vm`
พร้อม DOM และ `speechSynthesis` จำลอง (`tests/js/fake-dom.js`) ไม่ต้องติดตั้ง
แพ็กเกจ npm ใด ๆ เพิ่มเติม ส่วน `tests/test_image_preprocessing.py` และ
`tests/test_ocr_evaluation.py` ทดสอบ preprocessing, heuristic วัดคุณภาพภาพ,
CER/WER, และ CLI ประเมินผล ด้วยภาพเล็กที่สร้างในหน่วยความจำและ OCR reader
จำลอง ไม่ดาวน์โหลดโมเดลหรือเรียก inference จริงเช่นกัน
