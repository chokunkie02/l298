"""ตรรกะการแปลข้อความเป็นอักษรเบรลล์ 6 จุด (Step 4): normalize ข้อความ, เรียก
translator backend ทีละบรรทัด, ประกอบผลลัพธ์เป็น BrailleTranslation

โมดูลนี้ไม่ import Flask, EasyOCR, Serial, หรือ ESP32 เลย - แยกจาก app.py โดย
เจตนา เพื่อให้ทดสอบ orchestration ทั้งหมดได้โดยไม่ต้องมี Liblouis ติดตั้งจริง
(ใช้ FakeBrailleTranslator แทนได้ผ่าน dependency injection)

**สถาปัตยกรรม**: `BrailleTranslatorBackend` เป็น protocol/interface ที่แยก
"วิธีแปลข้อความหนึ่งบรรทัดเป็น Unicode Braille ดิบ" ออกจาก orchestration logic
(normalize, แบ่งบรรทัด, ตีความผลลัพธ์ดิบเป็น BrailleCell, จัดการ error) เพื่อไม่
ให้แอปพลิเคชันผูกติดกับ Liblouis โดยตรง - implementation จริงอยู่ใน
liblouis_translator.py (แยกไฟล์ เพราะต้องยุ่งกับ subprocess/import ภายนอก)
ส่วนไฟล์นี้มีเฉพาะ FakeBrailleTranslator (สำหรับเทสต์) และ
UnavailableBrailleTranslator (fallback ที่ปฏิเสธคำขอชัดเจนเมื่อไม่มี engine ใช้ได้)

**ห้าม fallback จาก Liblouis ไปยัง legacy dictionary แบบเงียบ ๆ โดยเด็ดขาด** -
ถ้า Liblouis ไม่พร้อมใช้งาน ต้องคืน error แบบมีโครงสร้างเท่านั้น (ดู
TranslatorUnavailableError) ไม่ใช่ผลลัพธ์จาก dictionary ที่ยังไม่ได้ตรวจสอบ
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from braille_models import (
    BrailleTranslation,
    DiagnosticSeverity,
    TranslationDiagnostic,
    convert_unicode_braille_string,
)

DEFAULT_MAX_TEXT_LENGTH = 5000


class BrailleTranslationError(RuntimeError):
    """คลาสฐานของข้อผิดพลาดทั้งหมดในการแปลข้อความเป็นอักษรเบรลล์"""


class InvalidInputTypeError(BrailleTranslationError):
    """เกิดขึ้นเมื่อ text ที่ส่งมาไม่ใช่ str (เช่น None, number, list, dict)"""


class EmptyTextError(BrailleTranslationError):
    """เกิดขึ้นเมื่อข้อความว่างเปล่าหรือมีแต่ช่องว่าง/บรรทัดว่างล้วน"""


class TextTooLongError(BrailleTranslationError):
    """เกิดขึ้นเมื่อข้อความยาวเกิน max_length ที่กำหนด"""


class TranslatorUnavailableError(BrailleTranslationError):
    """เกิดขึ้นเมื่อไม่มี translator engine ใดพร้อมใช้งานเลยในเครื่องนี้

    ต้องไม่ fallback ไปใช้ legacy dictionary แบบเงียบ ๆ เมื่อเกิด error นี้
    """


class TableUnavailableError(BrailleTranslationError):
    """เกิดขึ้นเมื่อ translator engine พร้อมใช้งาน แต่ตารางที่ต้องการ (เช่น
    th-g1.utb) ไม่มีอยู่จริงหรือใช้งานไม่ได้
    """


class TranslationTimeoutError(BrailleTranslationError):
    """เกิดขึ้นเมื่อการแปลใช้เวลานานเกินกำหนด (โดยเฉพาะ subprocess adapter)"""


class InvalidTranslatorOutputError(BrailleTranslationError):
    """เกิดขึ้นเมื่อผลลัพธ์ดิบจาก translator ไม่ใช่ Unicode Braille ที่ใช้งาน
    ได้เลย (บรรทัดที่มีเนื้อหาจริงแต่แปลงเป็นเซลล์ที่ถูกต้องไม่ได้แม้แต่เซลล์เดียว)
    """


class InternalTranslationError(BrailleTranslationError):
    """เกิดขึ้นเมื่อ translator ล้มเหลวด้วยสาเหตุอื่นที่ไม่เข้าพวกข้างต้น (เช่น
    subprocess คืนค่า error code, exception ที่ไม่คาดคิดจาก python binding)
    ข้อความที่คืนให้ผู้ใช้ต้องไม่มี stack trace หรือ shell output ดิบปนอยู่
    """


# --- Normalization ------------------------------------------------------


@dataclass(frozen=True)
class NormalizedInput:
    """ผลลัพธ์ของการเตรียมข้อความก่อนแปล: normalize CRLF/CR, NFC, แบ่งบรรทัด"""

    original_text: str
    normalized_text: str
    lines: tuple[str, ...]
    changed_by_normalization: bool


def normalize_text_for_braille(
    text: Any,
    *,
    max_length: int = DEFAULT_MAX_TEXT_LENGTH,
) -> NormalizedInput:
    """เตรียมข้อความก่อนส่งเข้า translator - เป็นฟังก์ชันบริสุทธิ์ล้วน

    ลำดับการตรวจสอบ:
      1. ต้องเป็น str เท่านั้น (ปฏิเสธ None/number/list/dict ทันที)
      2. ความยาวดิบต้องไม่เกิน max_length (ตรวจก่อน normalize เพื่อผลลัพธ์ที่
         คาดเดาได้แน่นอน ไม่ขึ้นกับว่า NFC จะย่อความยาวหรือไม่)
      3. แปลง CRLF และ CR เดี่ยว ๆ เป็น LF
      4. ทำ Unicode NFC normalization
      5. ปฏิเสธถ้าข้อความว่างเปล่าหรือมีแต่ช่องว่าง/บรรทัดว่างล้วนหลัง normalize

    **ไม่แก้ไขตัวสะกดหรือเนื้อหาข้อความ OCR ใด ๆ ทั้งสิ้น** เก็บช่องว่างที่มี
    ความหมายไว้ครบ (ไม่ strip เนื้อหาจริง ใช้ .strip() เพื่อ "ตรวจสอบ" ว่าว่าง
    เปล่าหรือไม่เท่านั้น)
    """
    if not isinstance(text, str):
        raise InvalidInputTypeError(
            f"ข้อความต้องเป็นสตริง (string) เท่านั้น ได้รับชนิด {type(text).__name__}"
        )

    if len(text) > max_length:
        raise TextTooLongError(
            f"ข้อความยาวเกินกำหนด ({len(text):,} ตัวอักษร) สูงสุด {max_length:,} ตัวอักษรต่อคำขอ"
        )

    without_crlf = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = unicodedata.normalize("NFC", without_crlf)

    if not normalized.strip():
        raise EmptyTextError("ข้อความว่างเปล่าหรือมีแต่ช่องว่าง ไม่สามารถแปลงเป็นอักษรเบรลล์ได้")

    return NormalizedInput(
        original_text=text,
        normalized_text=normalized,
        lines=tuple(normalized.split("\n")),
        changed_by_normalization=(normalized != text),
    )


# --- Translator backend interface ---------------------------------------


@runtime_checkable
class BrailleTranslatorBackend(Protocol):
    """Interface ที่ orchestration (translate_text) เรียกใช้ - แยกจาก
    implementation จริง (Liblouis/fake) โดยสิ้นเชิง เพื่อ dependency injection
    """

    def engine_name(self) -> str: ...

    def engine_version(self) -> str | None: ...

    def table_name(self) -> str: ...

    def is_available(self) -> bool:
        """ตรวจแบบเบา (ไม่แปลจริง) ว่า engine นี้พร้อมใช้งานในเครื่องนี้หรือไม่"""
        ...

    def check_table(self) -> bool | None:
        """ตรวจว่าตารางที่กำหนดใช้งานได้จริงหรือไม่ คืนค่า None ถ้า backend นี้
        ไม่มีวิธีตรวจสอบแยกต่างหาก (orchestration จะข้ามการตรวจขั้นนี้)
        """
        ...

    def translate_line(self, line: str) -> str:
        """แปลข้อความหนึ่งบรรทัด (ไม่มี \\n ปน) เป็นสตริง Unicode Braille ดิบ

        ต้อง raise BrailleTranslationError subclass ที่เหมาะสมเมื่อล้มเหลว
        (TranslationTimeoutError, InternalTranslationError, ฯลฯ) ห้าม raise
        exception ทั่วไปที่ไม่ได้ห่อไว้
        """
        ...


class UnavailableBrailleTranslator:
    """Backend ตัวยืนพื้นเมื่อไม่มี engine ใดพร้อมใช้งานเลย - is_available()
    คืน False เสมอ และ translate_line() raise TranslatorUnavailableError ถ้า
    ถูกเรียกโดยตรง (ไม่ควรถูกเรียก เพราะ translate_text() ตรวจ is_available()
    ก่อนเสมอ) ทำหน้าที่เป็น "ป้ายบอกเหตุผล" ที่ชัดเจนแทนการ fallback ไป dict
    """

    def __init__(self, table: str, reason: str) -> None:
        self._table = table
        self._reason = reason

    def engine_name(self) -> str:
        return "unavailable"

    def engine_version(self) -> str | None:
        return None

    def table_name(self) -> str:
        return self._table

    def is_available(self) -> bool:
        return False

    def check_table(self) -> bool | None:
        return None

    def reason(self) -> str:
        return self._reason

    def translate_line(self, line: str) -> str:
        raise TranslatorUnavailableError(self._reason)


@dataclass
class FakeBrailleTranslator:
    """Translator backend แบบ deterministic สำหรับเทสต์ - ไม่ยุ่งกับ Liblouis
    หรือระบบไฟล์ใด ๆ เลย ผู้ใช้เทสต์กำหนดผลลัพธ์ดิบ (Unicode Braille) ที่ต้องการ
    ให้คืนสำหรับแต่ละบรรทัด input ผ่าน `line_outputs` (dict) หรือ `default_fn`

    ใช้แทน Liblouis จริงในเทสต์ทั้งหมดของ orchestration/API เพื่อไม่ต้อง
    ติดตั้ง Liblouis ในสภาพแวดล้อมทดสอบอัตโนมัติเลย
    """

    line_outputs: dict[str, str] | None = None
    default_output: str | None = None
    engine: str = "fake"
    version: str = "test"
    table: str = "fake-table.utb"
    available: bool = True
    table_valid: bool | None = True
    raise_on_translate: BaseException | None = None

    def engine_name(self) -> str:
        return self.engine

    def engine_version(self) -> str | None:
        return self.version

    def table_name(self) -> str:
        return self.table

    def is_available(self) -> bool:
        return self.available

    def check_table(self) -> bool | None:
        return self.table_valid

    def translate_line(self, line: str) -> str:
        if self.raise_on_translate is not None:
            raise self.raise_on_translate
        mapping = self.line_outputs or {}
        if line in mapping:
            return mapping[line]
        if self.default_output is not None:
            return self.default_output
        raise InternalTranslationError(
            f"FakeBrailleTranslator ไม่มีผลลัพธ์ที่กำหนดไว้สำหรับบรรทัด: {line!r} "
            "(ตั้งค่า line_outputs หรือ default_output ในเทสต์)"
        )


# --- Orchestration --------------------------------------------------------


def translate_text(
    text: Any,
    translator: BrailleTranslatorBackend,
    *,
    max_length: int = DEFAULT_MAX_TEXT_LENGTH,
) -> BrailleTranslation:
    """จุดรวมของการแปลข้อความเป็นอักษรเบรลล์หนึ่งคำขอ

    ลำดับการทำงาน: normalize -> ตรวจ translator พร้อมใช้งาน -> ตรวจตาราง (ถ้า
    ตรวจได้) -> แปลทีละบรรทัด -> ตีความผลลัพธ์ดิบเป็นเซลล์ -> ประกอบ
    BrailleTranslation พร้อม line_boundaries (ตำแหน่งเซลล์สะสมที่จบแต่ละบรรทัด
    ยกเว้นบรรทัดสุดท้าย)

    raise BrailleTranslationError subclass ที่เหมาะสมเสมอเมื่อล้มเหลว ไม่มี
    การ fallback ไปยัง legacy dictionary ใด ๆ ในฟังก์ชันนี้
    """
    normalized_input = normalize_text_for_braille(text, max_length=max_length)

    if not translator.is_available():
        raise TranslatorUnavailableError(
            f"เครื่องมือแปลอักษรเบรลล์ ({translator.engine_name()}) ไม่พร้อมใช้งานในเครื่องนี้ "
            "กรุณาติดตั้ง Liblouis และตาราง th-g1.utb (ดู README.md หัวข้อการแปลข้อความเป็นเบรลล์)"
        )

    table_check = translator.check_table()
    if table_check is False:
        raise TableUnavailableError(
            f"ไม่พบหรือไม่สามารถใช้ตาราง '{translator.table_name()}' ได้กับ "
            f"{translator.engine_name()} กรุณาตรวจสอบการติดตั้งตาราง Liblouis"
        )

    all_cells = []
    all_diagnostics: list[TranslationDiagnostic] = []
    line_boundaries: list[int] = []
    line_count = len(normalized_input.lines)

    for line_index, line in enumerate(normalized_input.lines):
        raw_output = "" if line == "" else translator.translate_line(line)

        cells, diagnostics = convert_unicode_braille_string(raw_output, start_cell_index=len(all_cells))

        if line.strip() and raw_output and not cells:
            # บรรทัดมีเนื้อหาจริงและ translator คืนผลลัพธ์ที่ไม่ว่างเปล่า แต่ตีความ
            # เป็นเซลล์เบรลล์ที่ถูกต้องไม่ได้แม้แต่เซลล์เดียว - นี่คือสัญญาณว่า
            # ผลลัพธ์ดิบใช้งานไม่ได้เลย (เช่น ตารางผิด, encoding ผิด) ไม่ใช่แค่มี
            # ตัวอักษรแปลกปนมาบางตัว จึงยกระดับเป็น error ทั้งคำขอแทนที่จะคืน
            # cell_count: 0 อย่างเข้าใจผิดว่า "แปลสำเร็จ"
            raise InvalidTranslatorOutputError(
                f"ผลลัพธ์ดิบจาก translator สำหรับบรรทัดที่ {line_index + 1} ไม่ใช่ Unicode "
                "Braille ที่ใช้งานได้เลยแม้แต่ตัวอักษรเดียว กรุณาตรวจสอบการตั้งค่า engine/ตาราง"
            )

        all_cells.extend(cells)
        all_diagnostics.extend(diagnostics)

        if line_index < line_count - 1:
            line_boundaries.append(len(all_cells))

    return BrailleTranslation(
        source_text=normalized_input.original_text,
        normalized_text=normalized_input.normalized_text,
        cells=tuple(all_cells),
        line_boundaries=tuple(line_boundaries),
        diagnostics=tuple(all_diagnostics),
        engine=translator.engine_name(),
        engine_version=translator.engine_version(),
        table=translator.table_name(),
        changed_by_normalization=normalized_input.changed_by_normalization,
    )


def translation_response_dict(translation: BrailleTranslation, *, sent_to_hardware: bool = False) -> dict[str, Any]:
    """ประกอบ dict สำหรับ JSON response ของ POST /api/braille/translate เมื่อ
    สำเร็จ ตรงตามรูปแบบที่ Step 4 กำหนด (ok, cells, cell_count, diagnostics,
    engine, table, sent_to_hardware, ...) - แยกจาก BrailleTranslation.to_dict()
    เพราะ "ok"/"sent_to_hardware" เป็นรายละเอียดระดับ API ไม่ใช่ระดับโดเมน
    """
    payload = translation.to_dict()
    payload["ok"] = True
    payload["sent_to_hardware"] = sent_to_hardware
    return payload
