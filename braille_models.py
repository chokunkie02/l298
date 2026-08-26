"""โมเดลข้อมูลของผลลัพธ์การแปลข้อความเป็นอักษรเบรลล์ 6 จุด (Step 4)

โมดูลนี้เป็น pure data structures + ฟังก์ชันแปลง bitmask/Unicode Braille ล้วน
ไม่ import Flask, EasyOCR, Serial, หรือ ESP32 เลย เพื่อให้ทดสอบและนำไปใช้ซ้ำได้
อิสระจาก app.py และ braille_translation.py

ลำดับบิตที่ใช้ตลอดทั้งระบบ (คงที่เสมอ ต้องไม่สลับ เพราะ /send และคีย์บอร์ด
ทดสอบฮาร์ดแวร์เดิมใน static/script.js ใช้ลำดับนี้อยู่แล้ว):
  - bit 0 (ค่า 1)  = dot 1
  - bit 1 (ค่า 2)  = dot 2
  - bit 2 (ค่า 4)  = dot 3
  - bit 3 (ค่า 8)  = dot 4
  - bit 4 (ค่า 16) = dot 5
  - bit 5 (ค่า 32) = dot 6
  bitmask ที่ถูกต้องคือจำนวนเต็ม 0-63 (2^6 ค่า) bit_pattern คือสตริง 6 ตัวอักษร
  '0'/'1' เรียงตาม dot 1,2,3,4,5,6 - ตรงกับรูปแบบที่ใช้อยู่แล้วใน setPattern()/
  updateVisualPreview() ของ static/script.js และ endpoint /send ของ app.py

ลำดับบิตนี้ตรงกับนิยามบิตของ Unicode Braille Patterns block (U+2800-U+28FF)
เองพอดี: bit 0-5 ของ (codepoint - 0x2800) คือ dot 1-6, bit 6 คือ dot 7, bit 7
คือ dot 8 ตามมาตรฐาน Unicode การแปลงจึงตรงไปตรงมาสำหรับ dot 1-6 แต่ต้นแบบ
ฮาร์ดแวร์นี้รองรับเซลล์ 6 จุดเท่านั้น (Step 4) - ถ้าผลลัพธ์จาก translator มี
dot 7/8 ติดมาด้วยจะถูกตรวจพบและรายงานเป็น diagnostic ไม่ถูกละทิ้งเงียบ ๆ

เซลล์ว่าง (blank cell, U+2800) คือ bitmask 0 / bit_pattern "000000" - เป็นเซลล์
จริงที่มีความหมาย (เช่น ช่องว่างระหว่างคำ) ไม่ใช่ "ตัวเติมช่องว่างของเฟรม" ใด ๆ -
Step 4 นี้ยังไม่มีแนวคิดเรื่อง frame padding เลย
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --- ค่าคงที่ของการเข้ารหัสเซลล์ 6 จุด --------------------------------------

DOT_COUNT = 6
DOT_NUMBERS_IN_ORDER = (1, 2, 3, 4, 5, 6)
MIN_BITMASK = 0
MAX_BITMASK = 0b111111  # 63 - ค่าสูงสุดของเซลล์ 6 จุด (ทุกจุดเปิด)

BRAILLE_UNICODE_BASE = 0x2800
BRAILLE_UNICODE_MAX = 0x28FF  # ครอบคลุมจุด 1-8 ทั้งหมด (256 ค่า)
SIX_DOT_MASK = 0b00111111  # บิต 0-5 = dot 1-6
DOTS_7_8_MASK = 0b11000000  # บิต 6-7 = dot 7, dot 8

BLANK_CELL_UNICODE = chr(BRAILLE_UNICODE_BASE)  # U+2800 "⠀"


class InvalidBrailleMaskError(ValueError):
    """เกิดขึ้นเมื่อ bitmask ที่ให้มาไม่ใช่จำนวนเต็ม 0-63 ที่ถูกต้อง

    รวมถึงกรณี bool (True/False เป็น subclass ของ int ใน Python แต่ไม่ใช่
    bitmask ที่ถูกต้องเชิงความหมาย), float, string, ค่าติดลบ, และค่าเกิน 63
    """


@dataclass(frozen=True)
class BrailleCell:
    """หนึ่งเซลล์เบรลล์ 6 จุด พร้อมข้อมูลครบทุกรูปแบบ (index, unicode, dot
    numbers, bitmask, bit pattern) - immutable เสมอ
    """

    index: int
    unicode_braille: str
    dot_numbers: tuple[int, ...]
    bitmask: int
    bit_pattern: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "unicode_braille": self.unicode_braille,
            "dot_numbers": list(self.dot_numbers),
            "bitmask": self.bitmask,
            "bit_pattern": self.bit_pattern,
        }


def _validate_bitmask(bitmask: Any) -> int:
    """ตรวจว่า bitmask เป็นจำนวนเต็ม 0-63 ที่แท้จริง ปฏิเสธ bool/float/string/
    ค่านอกช่วงทั้งหมดอย่างชัดเจน (ไม่แปลงให้เงียบ ๆ)
    """
    if isinstance(bitmask, bool) or not isinstance(bitmask, int):
        raise InvalidBrailleMaskError(
            f"bitmask ต้องเป็นจำนวนเต็ม (int) เท่านั้น ได้รับชนิด {type(bitmask).__name__}: {bitmask!r}"
        )
    if not (MIN_BITMASK <= bitmask <= MAX_BITMASK):
        raise InvalidBrailleMaskError(
            f"bitmask ต้องอยู่ในช่วง {MIN_BITMASK}-{MAX_BITMASK} (เซลล์ 6 จุด) ได้รับ {bitmask}"
        )
    return bitmask


def dots_from_bitmask(bitmask: int) -> tuple[int, ...]:
    """แปลง bitmask (0-63) เป็นรายการหมายเลขจุดที่เปิด เรียงจากน้อยไปมาก (1-6)"""
    _validate_bitmask(bitmask)
    return tuple(dot for dot in DOT_NUMBERS_IN_ORDER if bitmask & (1 << (dot - 1)))


def bit_pattern_from_bitmask(bitmask: int) -> str:
    """แปลง bitmask (0-63) เป็นสตริง 6 ตัวอักษร '0'/'1' เรียงตาม dot 1,2,3,4,5,6"""
    _validate_bitmask(bitmask)
    return "".join("1" if bitmask & (1 << (dot - 1)) else "0" for dot in DOT_NUMBERS_IN_ORDER)


def bitmask_from_bit_pattern(bit_pattern: str) -> int:
    """แปลงสตริง 6 หลัก '0'/'1' (เรียง dot 1-6) กลับเป็น bitmask - ใช้เพื่อ
    ทดสอบความสอดคล้อง (round-trip) กับรูปแบบเดิมที่ /send และ static/script.js ใช้
    """
    if not isinstance(bit_pattern, str) or len(bit_pattern) != DOT_COUNT or any(c not in "01" for c in bit_pattern):
        raise InvalidBrailleMaskError(
            f"bit_pattern ต้องเป็นสตริง 6 ตัวอักษรที่มีแต่ '0'/'1' เท่านั้น ได้รับ {bit_pattern!r}"
        )
    bitmask = 0
    for position, char in enumerate(bit_pattern):
        if char == "1":
            bitmask |= 1 << position
    return bitmask


def make_cell(index: int, bitmask: int) -> BrailleCell:
    """สร้าง BrailleCell จาก index และ bitmask พร้อมตรวจสอบความถูกต้องทั้งหมด

    นี่คือทางเข้าเดียวที่ควรใช้สร้าง BrailleCell เพื่อการันตีว่าทุกฟิลด์
    สอดคล้องกันเสมอ (unicode_braille, dot_numbers, bit_pattern ล้วนคำนวณจาก
    bitmask เดียวกัน ไม่มีทางขัดแย้งกันเอง)
    """
    _validate_bitmask(bitmask)
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError(f"index ของเซลล์ต้องเป็นจำนวนเต็มไม่ติดลบ ได้รับ {index!r}")
    return BrailleCell(
        index=index,
        unicode_braille=chr(BRAILLE_UNICODE_BASE + bitmask),
        dot_numbers=dots_from_bitmask(bitmask),
        bitmask=bitmask,
        bit_pattern=bit_pattern_from_bitmask(bitmask),
    )


@dataclass(frozen=True)
class TranslationDiagnostic:
    """คำเตือน/ข้อผิดพลาดระดับตัวอักษรหรือระดับเซลล์ระหว่างการแปล ไม่ทำให้การ
    แปลทั้งคำขอล้มเหลวเสมอไป (ขึ้นกับ severity และตำแหน่งที่เกิด) - ใช้บอกผู้ใช้/
    นักพัฒนาว่าเกิดอะไรขึ้นอย่างชัดเจน แทนที่จะละทิ้งข้อมูลไปเงียบ ๆ
    """

    severity: str  # "error" | "warning" | "info"
    code: str
    description: str
    source_index: int | None = None
    character: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "description": self.description,
            "source_index": self.source_index,
            "character": self.character,
        }


class DiagnosticSeverity:
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class BrailleTranslation:
    """ผลลัพธ์การแปลข้อความหนึ่งคำขอทั้งหมด - อ่านอย่างเดียว (read-only) และ
    เป็นอิสระจาก Flask/EasyOCR/Serial/ESP32 โดยสิ้นเชิง
    """

    source_text: str
    normalized_text: str
    cells: tuple[BrailleCell, ...]
    line_boundaries: tuple[int, ...]
    diagnostics: tuple[TranslationDiagnostic, ...]
    engine: str
    engine_version: str | None
    table: str | None
    changed_by_normalization: bool

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_text": self.source_text,
            "normalized_text": self.normalized_text,
            "cells": [cell.to_dict() for cell in self.cells],
            "line_boundaries": list(self.line_boundaries),
            "cell_count": self.cell_count,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "engine": self.engine,
            "engine_version": self.engine_version,
            "table": self.table,
            "changed_by_normalization": self.changed_by_normalization,
        }


def unicode_braille_char_to_cell(
    output_index: int,
    cell_index: int,
    char: str,
) -> tuple[BrailleCell | None, TranslationDiagnostic | None]:
    """แปลงตัวอักษรหนึ่งตัวจากผลลัพธ์ดิบของ translator (คาดว่าเป็น Unicode
    Braille U+2800-U+28FF) เป็น BrailleCell หนึ่งเซลล์

    - `output_index`: ตำแหน่งของ char ในสตริงผลลัพธ์ดิบ (สำหรับ diagnostic)
    - `cell_index`: index ที่จะกำหนดให้ BrailleCell หากสร้างสำเร็จ (ตำแหน่งใน
      ลำดับเซลล์รวมของทั้งคำขอ ไม่ใช่ตำแหน่งในสตริงดิบ)

    คืนค่า (cell, diagnostic) - อย่างใดอย่างหนึ่งอาจเป็น None:
      - นอกช่วง Unicode Braille ทั้งหมด (ไม่ใช่ผลลัพธ์เบรลล์เลย): (None, ERROR)
      - มี dot 7/8 ติดมา: (cell จาก 6 บิตล่างเท่านั้น, WARNING) - ไม่ทิ้งเงียบ ๆ
      - ปกติ (dot 1-6 เท่านั้น): (cell, None)
    """
    codepoint = ord(char)
    if not (BRAILLE_UNICODE_BASE <= codepoint <= BRAILLE_UNICODE_MAX):
        return None, TranslationDiagnostic(
            severity=DiagnosticSeverity.ERROR,
            code="non_braille_output",
            description=(
                f"พบตัวอักษรที่ไม่ใช่ Unicode Braille (U+2800-U+28FF) ในผลลัพธ์ดิบจาก "
                f"translator ที่ตำแหน่ง {output_index}: {char!r} (U+{codepoint:04X})"
            ),
            source_index=output_index,
            character=char,
        )

    bits = codepoint - BRAILLE_UNICODE_BASE
    six_dot_bits = bits & SIX_DOT_MASK
    extra_dots = bits & DOTS_7_8_MASK

    cell = make_cell(cell_index, six_dot_bits)

    if extra_dots:
        extra_dot_numbers = [d for d in (7, 8) if extra_dots & (1 << (d - 1))]
        diagnostic = TranslationDiagnostic(
            severity=DiagnosticSeverity.WARNING,
            code="unsupported_dots_7_or_8",
            description=(
                f"ผลลัพธ์จาก translator ที่ตำแหน่ง {output_index} มี dot "
                f"{'/'.join(str(d) for d in extra_dot_numbers)} ซึ่งฮาร์ดแวร์ต้นแบบนี้ "
                "รองรับเฉพาะเซลล์ 6 จุด (dot 1-6) เท่านั้น จึงถูกตัดออกจากเซลล์นี้ "
                "(ไม่ได้ถูกละทิ้งแบบไม่แจ้งเตือน)"
            ),
            source_index=output_index,
            character=char,
        )
        return cell, diagnostic

    return cell, None


def convert_unicode_braille_string(
    raw_output: str,
    *,
    start_cell_index: int = 0,
) -> tuple[list[BrailleCell], list[TranslationDiagnostic]]:
    """แปลงผลลัพธ์ดิบทั้งสตริงจาก translator (คาดว่าเป็น Unicode Braille ล้วน)
    เป็นลิสต์ BrailleCell + ลิสต์ TranslationDiagnostic

    ไม่สมมติว่าจำนวนเซลล์ผลลัพธ์เท่ากับจำนวนตัวอักษรอินพุต (translator อาจสร้าง
    หลายเซลล์จากตัวอักษรต้นทางเดียว เช่น capital sign, number sign) - ฟังก์ชันนี้
    เพียงแค่ตีความสตริงผลลัพธ์ดิบทีละตัวอักษรเท่านั้น
    """
    cells: list[BrailleCell] = []
    diagnostics: list[TranslationDiagnostic] = []

    for output_index, char in enumerate(raw_output):
        cell, diagnostic = unicode_braille_char_to_cell(output_index, start_cell_index + len(cells), char)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
        if cell is not None:
            cells.append(cell)

    return cells, diagnostics
