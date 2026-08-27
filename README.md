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

## การแปลข้อความเป็นอักษรเบรลล์ 6 จุด (Text-to-Braille, Step 4)

หลังผู้ใช้กดยืนยันข้อความ OCR แล้ว ระบบจะแปลงข้อความนั้นเป็น**ลำดับเซลล์อักษร
เบรลล์ 6 จุดแบบมีโครงสร้าง** (ยังไม่ส่งไปยัง ESP32 ในขั้นตอนนี้) สถาปัตยกรรม
แยกเป็น 3 ชั้น:

| ไฟล์                        | หน้าที่                                                              |
|-----------------------------|------------------------------------------------------------------------|
| `braille_models.py`         | โมเดลข้อมูล (BrailleCell, BrailleTranslation, TranslationDiagnostic) และการแปลง Unicode Braille <-> bitmask - ไม่ยุ่งกับ Flask/Liblouis เลย |
| `braille_translation.py`    | normalize ข้อความ, แบ่งบรรทัด, orchestration (`translate_text`), interface `BrailleTranslatorBackend`, `FakeBrailleTranslator` (ใช้ในเทสต์) |
| `liblouis_translator.py`    | adapter เชื่อมต่อ Liblouis จริง (Python binding หรือ CLI) |

**ทำไมหนึ่งตัวอักษรอาจกลายเป็นหลายเซลล์**: อักษรเบรลล์ไม่ได้แปลแบบตัวต่อตัว 1:1
เสมอไป เช่น ตัวพิมพ์ใหญ่ภาษาอังกฤษต้องมี "capital sign" นำหน้า, ตัวเลขต้องมี
"number sign" นำหน้า, และเครื่องหมายวรรคตอน/สระบางตัวอาจใช้มากกว่าหนึ่งเซลล์
โค้ดทั้งหมดจึง**ไม่สมมติว่าจำนวนเซลล์ผลลัพธ์เท่ากับจำนวนตัวอักษรอินพุต** เพียง
ตีความผลลัพธ์ดิบจาก Liblouis ทีละเซลล์เท่านั้น

### ลำดับบิต (Dot-to-Bit Ordering)

`bit 0` = dot 1, `bit 1` = dot 2, ... `bit 5` = dot 6 (bitmask เป็นจำนวนเต็ม
0-63) `bit_pattern` เป็นสตริง 6 ตัวอักษรเรียงตาม dot 1,2,3,4,5,6 - **ตรงกับ
รูปแบบที่ endpoint `/send` เดิมและคีย์บอร์ดทดสอบฮาร์ดแวร์ใน static/script.js
ใช้อยู่แล้วทุกประการ** เซลล์ว่าง (U+2800) คือ bitmask 0 / pattern "000000" และ
เป็นเซลล์จริงที่มีความหมาย (เช่นช่องว่างระหว่างคำ) ไม่ใช่ตัวเติมช่องว่างของ
เฟรมใด ๆ (แนวคิดเรื่อง frame padding ยังไม่มีใน Step 4)

### Liblouis (system dependency)

**Liblouis ไม่ใช่ Python package ที่ `pip install` แล้วใช้งานได้ทันที** ต้อง
ติดตั้งไลบรารีระดับระบบก่อน โปรเจกต์นี้**ไม่ติดตั้งให้อัตโนมัติ**และ**ไม่รัน
Homebrew หรือคำสั่งติดตั้งระบบใด ๆ เอง** - คุณต้องติดตั้งเองตามความเหมาะสมกับ
เครื่องของคุณ ตัวอย่างบน macOS (Homebrew):

```bash
# รันเองเมื่อพร้อม - เครื่องมือนี้จะไม่รันคำสั่งนี้ให้อัตโนมัติ
brew install liblouis
pip install louis   # Python binding อย่างเป็นทางการของ Liblouis (ไม่ใช่ package อื่นที่ชื่อคล้ายกัน)
```

บน Linux ส่วนใหญ่ใช้ `apt install liblouis-bin python3-louis` (Debian/Ubuntu)
หรือเทียบเท่าใน distro ของคุณ - โปรดตรวจสอบชื่อแพ็กเกจที่ถูกต้องสำหรับระบบของ
คุณเอง

**ตารางไทยที่ต้องใช้**: `th-g1.utb` (ค่าคงที่ `DEFAULT_THAI_TABLE` ใน
`liblouis_translator.py`)

**การเลือก adapter**: ระบบตรวจสภาพแวดล้อมและเลือก Python binding (`import
louis`) ก่อนเสมอถ้ามี (ทำงานในโพรเซสเดียวกัน ไม่มี subprocess ปลอดภัยกว่าและ
เร็วกว่า) และใช้คำสั่ง `lou_translate` (CLI) เป็นทางเลือกสำรองเมื่อไม่มี Python
binding แต่มี Liblouis ระดับระบบ ถ้าไม่พบทั้งสองแบบ API จะคืน error แบบมี
โครงสร้าง (`translator_unavailable`) **ไม่มีการ fallback ไปยัง legacy
dictionary โดยอัตโนมัติเด็ดขาด**

**คำสั่ง CLI ที่ adapter เรียกจริง**: `lou_translate -d unicode.dis <table>`
(ข้อความเข้าทาง stdin) - **ต้องระบุ `-d unicode.dis` เสมอ** ยืนยันแล้วกับ
Liblouis 3.38.0 (Homebrew) ว่าถ้าไม่ระบุ display table, `lou_translate` จะคืน
ข้อความเดิมกลับมาเฉย ๆ (ไม่ใช่ Unicode Braille) ทำให้ทั้งข้อความถูกตีความเป็น
`non_braille_output` ทุกตัวอักษร (`lou_translate --help` เองก็แนะนำให้ระบุ
display table เสมอเพื่อความชัดเจนและแน่นอนของผลลัพธ์) ตัวอย่างที่ยืนยันแล้วจริง
บนเครื่องที่พัฒนา (**แสดงเพื่อยืนยันว่าการเชื่อมต่อ/encoding ทำงานถูกต้อง
เท่านั้น ไม่ใช่การยืนยันความถูกต้องทางภาษาศาสตร์**):

```bash
$ echo "hello" | lou_translate -d unicode.dis th-g1.utb
⠓⠑⠇⠇⠕
```

**วิธีตรวจสอบเวอร์ชันและตารางที่ติดตั้ง**:

```bash
python3 -c "import louis; print(louis.version())"   # ถ้าติดตั้ง Python binding
lou_translate --version
lou_checktable th-g1.utb && echo "ตารางใช้งานได้"
echo "hello" | lou_translate -d unicode.dis th-g1.utb   # ต้องได้ Unicode Braille กลับมา ไม่ใช่ "hello" เฉย ๆ
```

หรือรัน integration test ที่แนบมา (ข้ามอัตโนมัติถ้าไม่มี Liblouis):

```bash
python -m unittest tests.test_liblouis_integration -v
```

### API: `POST /api/braille/translate`

```json
// Request
{ "text": "ข้อความที่ยืนยันแล้ว" }

// Response (สำเร็จ) - รูปแบบตัวอย่างเท่านั้น ไม่ใช่ผลแปลภาษาไทยจริง
{
  "ok": true,
  "source_text": "...",
  "normalized_text": "...",
  "cells": [
    { "index": 0, "unicode_braille": "⠿", "dot_numbers": [1,2,3,4,5,6], "bitmask": 63, "bit_pattern": "111111" }
  ],
  "line_boundaries": [],
  "cell_count": 1,
  "diagnostics": [],
  "engine": "liblouis-python",
  "engine_version": "3.29.0",
  "table": "th-g1.utb",
  "changed_by_normalization": false,
  "sent_to_hardware": false
}
```

`sent_to_hardware` เป็น `false` เสมอใน Step 4 - endpoint นี้ไม่เรียก Serial/
ESP32 ไม่ว่ากรณีใด error ที่เป็นไปได้: `missing_text`, `invalid_text_type`,
`empty_text`, `text_too_long`, `translator_unavailable`, `table_unavailable`,
`translation_timeout`, `invalid_translator_output`, `translation_failed` -
ทุก error คืนเป็น JSON แบบมีโครงสร้างเสมอ ไม่มี stack trace หรือ shell output
ดิบหลุดไปถึง browser

### พจนานุกรมเดิม (Legacy Dictionary) - คำเตือน

โปรเจกต์นี้มีพจนานุกรม hardcode ตัวอักษร -> รูปแบบจุด 6 บิตอยู่เดิม (ย้ายไปที่
`legacy_braille_dictionary.py` แล้ว ค่าเดิมทุกประการ) **ยังไม่ผ่านการตรวจสอบ
ความถูกต้องเทียบกับมาตรฐานอักษรเบรลล์ไทยใด ๆ** และ**ไม่ถูกใช้โดยเส้นทางแปล OCR
-> เบรลล์เลย** endpoint `/api/braille_dictionary` และคีย์บอร์ดทดสอบฮาร์ดแวร์
เดิมใน static/script.js ยังคงใช้พจนานุกรมนี้ต่อไปสำหรับการทดสอบฮาร์ดแวร์ด้วยมือ
เท่านั้น (ไม่เกี่ยวกับ OCR) มีคลาส `LegacyDictionaryTranslator` สำหรับพัฒนา/
ทดลองเท่านั้น ต้องเปิดใช้งานด้วย `enabled=True` อย่างชัดเจน ห้ามใช้ใน
production ดูรายละเอียดความแตกต่างระหว่างพจนานุกรม frontend/backend ที่ยืนยัน
แล้วใน `tests/test_legacy_braille_dictionary.py`

### สิ่งที่ยังไม่ทำใน Step 4 (โดยตั้งใจ)

- **ไม่ส่งข้อมูลไปยัง Serial/ESP32** - `sent_to_hardware` เป็น `false` เสมอ
- **ไม่มี playback อัตโนมัติ** (เล่นเซลล์ทีละอันอัตโนมัติ) - เก็บไว้ทำใน Step 5
- **ไม่มี frame padding** - เซลล์ว่างทั้งหมดที่เห็นมาจากผลแปลจริงเท่านั้น
- **ความถูกต้องทางภาษาศาสตร์ของอักษรเบรลล์ไทยที่ได้ยังไม่ผ่านการตรวจสอบโดย
  ผู้เชี่ยวชาญ/ผู้อ่านเบรลล์ไทย** - CLI adapter (`LiblouisSubprocessAdapter`)
  ได้ทดสอบกับ Liblouis 3.38.0 จริงแล้ว (ยืนยันว่าเชื่อมต่อได้และได้ Unicode
  Braille ที่ถูกต้องเชิงโครงสร้าง หลังแก้ไขให้ระบุ `-d unicode.dis` เสมอ - ดู
  หัวข้อ Liblouis ด้านบน) **แต่นี่ยืนยันแค่ว่าการเชื่อมต่อและ encoding ถูกต้อง
  เท่านั้น ไม่ใช่หลักฐานความถูกต้องทางภาษาศาสตร์ของอักษรเบรลล์ไทยที่ได้แต่อย่าง
  ใด** ยังต้องให้ผู้เชี่ยวชาญ/ผู้อ่านเบรลล์ไทยที่มีคุณสมบัติตรวจสอบเทียบกับคู่มือ
  อักษรเบรลล์ไทยก่อนใช้งานจริงเสมอ ส่วน Python binding adapter
  (`LiblouisPythonAdapter`) ยังไม่เคยถูกทดสอบกับ binding จริงเลย (เครื่องที่ใช้
  พัฒนา/ทดสอบติดตั้งเฉพาะ CLI ผ่าน Homebrew เท่านั้น)

## การเล่นลำดับอักษรเบรลล์แบบจำลอง (Single-Cell Playback, Step 5)

หลังแปลข้อความเป็นอักษรเบรลล์สำเร็จ (Step 4) ผู้ใช้สามารถเล่นลำดับเซลล์ผ่าน
จอแสดงผลจุด 6 จุดแบบ**จำลองบนหน้าจอเท่านั้น** ได้ ทั้งแบบเลื่อนด้วยมือและเล่น
อัตโนมัติ **Step 5 นี้ไม่ส่งข้อมูลไปยัง Serial/ESP32 เลยไม่ว่ากรณีใด**

### สถาปัตยกรรม

`static/braille_playback.js` เป็น state machine บริสุทธิ์ล้วน แยกจาก Flask,
OCR, Liblouis, Serial, ESP32, และ network request ใด ๆ โดยสิ้นเชิง - ไม่รู้จัก
แม้แต่ DOM รับ timer function (`setTimeout`/`clearTimeout`) แบบ inject เข้ามา
เสมอ เพื่อให้เทสต์ควบคุมเวลาได้แบบ deterministic (ดู
`tests/js/braille_playback.test.js` ซึ่งไม่รอเวลาจริงเลยแม้แต่มิลลิวินาทีเดียว)
ไฟล์ `static/script.js` มีหน้าที่แค่เชื่อม callback ของ controller เข้ากับ DOM/
aria-live เท่านั้น

**สถานะ (state) ของ playback**: `empty` (ยังไม่มีลำดับ) → `ready` (โหลดแล้ว
ยังไม่เล่น อยู่ที่เซลล์แรก) → `playing_cell`/`playing_gap` (กำลังเล่นอัตโนมัติ)
→ `paused` (หยุดชั่วคราว เก็บตำแหน่งไว้) หรือ `completed` (เล่นครบ) หรือ
`stopped` (หยุดเล่น เคลียร์จอจำลอง) การเปลี่ยนสถานะทั้งหมดชัดเจนและทดสอบได้
(ดู `BRAILLE_PLAYBACK_STATES` ใน `static/braille_playback.js`)

### การควบคุมด้วยมือและอัตโนมัติ

- **แปลสำเร็จ = โหลดลำดับเข้า controller ทันที แต่ไม่เริ่มเล่นอัตโนมัติ**
  ตำแหน่งเริ่มต้นคือเซลล์แรกเสมอ ผู้ใช้ต้องกด "เริ่มเล่น" เอง
- **เริ่มเล่น**: หยุดเสียงพูดที่กำลังทำงานอยู่ก่อนเสมอ แล้วเล่นจากตำแหน่ง
  ปัจจุบัน กดซ้ำระหว่างเล่นอยู่แล้วไม่สร้าง timer ซ้อนกัน
- **หยุดชั่วคราว / เล่นต่อ**: เก็บตำแหน่งปัจจุบันไว้ กดเล่นต่อได้ปลอดภัย
- **ก่อนหน้า / ถัดไป**: เลื่อนทีละ 1 เซลล์จริงเสมอ (ไม่ข้าม ไม่วนกลับ) และ
  **หยุดการเล่นอัตโนมัติที่กำลังทำงานอยู่ก่อนเสมอ**
- **เริ่มใหม่**: กลับไปเซลล์แรก ไม่เล่นอัตโนมัติ (ต้องกดเริ่มเล่นเอง เหมือน
  ตอนแปลสำเร็จครั้งแรก)
- **หยุด**: ยกเลิก timer ที่ค้างอยู่ทั้งหมด เคลียร์จอแสดงผลจำลอง (ไม่ย้อน
  ตำแหน่งกลับไปเซลล์แรก - ต่างจาก "เริ่มใหม่")
- เริ่ม OCR ภาพใหม่ หรือแปลใหม่ (รวมถึงกด "ลองแปลงใหม่") จะล้างลำดับเก่าและ
  ยกเลิก timer เก่าทั้งหมดทันทีเสมอ

### เซลล์ว่างจริง vs ช่องว่างชั่วคราวระหว่างเซลล์

**เซลล์ว่างจริง** (bitmask 0, pattern `"000000"`, U+2800) เป็นเซลล์หนึ่งใน
ลำดับที่มี index และระยะเวลาแสดงผลของตัวเอง เช่น ช่องว่างระหว่างคำในข้อความจริง
- นับรวมใน cell_count เสมอ ประกาศว่า "เซลล์ N จาก M เป็นช่องว่าง" (ไม่ใช่
"เซลล์ N จาก M จุด" เพราะไม่มีจุดเปิด)

**ช่องว่างชั่วคราวระหว่างเซลล์** (inter-cell gap) เป็นเพียงจังหวะเว้นระหว่าง
การแสดงเซลล์สองเซลล์ที่ต่อเนื่องกันระหว่างเล่นอัตโนมัติเท่านั้น **ไม่นับเป็น
เซลล์ ไม่มี index ของตัวเอง ไม่เปลี่ยน cell_count และไม่ถูก serialize เป็น
ข้อมูลที่แปลแล้วใด ๆ** - แค่เคลียร์จอจำลองชั่วคราวแล้วแสดงเซลล์ถัดไปเมื่อครบ
กำหนดเวลา สองสิ่งนี้ต้องไม่สับสนกันทั้งในโค้ดและคำประกาศเชิง accessibility

### line boundaries (การขึ้นบรรทัดใหม่)

ใช้ metadata `line_boundaries` จาก API แปลเบรลล์ตรง ๆ **ไม่มีการสร้างรูปแบบ
จุดสำหรับ newline เอง และไม่นับ newline เป็นเซลล์** รองรับช่วงหยุดเพิ่มเติมที่
ปรับได้เมื่อขึ้นบรรทัดใหม่ (แยกจากช่วงว่างระหว่างเซลล์ปกติ) และประกาศ "ขึ้น
บรรทัดที่ N" ผ่าน aria-live ทุกครั้งที่ขึ้นบรรทัดใหม่ ไม่ว่าจะเล่นอัตโนมัติหรือ
เลื่อนด้วยมือ บรรทัดว่าง (ไม่มีเซลล์เลย) ไม่ทำให้ระบบขัดข้อง แค่ไม่มีเซลล์ให้
แสดงในบรรทัดนั้น

### การเข้าถึง (Accessibility)

- ปุ่มควบคุมทั้งหมดเป็น `<button>`/`<input>` จริง มี label ภาษาไทยชัดเจน ไม่พึ่ง
  ไอคอน สี หรือตำแหน่งเพียงอย่างเดียว
- ตัวบ่งชี้โฟกัสที่มองเห็นได้ใช้กฎ CSS `:focus-visible` เดิมของหน้าเว็บ (ใช้
  ร่วมกับทุกปุ่ม/input ในหน้าโดยอัตโนมัติ)
- ข้อความ "เซลล์ปัจจุบัน" (`#brailleCurrentCellInfo`) อัปเดตทุกครั้งที่เซลล์
  เปลี่ยนแต่**ไม่ใช่ aria-live** - โปรแกรมอ่านหน้าจอเข้าถึงได้ตลอดเวลาโดยไม่ถูก
  ขัดจังหวะ ส่วนการประกาศแบบ live (`#braillePlaybackAnnouncer`,
  `aria-live="polite"`) ใช้เฉพาะเหตุการณ์สำคัญ: การนำทางด้วยมือ, เริ่ม/เริ่มใหม่
  การเล่น, เปลี่ยนสถานะ (หยุดชั่วคราว/หยุดเล่น), ขึ้นบรรทัดใหม่, และเล่นครบ -
  **ไม่ประกาศทุกเซลล์ระหว่างเล่นอัตโนมัติ** เพื่อไม่ให้โปรแกรมอ่านหน้าจอถูกถล่ม
  ด้วยข้อความขณะเล่นเร็ว
- ย้าย focus ไปที่ปุ่ม "เริ่มเล่น" ทันทีหลังแปลสำเร็จ
- ปุ่มที่กดแล้วไม่มีผล (เช่น "เริ่มเล่น" ขณะเล่นครบแล้ว, "หยุดชั่วคราว" ขณะไม่ได้
  เล่นอยู่) ถูกปิดใช้งานเสมอ พร้อม `disabled` และ `aria-disabled` ที่ตรงกัน
- Animation/transition ของจุดเบรลล์ใช้กฎ `prefers-reduced-motion: reduce`
  เดิมของหน้าเว็บ (ลด transition ทั้งหมดเหลือ 0.01ms โดยอัตโนมัติ)
- ไม่มีการเพิ่ม keyboard shortcut ระดับ global ใด ๆ ที่อาจรบกวนโปรแกรมอ่าน
  หน้าจอหรือการนำทางปกติของเบราว์เซอร์

### จอแสดงผลจำลอง (Simulated Preview)

ใช้จอแสดงผลจุด 6 จุดเดิม (Braille 6-Dot Matrix Preview) ที่มีอยู่แล้วในหน้าเว็บ
ซ้ำ - **`updateVisualPreview()` เป็นฟังก์ชันบริสุทธิ์ (แค่ toggle CSS class)
ไม่เคยเรียก `/send` เลย** จึงนำมาใช้กับการเล่นเบรลล์ได้อย่างปลอดภัยโดยตรง โดย
**ไม่ผ่าน** `setPattern()` (ซึ่งจะไปแก้ค่าในช่องกรอก binary/การแสดงผลของการ
ควบคุมด้วยมือ) เพื่อรักษาพฤติกรรมการทดสอบฮาร์ดแวร์ด้วยมือเดิมให้แยกจากกันอย่าง
สมบูรณ์ มีป้ายกำกับ "กำลังแสดงเซลล์จากการเล่นอักษรเบรลล์ (จำลอง ไม่ส่งไปยัง
ESP32)" ปรากฏขึ้นข้าง ๆ preview เมื่อกำลังเล่น และมีข้อความเตือนซ้ำอีกครั้งใน
ส่วนควบคุมการเล่นเองว่า**ยังไม่ได้ส่งข้อมูลไปยัง ESP32 หรือฮาร์ดแวร์จริงแต่อย่าง
ใด** ต้องกดปุ่ม "Send to ESP32" ของการควบคุมด้วยมือเองเท่านั้นจึงจะส่งข้อมูลจริง

### ค่าเวลาเริ่มต้น (ปรับได้)

| การตั้งค่า                          | ช่วงที่ปลอดภัย | ค่าเริ่มต้นของต้นแบบ |
|--------------------------------------|-----------------|------------------------|
| ระยะเวลาแสดงแต่ละเซลล์ (cellDurationMs) | 300–5000 ms     | 900 ms                 |
| ช่วงว่างระหว่างเซลล์ (gapMs)           | 0–2000 ms       | 150 ms                 |
| ช่วงหยุดเมื่อขึ้นบรรทัดใหม่ (linePauseMs) | 0–5000 ms       | 700 ms                 |

ค่าเริ่มต้นเป็นการเลือกสำหรับต้นแบบ (prototype) เท่านั้น ไม่ใช่มาตรฐานตายตัว -
ปรับได้จากช่องกรอกในหน้าเว็บ ค่าที่นอกช่วงจะถูก **clamp** ให้อยู่ในช่วงเสมอ (ไม่
ปฏิเสธคำขอ) ค่าที่ไม่ใช่ตัวเลขจำกัด (NaN, Infinity) จะถูกละเว้น (คงค่าเดิมไว้)
`cellDurationMs` มีขั้นต่ำ 300ms เสมอเพื่อไม่ให้เกิด loop หน่วงเวลาเป็น 0 การ
เปลี่ยนค่าเวลามีผลกับการเปลี่ยนสถานะครั้งถัดไปเท่านั้น ไม่กระทบ timer ที่ตั้งไว้
แล้วและไม่ทำให้เริ่มเล่นซ้ำ/เล่นซ้อนกัน (ไม่มีการบันทึกค่าเหล่านี้ลง
localStorage หรือส่งไปที่ analytics ใด ๆ - รีเซ็ตกลับเป็นค่าเริ่มต้นทุกครั้งที่
โหลดหน้าใหม่)

### ขอบเขตที่ยังไม่ทำใน Step 5 (โดยตั้งใจ)

- **ไม่ส่งข้อมูลไปยัง Serial/ESP32 ไม่ว่ากรณีใด** - ไม่มีจุดใดใน
  `static/braille_playback.js` หรือปุ่มควบคุมการเล่นเรียก `fetch('/send')`,
  `sendPatternToESP32()`, หรือโค้ดเฉพาะ ESP32 ใด ๆ เลย (ยืนยันด้วยเทสต์ใน
  `tests/js/braille_playback_integration.test.js`)
- **ไม่มี frame padding** ใด ๆ - เซลล์ว่างทั้งหมดที่เห็นมาจากผลแปลจริงเท่านั้น
- **สิ่งที่ Step 6 ต้องเตรียมเพื่อเชื่อมต่อฮาร์ดแวร์จริง**: `static/braille_playback.js`
  มีจุดเชื่อมต่อ (callback `onCellDisplay`/`onTransientBlank`) ที่ Step 6
  สามารถต่อยอดเป็นเส้นทางส่งข้อมูลไปยัง ESP32 ได้ (เช่น เพิ่ม callback ใหม่หรือ
  wiring เพิ่มเติมใน script.js) โดยไม่ต้องแก้ state machine หลัก แต่ต้องออกแบบ
  ให้สอดคล้องกับ protocol Serial เดิม (`/send`, 6 หลัก `0`/`1`) และควรมีกลไก
  เปิด/ปิดการส่งจริงอย่างชัดเจน (opt-in) ไม่ส่งอัตโนมัติโดยไม่ได้รับอนุญาต

## การเชื่อมต่อฮาร์ดแวร์แบบมีการ์ด (Guarded Hardware Playback, Step 6)

Step 6 เชื่อม "ขอบเขตผลลัพธ์การเล่น" ของ Step 5 เข้ากับเส้นทาง Serial จริง โดย
**เปิดใช้งานเมื่อผู้ใช้ยินยอมอย่างชัดเจนเท่านั้น** หยุดได้อย่างปลอดภัย validate
เข้ม และทดสอบด้วย mock ได้ทั้งหมด

### สถานะความปลอดภัย ณ ปัจจุบัน (สรุปจากการตรวจ repo)

| หัวข้อ | สถานะ | หลักฐาน |
| --- | --- | --- |
| ซอร์สเฟิร์มแวร์ ESP32 | **ไม่มีใน repo** (ไม่มี `.ino`/`platformio.ini`/C/C++/binary/upload script ใด ๆ) | `git ls-files` |
| payload Serial ที่ส่งจริง | **ยืนยันแล้ว**: ASCII 6 บิต `0/1` + LF เช่น `b"101010\n"` | `app.py` `f"{pattern}\n".encode(...)` |
| baud / ตัวคั่น | **ยืนยันแล้ว**: 115200 บอด, 8N1, ตัวคั่น LF | `app.DEFAULT_BAUD`, `serial.Serial(..., timeout=1)` |
| การอ่าน Serial / การแยก ACK | **ไม่มี** — ไม่มี `.read()`/`.readline()` ที่ใดเลย | ตรวจซอร์สทั้งหมด |
| `000000` = คำสั่งดับทุกจุด | **สันนิษฐาน แต่ยังไม่ยืนยัน** ว่าเฟิร์มแวร์ปลดพลังงานทุกจุดอย่างปลอดภัย | ปุ่ม All OFF เดิมส่ง `000000` เท่านั้น |
| lock กันการเขียน Serial ซ้อน | **เพิ่มใน Step 6** (`serial_write_lock` ใช้ร่วมกับ `/send` เดิม) | `app.py` |
| actuator ค้างพลังงานเมื่อ browser แครช | **เป็นไปได้** — ก่อน Step 6 ไม่มีการล้างเมื่อหลุด/แครช | — |
| watchdog เฟิร์มแวร์ / host | **host watchdog เพิ่มใน Step 6**; **เฟิร์มแวร์ยังไม่มี** (blocker สำหรับใช้งานแบบไม่มีคนดูแล) | — |
| การจับคู่จุด ↔ GPIO | **ไม่ทราบ** (ไม่มีเฟิร์มแวร์) — ห้ามสมมติ | — |

> เนื่องจากความปลอดภัยของการ "ค้างเซลล์" (ความร้อนของ actuator / ไดรเวอร์ L298N)
> และพฤติกรรมการล้างเซลล์ **ยังยืนยันไม่ได้จาก repo** การเล่นไปยังฮาร์ดแวร์จริง
> จึง **ปิดอยู่โดยค่าเริ่มต้น** — mock transport, เซสชันแบบมีการ์ด, host watchdog,
> UI opt-in และโหมดตรวจสอบจุดด้วยมือ ถูก implement ครบ แต่ transport production
> จะ `is_available() == False` จนกว่าจะตั้ง env สองตัว:
>
> ```bash
> export BRAILLE_HARDWARE_ENABLED=1
> export BRAILLE_HARDWARE_SAFETY_CONFIRMED=1   # ตั้งได้ก็ต่อเมื่อผ่านเช็กลิสต์ฮาร์ดแวร์แบบมีผู้ดูแลแล้ว
> ```
>
> เดโม/เทสต์ในเบราว์เซอร์โดยไม่มีฮาร์ดแวร์: `export BRAILLE_HARDWARE_MOCK=1`

### สถาปัตยกรรม

- **`braille_hardware.py`** — ชั้น transport (แยกจาก playback/OCR/Liblouis/Flask
  โดยสิ้นเชิง): `BrailleHardwareTransport` (ABC: `is_available`, `display_pattern`,
  `clear`, `close`/`disconnect`) พร้อม 3 implementation —
  `SerialBrailleHardwareTransport` (ใช้ซ้ำ `ser_conn` เดิม + `serial_write_lock`
  เดียวกับ `/send` ไม่มี `serial.Serial` ซ้ำซ้อน), `MockBrailleHardwareTransport`
  (deterministic บันทึกทุก payload ไบต์), `UnavailableBrailleHardwareTransport`
  (raise error มีโครงสร้าง) — `CLEAR_PATTERN = "000000"`, `validate_pattern` รับ
  เฉพาะ `^[01]{6}$`, `encode_pattern` = ASCII 6 บิต + LF (ไม่รับข้อความ OCR /
  Unicode Braille)
- **`braille_hardware_session.py`** — `HardwarePlaybackSessionManager`: เซสชันเดียว
  ต่อครั้ง, `session_id` + `generation` ต้องตรงทุกคำขอ, เริ่มต้อง `clear()` ก่อน,
  แยก "ช่องว่างชั่วคราว" (ไม่เพิ่ม real-cell index) จาก "เซลล์ว่างจริง" (เพิ่ม
  index), host watchdog หนึ่งตัวต่อเซสชัน (`threading.Timer` inject ได้ในเทสต์),
  stop = ยกเลิกเซสชัน **ก่อน** แล้ว best-effort `clear()` ครั้งเดียว
- **`static/braille_hardware.js`** — `BrailleHardwareBridge` (ไม่รู้จัก DOM):
  `onCell → sendCell(bit_pattern, index)`, `onTransientBlank → sendTransientGap()`
  ส่ง `"000000"`, `onStop/onComplete/onError → handlePlaybackEnded()`, ปุ่ม
  Pause / "ฟังอีกครั้ง" / Restart → `handlePlaybackEnded()` อย่างชัดเจน, ทิ้ง
  callback ล้าสมัย, โหมด **ปิดเสมอตอนสร้าง instance**
  - **การจัดคิว (serialization)**: ทุกคำขอที่เปลี่ยนสถานะฮาร์ดแวร์ (cell / gap /
    verify) ของเซสชันหนึ่งเข้าคิวและทำ **ทีละคำขอ** ไม่มีทางที่สองคำขอออกพร้อม
    กันด้วย `generation` เดียวกัน (ซึ่งจะทำให้คำขอที่สองได้ `409 stale_session`)
    แต่ละคำขอในคิวใช้ `generation` ล่าสุดจาก response ก่อนหน้า - `stopSession`
    มีลำดับความสำคัญสูงสุด: ทำให้เซสชัน client เป็นโมฆะทันที ล้างคิว แล้วส่งคำขอ
    `/stop` แบบ best-effort โดยไม่รอคิว - response ที่มาถึงช้าหลังหยุด/รีสตาร์ต
    ถูกทิ้ง (ห้ามปลุกเซสชันใหม่ให้ทำงาน)
- **Flask routes** (ไม่แตะ `ser_conn` ตรง ๆ ไม่ log เนื้อหาเอกสาร):
  `GET /api/hardware/status`, `GET /api/hardware/ports`,
  `POST /api/hardware/playback/{start,cell,stop}`, `POST /api/hardware/verify/cell`

### ปุ่มควบคุมการเล่นหลัก vs โหมดฮาร์ดแวร์ (สำคัญด้านความปลอดภัย)

ปุ่ม "เริ่มเล่น / ก่อนหน้า / ถัดไป / เริ่มใหม่" ในส่วนหลักเป็น **ปุ่มควบคุมการ
จำลองล้วน ๆ** ต้องทำงานได้เสมอไม่ว่าจะมีฮาร์ดแวร์หรือไม่ และ **ไม่มีจุดใดเริ่ม
เซสชันฮาร์ดแวร์อัตโนมัติ** เซสชันฮาร์ดแวร์เริ่มได้เฉพาะเมื่อผู้ใช้: (1) ติ๊ก
checkbox "โหมดฮาร์ดแวร์จริง" → (2) เลือกและเชื่อมต่อพอร์ต → (3) กด "เริ่มเซสชัน
ฮาร์ดแวร์" เอง เมื่อเซสชันเปิดอยู่ callback ของการเล่นจึงส่งเซลล์ให้อัตโนมัติ
ผ่านคิว - การเล่นอัตโนมัติส่ง real-cell index ตามลำดับ (0, 1, 2, …), transient
gap ไม่เพิ่ม index

> การถดถอยจาก commit `e45bdd5` (แก้แล้ว): ปุ่มเล่นหลักเคยเรียก
> `ensureHardwareSessionActive()` ที่อยู่นอก scope → `ReferenceError` ทำให้การ
> เล่นจำลองพังทั้งหมด; และ `paused` เคยยิง transient gap ชนกับ cell ด้วย
> generation เดียวกัน → `409 stale_session` ทำลายเซสชัน ตอนนี้ปุ่มหลักไม่แตะ
> ฮาร์ดแวร์โดยตรง และคำขอทุกอย่างเข้าคิวทีละรายการ

### ความหมายของ "สำเร็จ" — สี่ระดับ (สำคัญ)

เฟิร์มแวร์ **ไม่มี ACK ที่ยืนยันได้** ระบบจึงแยก:

| ระดับ | ความหมาย | ค่าใน Step 6 |
| --- | --- | --- |
| `accepted_by_server` | เซิร์ฟเวอร์รับคำขอ + ผ่าน validation | `true` เมื่อผ่าน |
| `written_to_serial` | เขียนไบต์ลง OS buffer + `flush()` แล้ว | `true` เมื่อเขียนได้ |
| `acknowledged_by_device` | อุปกรณ์ตอบรับ | **`null` (unknown) เสมอ** |
| `physically_displayed` | เซลล์ถูกยกจุดจริงบนฮาร์ดแวร์ | **`null` (unknown) เสมอ** |

UI แสดง **"ส่งคำสั่งผ่าน Serial แล้ว แต่ยังไม่ได้รับการยืนยันจากอุปกรณ์"** เท่านั้น
ไม่มีจุดใดแสดง "ESP32 แสดงผลสำเร็จ" หลัง `write()`/`flush()`

### host watchdog และข้อจำกัด

ทุกคำขอเซลล์ที่ถูกต้อง refresh เส้นตายสั้น ๆ (`DEFAULT_WATCHDOG_SECONDS = 4.0`
วินาที, ปรับได้ตอน `start()`, clamp 1–30) เมื่อเลยเส้นตาย: ยกเลิกเซสชัน →
best-effort `clear()` → บันทึก safety event (**ไม่มีข้อความ OCR**) — เวลาของ
watchdog แยกจากเวลาการเล่นเซลล์, มี timer เดียวต่อเซสชัน, เซสชันใหม่ทำให้
callback ของ watchdog เก่าเป็นโมฆะ, `atexit` ของ Flask ทำ best-effort clear,
การ disconnect ทำ best-effort clear ก่อนปิดพอร์ต

**4.0 วินาที คือค่าอนุรักษ์นิยม (conservative) ฝั่ง host ที่เลือกไว้เท่านั้น —
ไม่ใช่ค่าที่พิสูจน์แล้วว่าปลอดภัยเชิงกายภาพสำหรับ actuator** (commit `e45bdd5`
เคยดันเป็น 10.0 โดยไม่มีหลักฐาน จึง revert กลับ) `cellDurationMs` ปกติ = 3000 ms
< 4000 ms จึง refresh watchdog ทันทุกเซลล์ หากตั้ง `cellDurationMs` > watchdog
(เช่น 5000 ms) watchdog จะสั่งล้างเซลล์และจบเซสชันฮาร์ดแวร์ระหว่างเซลล์ (การเล่น
จำลองยังทำงานต่อ) — ให้ตั้ง `cellDurationMs` ≤ watchdog เพื่อการเล่นฮาร์ดแวร์
ต่อเนื่อง

> **host watchdog ป้องกันไม่ได้** เมื่อคอมพิวเตอร์แครช สาย USB หลุด หรือไฟดับ —
> **ยังจำเป็นต้องมี watchdog / timeout-clear ระดับเฟิร์มแวร์** สำหรับ actuator ที่
> อาจร้อนเกิน หากเฟิร์มแวร์ไม่มี ถือเป็น **blocker** สำหรับการใช้งานแบบไม่มีคนดูแล
> — พฤติกรรม watchdog ระดับเฟิร์มแวร์ยัง **ไม่ทราบ**

### ขั้นตอน opt-in ฮาร์ดแวร์ (UI)

การ์ด "โหมดฮาร์ดแวร์จริง" แยกจากการเล่นจำลอง — **ปิดทุกครั้งที่โหลดหน้า** ต้อง
ติ๊ก checkbox ยืนยันเอง → เลือกพอร์ต (ระบบไม่เลือกให้ ไม่เดาว่าเป็น ESP32) →
เชื่อมต่อ → กด "เริ่มเซสชันฮาร์ดแวร์" เอง → ปุ่ม "หยุดและล้างเซลล์" เด่นชัด กด
ด้วยคีย์บอร์ดได้ตลอดเวลาที่เล่นอยู่ สถานะการเชื่อมต่อ/การส่ง/watchdog/หยุด ใช้
`aria-live` ไม่พึ่งสีอย่างเดียว การเล่นจำลองยังทำงานได้อิสระ

**นโยบาย Pause / "ฟังอีกครั้ง" (เลือกใช้แบบเดียว สอดคล้องทุกที่):**

| การกระทำ | ผลต่อการจำลอง | ผลต่อเซสชันฮาร์ดแวร์ |
| --- | --- | --- |
| ปุ่ม "หยุดชั่วคราว" (Pause) | หยุดชั่วคราว เก็บตำแหน่งไว้ | **จบและล้างเซสชัน** (`handlePlaybackEnded`) |
| ปุ่ม "ฟังข้อความอีกครั้ง" (Listen Again) | หยุดการเล่นชั่วคราว | **จบและล้างเซสชัน** |
| ปุ่ม "หยุด" (Stop) | หยุด ล้างจอจำลอง | **จบและล้างเซสชัน** |
| ปุ่ม "เริ่มใหม่" (Restart) | กลับเซลล์แรก | **จบและล้างเซสชัน** (ต้องเริ่มเซสชันใหม่เอง) |
| ปุ่ม "ก่อนหน้า / ถัดไป" (Previous/Next) | เลื่อน 1 เซลล์ | ส่ง **เฉพาะเซลล์ปลายทาง** ผ่านคิว (ถ้าเซสชัน active) ไม่มี transient gap ชนกัน; การถอยหลังผ่านเซลล์ที่ส่งไปแล้วจะทำให้เซิร์ฟเวอร์จบเซสชันแบบ fail-safe |
| OCR ใหม่ / แปลใหม่ / reset / ปิดโหมดฮาร์ดแวร์ | ล้างลำดับ | **จบและล้างเซสชัน** |

การกลับมาเล่นต่อหลัง Pause/Stop/Restart **ต้องกด "เริ่มเซสชันฮาร์ดแวร์" ใหม่
อย่างชัดเจน** — ไม่มีการ resume เซสชันฮาร์ดแวร์อัตโนมัติ ปลอดภัยกว่าการค้างเซลล์
ที่จ่ายพลังงานไว้ระหว่างพัก

### พฤติกรรม lifecycle ของเบราว์เซอร์ (ไม่รับประกัน)

`visibilitychange` (แท็บถูกซ่อน) → pause + หยุดเซสชัน; `pagehide` → best-effort
หยุด; `beforeunload` → สัญญาณเสริมเท่านั้น — **host watchdog คือด่านหลักฝั่งโฮสต์**

### กฎการเลือกพอร์ต

`GET /api/hardware/ports` แสดง metadata จาก PySerial ตามจริง — **ไม่**สร้าง
`COM3`/`COM4` ปลอม, **ไม่**ตั้งชื่อว่า ESP32, `/dev/cu.wlan-debug` และอุปกรณ์
Bluetooth ถูกทำเครื่องหมาย `likely_unrelated`, ทุกพอร์ตแสดง **"อุปกรณ์ Serial ที่
ยังไม่ได้ยืนยันชนิด"** จนกว่าจะยืนยันตัวตนได้จริง (ไม่มี handshake ปลอม) — ผู้ใช้
ต้องเลือกเอง, รองรับ Windows เดิม, `/send` เดิมทำงานเข้ากันได้ย้อนหลัง

### โหมดตรวจสอบลำดับจุดด้วยมือ

`POST /api/hardware/verify/cell` รับเฉพาะ `100000, 010000, 001000, 000100,
000010, 000001, 000000` — **ไม่มี `111111`** เริ่มด้วย clear, กดสั่งทีละรูปแบบ,
watchdog จำกัดเวลาการจ่ายพลังงาน, บันทึกผลสังเกต (pattern / จุดที่คาดหวัง / จุด
ที่เห็นจริง / pass·fail·unknown) **ในหน้าเว็บเท่านั้น ไม่ commit เข้า Git** —
ตรวจได้แค่ **ลำดับจุดเชิงตรรกะ 1–6** ไม่ใช่หมายเลขขา GPIO ของ ESP32

### เช็กลิสต์การทดสอบฮาร์ดแวร์แบบมีผู้ดูแล (ห้ามรันอัตโนมัติ)

1. ถอดไฟเลี้ยง actuator ออกก่อน
2. เสียบ USB แล้วเลือกพอร์ต Serial ที่ยืนยันแล้ว
3. ยืนยัน baud (115200) และคำสั่งล้าง (`000000` + LF)
4. จ่ายไฟ actuator โดยมีผู้ดูแล
5. ส่ง `000000` เป็นอย่างแรก
6. ทดสอบทีละจุด ด้วยเวลากดสั้น ๆ
7. ยืนยันจุดเชิงตรรกะ 1–6
8. ทดสอบปุ่มหยุด และการล้างโดย watchdog
9. ถอด USB ระหว่างการทดสอบที่ปลอดภัย สังเกตพฤติกรรมเฟิร์มแวร์ (ล้างเองหรือไม่)
10. ทดสอบลำดับที่แปลแล้วสั้น ๆ หนึ่งชุด
11. บันทึกว่ามี ACK ตอบกลับหรือไม่
12. หยุดทันทีหากฮาร์ดแวร์ร้อน สั่นผิดปกติ หรือไม่ล้างเซลล์

### คำถามที่ยังค้างสำหรับทีมฮาร์ดแวร์

- เฟิร์มแวร์ตีความ `000000` เป็น "ปลดพลังงานทุกจุด" จริงหรือไม่ และค้างสถานะนั้น
  ได้นานเท่าใดอย่างปลอดภัย
- การค้างเซลล์ที่มีจุดเปิด (เช่น `101010`) ค้างได้กี่วินาทีก่อน actuator/L298N
  ร้อนเกิน — ต้องมี duty-cycle หรือไม่
- เฟิร์มแวร์มี watchdog / auto-clear timeout หรือไม่ ถ้ามี กี่มิลลิวินาที
- เฟิร์มแวร์ส่งสตริง ACK ใด ๆ กลับหรือไม่ (รูปแบบ, เงื่อนไข)
- การจับคู่จุดเบรลล์ 1–6 กับขา GPIO ของ ESP32 และช่องของ L298N
- พฤติกรรมเมื่อ USB หลุดกลางคัน — เฟิร์มแวร์ล้างเซลล์เองหรือค้าง
- เวอร์ชันเฟิร์มแวร์ปัจจุบันบนบอร์ดต้นแบบ และมีซอร์สที่ใด

รายละเอียดโปรโตคอลระดับไบต์: ดู [`PROTOCOL.md`](PROTOCOL.md)

## ทดสอบ

ชุดทดสอบใช้ Reader จำลอง จึงไม่ดาวน์โหลดโมเดล ไม่ใช้ GPU ไม่ใช้อินเทอร์เน็ต และไม่ทำ OCR จริง
ชุดทดสอบฮาร์ดแวร์ (Step 6) ใช้ mock transport + fake timer ทั้งหมด **ไม่เปิดพอร์ต
Serial จริง** และไม่มีการเรียก `/api/hardware/*` อัตโนมัติตอนโหลดหน้า
(`tests/test_regression_e45bdd5.py` + `tests/js/braille_hardware_regression.test.js`
ตรึงการแก้การถดถอยของ commit `e45bdd5`: ปุ่มเล่นหลักต้องไม่ ReferenceError, ไม่
เริ่มเซสชันฮาร์ดแวร์อัตโนมัติ, ไม่เกิด `409 stale_session` ระหว่างเล่นตามลำดับ,
Pause/Listen Again จบเซสชัน, ต้องมี flag ทั้งสองตัว, watchdog กลับเป็น 4.0s,
Liblouis ไม่ fallback ไป legacy dictionary):

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
node --check static/script.js
node --check static/braille_playback.js
node --check static/braille_hardware.js
node --test "tests/js/**/*.test.js"
python -m compileall -q app.py ocr_service.py image_preprocessing.py ocr_evaluation.py evaluate_ocr.py synthetic_dataset.py generate_synthetic_ocr.py braille_models.py braille_translation.py liblouis_translator.py legacy_braille_dictionary.py braille_hardware.py braille_hardware_session.py tests
git diff --check
```

ชุดทดสอบ `tests/js/` ครอบคลุมพฤติกรรมการอ่านออกเสียง (TTS), ปุ่มยืนยัน,
คำเตือนคุณภาพภาพ, **การแปลงเป็นอักษรเบรลล์หลังยืนยัน** (`braille_translation.
test.js`), และ**การเล่นลำดับอักษรเบรลล์แบบจำลอง** (Step 5:
`braille_playback.test.js` ทดสอบ state machine ล้วนด้วย timer จำลองแบบ
deterministic ไม่พึ่ง DOM เลย, `braille_playback_integration.test.js` ทดสอบการ
เชื่อมกับ DOM/ปุ่มควบคุม/จอแสดงผลจำลองจริงผ่าน `static/script.js`) โดยรัน
`static/script.js` และ `static/braille_playback.js` จริงในบริบท Node `vm`
พร้อม DOM, `speechSynthesis`/`fetch` จำลอง, และ timer queue จำลอง
(`tests/js/fake-dom.js`) ไม่ต้องติดตั้งแพ็กเกจ npm ใด ๆ เพิ่มเติม ไม่มีการรอ
เวลาจริงแม้แต่มิลลิวินาทีเดียวในเทสต์การเล่นเบรลล์ ส่วน `tests/test_image_preprocessing.py` และ
`tests/test_ocr_evaluation.py` ทดสอบ preprocessing, heuristic วัดคุณภาพภาพ,
CER/WER, dataset labeling (synthetic/real_camera), และ CLI ประเมินผล ด้วยภาพ
เล็กที่สร้างในหน่วยความจำและ OCR reader จำลอง ส่วน `tests/test_synthetic_dataset.py`
ทดสอบตัวสร้างชุดข้อมูลสังเคราะห์ (Step 3.5): การ render, augmentation แบบ
deterministic, การป้องกัน data leakage ระหว่าง split, และความเข้ากันได้ของ
manifest กับ `evaluate_ocr.py` เดิม ใช้ font ที่ฝังอยู่ใน Pillow เองสำหรับกลไก
ทั่วไป และค้นหา font ไทยที่มีอยู่แล้วในเครื่อง (ข้ามอย่างชัดเจนถ้าไม่พบ) สำหรับ
เทสต์ที่ต้องตรวจสอบสระ/วรรณยุกต์ไทยจริง

ชุดทดสอบ Step 4 (`tests/test_braille_models.py`, `tests/test_braille_translation.py`,
`tests/test_liblouis_translator.py`, `tests/test_legacy_braille_dictionary.py`,
`tests/test_app_braille.py`) ทดสอบ bitmask 0-63 ครบทุกค่า, การแปลง Unicode
Braille, normalization, orchestration, และ API ทั้งหมดด้วย `FakeBrailleTranslator`
(ไม่ต้องมี Liblouis ติดตั้ง) ส่วน `tests/test_liblouis_integration.py` เป็น
integration test เสริมที่**ข้ามอัตโนมัติ**ถ้าไม่พบ Liblouis หรือตาราง th-g1.utb
ในเครื่อง (ดูหัวข้อการแปลข้อความเป็นเบรลล์ด้านบนสำหรับวิธีติดตั้ง)

ไม่มีการดาวน์โหลด font, โมเดล OCR, dataset, หรือ Liblouis ใด ๆ ระหว่างรันชุด
เทสต์อัตโนมัติหลักทั้งหมดข้างต้น
