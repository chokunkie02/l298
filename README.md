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

## ทดสอบ

ชุดทดสอบใช้ Reader จำลอง จึงไม่ดาวน์โหลดโมเดล ไม่ใช้ GPU ไม่ใช้อินเทอร์เน็ต และไม่ทำ OCR จริง:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
node --check static/script.js
node --test "tests/js/**/*.test.js"
python -m compileall -q app.py ocr_service.py image_preprocessing.py ocr_evaluation.py evaluate_ocr.py synthetic_dataset.py generate_synthetic_ocr.py braille_models.py braille_translation.py liblouis_translator.py legacy_braille_dictionary.py tests
git diff --check
```

ชุดทดสอบ `tests/js/` ครอบคลุมพฤติกรรมการอ่านออกเสียง (TTS), ปุ่มยืนยัน,
คำเตือนคุณภาพภาพ, และ**การแปลงเป็นอักษรเบรลล์หลังยืนยัน** (`braille_translation.
test.js`) โดยรัน `static/script.js` จริงในบริบท Node `vm` พร้อม DOM และ
`speechSynthesis`/`fetch` จำลอง (`tests/js/fake-dom.js`) ไม่ต้องติดตั้ง
แพ็กเกจ npm ใด ๆ เพิ่มเติม ส่วน `tests/test_image_preprocessing.py` และ
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
