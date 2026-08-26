"""พจนานุกรมแมปตัวอักษร -> รูปแบบจุด 6 บิตแบบ hardcode ที่มีอยู่เดิมในโปรเจกต์
(ย้ายมาจาก app.py แบบคงเนื้อหาเดิมทุกประการ ไม่มีการแก้ไขค่าใด ๆ)

**คำเตือนสำคัญ - อ่านก่อนใช้งาน**:

  1. **พจนานุกรมนี้ยังไม่ได้รับการตรวจสอบความถูกต้องเทียบกับมาตรฐานอักษร
     เบรลล์ไทยใด ๆ** (เช่น คู่มืออักษรเบรลล์ไทย/Thai Braille Use Manual) ไม่มี
     แหล่งอ้างอิงที่ authoritative กำกับไว้ในโค้ดเดิม จึง**ต้องไม่ถือว่าถูกต้อง
     ตามมาตรฐานโดยไม่มีหลักฐานยืนยัน**

  2. **ไม่ถูกใช้โดยอัตโนมัติในเส้นทางการแปล OCR -> เบรลล์ (Step 4)** เส้นทาง
     production (`POST /api/braille/translate`) ใช้ Liblouis เท่านั้น (ดู
     braille_translation.py, liblouis_translator.py) พจนานุกรมนี้ใช้เพื่อ:
       (ก) endpoint `/api/braille_dictionary` เดิมที่มีอยู่ก่อน Step 4 (คงไว้
           สำหรับการทดสอบฮาร์ดแวร์ด้วยมือ ไม่เกี่ยวกับ OCR)
       (ข) `LegacyDictionaryTranslator` ด้านล่าง ซึ่ง**ต้องเปิดใช้งานด้วยมือ
           อย่างชัดเจนเท่านั้น** (ผ่านพารามิเตอร์ `enabled=True` ตรง ๆ) สำหรับ
           การพัฒนา/ทดลองเท่านั้น ห้ามเปิดใช้ใน production

  3. **มีเฉพาะพยัญชนะไทย (ไม่มีสระ วรรณยุกต์ ตัวเลขไทย หรือเครื่องหมายวรรค
     ตอนไทย)**, ตัวพิมพ์ใหญ่ภาษาอังกฤษ A-Z, และตัวเลข 0-9 เท่านั้น - ไม่รองรับ
     คำภาษาไทยทั่วไปที่มีสระ/วรรณยุกต์ ซึ่งเป็นข้อความเกือบทั้งหมดที่ OCR จะพบ
     จริง (ดูการตรวจสอบเปรียบเทียบกับพจนานุกรมฝั่ง frontend ใน static/script.js
     ที่ tests/test_legacy_braille_dictionary.py และ README.md)
"""

from __future__ import annotations

# Thai Braille Mapping Reference Dictionary (6-dot Binary Representation)
# ย้ายมาจาก app.py คำต่อคำ - ไม่เปลี่ยนค่าใด ๆ (ดู git blame ของ app.py เดิม
# สำหรับประวัติที่มาก่อนหน้านี้)
THAI_BRAILLE_MAP: dict[str, str] = {
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


class LegacyDictionaryDisabledError(RuntimeError):
    """เกิดขึ้นเมื่อพยายามใช้ LegacyDictionaryTranslator โดยไม่เปิด enabled=True
    อย่างชัดเจน - ป้องกันการใช้พจนานุกรมที่ยังไม่ตรวจสอบโดยไม่ตั้งใจ
    """


class LegacyDictionaryTranslator:
    """Translator backend (ตรงตาม braille_translation.BrailleTranslatorBackend)
    ที่ใช้ THAI_BRAILLE_MAP ข้างบน - **สำหรับการพัฒนา/ทดลองเท่านั้น**

    ต้องส่ง `enabled=True` อย่างชัดเจนตอนสร้าง object เท่านั้นถึงจะใช้งานได้
    (ค่าเริ่มต้นคือ False เสมอ) เพื่อไม่ให้ถูกใช้งานโดยไม่ตั้งใจในเส้นทาง
    production ใด ๆ - แม้เปิดใช้แล้ว is_available()/check_table() ยังคงคืนค่า
    ที่บ่งชี้ว่านี่คือพจนานุกรมที่ยังไม่ตรวจสอบเสมอผ่าน engine_name()

    ตัวอักษรที่ไม่มีในพจนานุกรม (สระ วรรณยุกต์ เครื่องหมายวรรคตอน ช่องว่าง
    ตัวอักษรไทยส่วนใหญ่) จะถูกข้ามและบันทึกเป็นข้อมูล - ไม่ raise error ทั้งคำขอ
    เพราะพจนานุกรมนี้ไม่สมบูรณ์อยู่แล้วโดยธรรมชาติของมันเอง (ดู docstring ของ
    โมดูล) ผู้เรียกต้องตีความ cell_count ที่ต่ำกว่าที่คาดไว้เอง
    """

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    def engine_name(self) -> str:
        return "legacy-dictionary-UNVERIFIED"

    def engine_version(self) -> str | None:
        return "unversioned-hardcoded-dict"

    def table_name(self) -> str:
        return "legacy_braille_dictionary.THAI_BRAILLE_MAP"

    def is_available(self) -> bool:
        return self._enabled

    def check_table(self) -> bool | None:
        # ไม่มี "ตาราง" แยกต่างหากให้ตรวจสอบ - คืน None เสมอ (แปลว่า "ข้าม
        # ขั้นตอนตรวจสอบตาราง" ไม่ใช่ "ตารางถูกต้อง")
        return None

    def translate_line(self, line: str) -> str:
        if not self._enabled:
            raise LegacyDictionaryDisabledError(
                "LegacyDictionaryTranslator ถูกปิดใช้งานอยู่ (ต้องระบุ enabled=True "
                "อย่างชัดเจนเพื่อการพัฒนา/ทดลองเท่านั้น) พจนานุกรมนี้ยังไม่ผ่านการ "
                "ตรวจสอบความถูกต้อง ห้ามใช้ใน production"
            )

        from braille_models import BRAILLE_UNICODE_BASE, bitmask_from_bit_pattern

        chars = []
        for char in line:
            pattern = THAI_BRAILLE_MAP.get(char)
            if pattern is None:
                continue  # ตัวอักษรไม่มีในพจนานุกรม (สระ/วรรณยุกต์/ช่องว่าง/ฯลฯ) - ข้าม
            bitmask = bitmask_from_bit_pattern(pattern)
            chars.append(chr(BRAILLE_UNICODE_BASE + bitmask))
        return "".join(chars)
