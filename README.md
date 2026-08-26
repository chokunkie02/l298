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

## ชุดข้อมูล OCR สังเคราะห์ (Synthetic Dataset, Step 3.5)

นอกจากชุดภาพถ่ายจริง (หัวข้อก่อนหน้า) โปรเจกต์นี้มี `generate_synthetic_ocr.py`
สำหรับสร้างภาพ OCR **สังเคราะห์** จากข้อความที่รู้ ground truth แน่นอน (render
ด้วยฟอนต์ที่คุณจัดหาเอง) แล้วจำลองสภาพกล้อง (มืด/สว่าง, มุมเอียง, perspective,
ถ่ายไกล, เบลอ, noise, JPEG artifact ฯลฯ) แบบ deterministic (ทำซ้ำได้แน่นอนด้วย
seed เดียวกัน) รายละเอียดเต็มอยู่ที่
[`evaluation/synthetic/README.md`](evaluation/synthetic/README.md)

**ข้อจำกัดสำคัญที่ต้องย้ำ**: ชุดข้อมูลสังเคราะห์นี้**ไม่ใช่ตัวแทนของภาพถ่ายจริง
และห้ามใช้แทนชุดภาพถ่ายจริงใน `evaluation/`** ใช้เพื่อทดสอบว่า pipeline
preprocessing/evaluation ทำงานถูกต้องเชิงกลไกเท่านั้น **ห้ามใช้ fine-tune โมเดล
ใด ๆ** และ **CER ของชุดสังเคราะห์กับ CER ของชุดภาพจริงต้องไม่ถูกนำมารวมเป็น
คะแนนเดียวกันเด็ดขาด** - ชุดภาพถ่ายจริงยังคงจำเป็นเสมอสำหรับตัดสินใจใด ๆ
เกี่ยวกับ production

ตัวอย่างคำสั่ง (ต้องระบุ `--font-dir` ของคุณเอง เครื่องมือนี้ไม่ดาวน์โหลดหรือ
ใช้ font ของระบบปฏิบัติการเป็นค่าเริ่มต้น):

```bash
source .venv/bin/activate
python generate_synthetic_ocr.py \
    --corpus evaluation/synthetic/corpus.example.csv \
    --font-dir /path/to/approved-fonts \
    --output evaluation/generated \
    --run-name baseline-seed-42 \
    --variants-per-text 5 \
    --seed 42

# ประเมินผลด้วยตัวประเมินเดิม (รายงานจะระบุว่าเป็นชุดข้อมูล synthetic อัตโนมัติ)
python evaluate_ocr.py \
    --manifest evaluation/generated/baseline-seed-42/manifest.csv \
    --output evaluation/results/baseline-seed-42.csv
```

- **seed เดียวกัน + corpus/font เดียวกัน → ได้ไฟล์ภาพและพารามิเตอร์ augmentation
  เหมือนเดิมทุกไบต์เสมอ** seed ต่างกันให้ผล augmentation ต่างกัน
- ภาพทุกใบจากข้อความต้นทางเดียวกัน (ต่างฟอนต์/variant) มี `group_id` เดียวกัน
  เสมอ - เมื่อแบ่ง `--splits` จะแบ่งตาม `group_id` เท่านั้น (กัน data leakage
  ระหว่าง train/val/test) และเครื่องมือจะ raise error ทันทีถ้าตรวจพบ leakage
- `evaluate_ocr.py` จะ**ปฏิเสธไม่ทำงาน**ทันทีถ้า manifest มีทั้งแถวสังเคราะห์และ
  แถวภาพจริงปนกัน เพื่อไม่ให้คำนวณ CER รวมที่ตีความผิด
- ภาพที่ generate, manifest จริง, และผลประเมินไม่ถูก commit เข้า Git (ถูกกันด้วย
  `.gitignore`) - track เฉพาะ `evaluation/synthetic/README.md` และ
  `evaluation/synthetic/corpus.example.csv` (แม่แบบเท่านั้น)
- ผู้ใช้ต้องตรวจสอบ license ของฟอนต์เองและตรวจสอบด้วยสายตาว่าฟอนต์แสดงสระ/
  วรรณยุกต์ไทยถูกต้อง (การตรวจ coverage ของเครื่องมือเป็นเพียง heuristic)

## ทดสอบ

ชุดทดสอบใช้ Reader จำลอง จึงไม่ดาวน์โหลดโมเดล ไม่ใช้ GPU ไม่ใช้อินเทอร์เน็ต และไม่ทำ OCR จริง:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
node --check static/script.js
node --test "tests/js/**/*.test.js"
python -m compileall -q app.py ocr_service.py image_preprocessing.py ocr_evaluation.py evaluate_ocr.py synthetic_dataset.py generate_synthetic_ocr.py tests
git diff --check
```

ชุดทดสอบ `tests/js/` ครอบคลุมพฤติกรรมการอ่านออกเสียง (TTS), ปุ่มยืนยัน, และ
คำเตือนคุณภาพภาพของขั้นตอน OCR โดยรัน `static/script.js` จริงในบริบท Node `vm`
พร้อม DOM และ `speechSynthesis` จำลอง (`tests/js/fake-dom.js`) ไม่ต้องติดตั้ง
แพ็กเกจ npm ใด ๆ เพิ่มเติม ส่วน `tests/test_image_preprocessing.py` และ
`tests/test_ocr_evaluation.py` ทดสอบ preprocessing, heuristic วัดคุณภาพภาพ,
CER/WER, dataset labeling (synthetic/real_camera), และ CLI ประเมินผล ด้วยภาพ
เล็กที่สร้างในหน่วยความจำและ OCR reader จำลอง ส่วน `tests/test_synthetic_dataset.py`
ทดสอบตัวสร้างชุดข้อมูลสังเคราะห์ (Step 3.5): การ render, augmentation แบบ
deterministic, การป้องกัน data leakage ระหว่าง split, และความเข้ากันได้ของ
manifest กับ `evaluate_ocr.py` เดิม ใช้ font ที่ฝังอยู่ใน Pillow เองสำหรับกลไก
ทั่วไป และค้นหา font ไทยที่มีอยู่แล้วในเครื่อง (ข้ามอย่างชัดเจนถ้าไม่พบ) สำหรับ
เทสต์ที่ต้องตรวจสอบสระ/วรรณยุกต์ไทยจริง ไม่ดาวน์โหลด font, โมเดล OCR, หรือ
dataset ใด ๆ ระหว่างรันเทสต์ทั้งหมด
