"""ตัวปรับต่อ (adapter) ระหว่าง braille_translation.BrailleTranslatorBackend
กับ Liblouis จริง (https://liblouis.io/) - engine การแปลอักษรเบรลล์ production
ของ Step 4

**Liblouis ไม่ได้เป็น Python package ที่ pip install แล้วใช้งานได้ทันที** ต้อง
ติดตั้งไลบรารีระบบ (C library) ก่อนเสมอ - ดูวิธีติดตั้งใน README.md หัวข้อ
"การแปลข้อความเป็นอักษรเบรลล์" โมดูลนี้**ไม่ดาวน์โหลด/คอมไพล์/ติดตั้ง/แนบ
(vendor) Liblouis ให้อัตโนมัติ** และ**ไม่รัน Homebrew หรือคำสั่งติดตั้งระบบใด ๆ
เองโดยไม่ได้รับอนุญาตจากผู้ใช้ก่อน**

**การเลือก adapter**: มีสองวิธีเชื่อมต่อ Liblouis จาก Python -
  1. Python binding อย่างเป็นทางการ (`import louis`) - เรียกใช้ในโพรเซสเดียวกัน
     โดยตรง ไม่มี subprocess, ไม่มีความเสี่ยงเรื่อง shell/argument escaping,
     เร็วกว่า, ได้ exception ที่มีรายละเอียดตรงกว่า
  2. คำสั่งบรรทัดคำสั่ง `lou_translate` (มากับแพ็กเกจ liblouis ของระบบ) - ต้อง
     เรียกผ่าน subprocess

โมดูลนี้**เลือก Python binding ก่อนเสมอถ้ามี** เพราะเป็น adapter ที่เล็กและ
ปลอดภัยกว่า (ไม่ต้อง spawn process, ไม่ต้อง escape argument, ไม่ต้องจัดการ
timeout ของ subprocess) จะใช้ CLI adapter (`lou_translate`) เป็นทางเลือกสำรอง
เฉพาะเมื่อไม่มี Python binding ติดตั้งแต่มี Liblouis ระดับระบบอยู่เท่านั้น

**สถานะการยืนยัน**: CLI adapter (`LiblouisSubprocessAdapter`) ได้ทดสอบกับ
Liblouis 3.38.0 จริงแล้ว (ติดตั้งผ่าน Homebrew) รวมถึงพบและแก้ปัญหา encoding
ที่ `lou_translate` ต้องระบุ `-d unicode.dis` อย่างชัดเจนจึงจะคืน Unicode
Braille (ดู UNICODE_DISPLAY_TABLE และ LiblouisSubprocessAdapter) ผลลัพธ์ที่
ยืนยันแล้วยืนยันเพียงว่า**การเชื่อมต่อและการเข้ารหัส Unicode ทำงานถูกต้อง**
**ไม่ได้ยืนยันความถูกต้องทางภาษาศาสตร์ของอักษรเบรลล์ไทยที่ได้แต่อย่างใด** ยังคง
ต้องให้ผู้เชี่ยวชาญ/ผู้อ่านเบรลล์ไทยที่มีคุณสมบัติตรวจสอบเทียบกับคู่มืออักษร
เบรลล์ไทยก่อนใช้งานจริงเสมอ

`LiblouisPythonAdapter` (`import louis`) เขียนขึ้นตาม API ที่ liblouis ประกาศ
ต่อสาธารณะ (`louis.translateString`, `louis.version`) แต่**ยังไม่เคยถูกรัน
ทดสอบกับ Python binding จริง** เพราะเครื่องที่พัฒนา/ทดสอบนี้ติดตั้งเฉพาะ CLI
tools ผ่าน Homebrew เท่านั้น ยังไม่มี python package `louis` ติดตั้งอยู่ ผู้ใช้
ที่ติดตั้ง Python binding ควรรัน integration test ที่
tests/test_liblouis_integration.py เพื่อยืนยันความเข้ากันได้ของ adapter นี้
ก่อนใช้งานจริงเช่นกัน
"""

from __future__ import annotations

import importlib.util
import logging
import shutil
import subprocess
from dataclasses import dataclass

from braille_translation import (
    BrailleTranslationError,
    InternalTranslationError,
    TranslationTimeoutError,
)

DEFAULT_THAI_TABLE = "th-g1.utb"
DEFAULT_SUBPROCESS_TIMEOUT_SECONDS = 10.0

# ตาราง display ที่บังคับให้ lou_translate คืนผลลัพธ์เป็น Unicode Braille
# (U+2800-U+28FF) เสมอ - ยืนยันแล้วจริงกับ Liblouis 3.38.0 (ติดตั้งผ่าน
# Homebrew): ไม่ระบุ -d จะได้ข้อความ "hello" กลับมาเฉย ๆ (ไม่ใช่เบรลล์เลย)
# เพราะ lou_translate ใช้ display table ค่าเริ่มต้นที่ไม่เหมาะกับ output ที่เรา
# ต้องการ ส่วน `lou_translate --help` เองก็แนะนำให้ระบุ display table เสมอ
# เพื่อความชัดเจนและแน่นอนของผลลัพธ์ ("For clarity and reliability, it is
# recommended to always make the display table explicit.")
UNICODE_DISPLAY_TABLE = "unicode.dis"

_LOU_TRANSLATE_CANDIDATES = ("lou_translate",)
_LOU_CHECKTABLE_CANDIDATES = ("lou_checktable",)

logger = logging.getLogger(__name__)


def _python_binding_module_available() -> bool:
    """ตรวจแบบเบา (ไม่ import จริง) ว่ามี python package ชื่อ `louis` ติดตั้งอยู่
    หรือไม่ - นี่คือชื่อ module อย่างเป็นทางการของ Liblouis Python binding
    (มาจาก liblouis เอง ไม่ใช่ PyPI package อื่นที่ชื่อคล้ายกัน)
    """
    try:
        return importlib.util.find_spec("louis") is not None
    except (ImportError, ValueError):
        return False


def _cli_tool_path(candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


class LiblouisPythonAdapter:
    """Adapter ที่เรียก Liblouis ผ่าน Python binding อย่างเป็นทางการ (`import
    louis`) - ทำงานในโพรเซสเดียวกัน ไม่มี subprocess

    หมายเหตุความไม่แน่นอนของ API: liblouis python binding เวอร์ชันต่าง ๆ อาจมี/
    ไม่มีฟังก์ชัน `checkTable` เท่ากันหมด adapter นี้ตรวจด้วย `hasattr` ก่อนเรียก
    เสมอ ถ้าไม่มีจะ fallback ไปตรวจด้วยการแปลข้อความสั้น ๆ แทน (ดู check_table())
    """

    def __init__(self, table: str = DEFAULT_THAI_TABLE) -> None:
        self._table = table
        self._module = None

    def _get_module(self):
        if self._module is None:
            import louis  # นำเข้าตอนใช้งานจริงเท่านั้น (lazy) ไม่ import ที่ module level

            self._module = louis
        return self._module

    def engine_name(self) -> str:
        return "liblouis-python"

    def engine_version(self) -> str | None:
        if not self.is_available():
            return None
        try:
            module = self._get_module()
            version_fn = getattr(module, "version", None)
            if callable(version_fn):
                return str(version_fn())
        except Exception:  # noqa: BLE001 - ข้อมูลเวอร์ชันเป็นข้อมูลเสริม ไม่ควรทำให้ทั้งคำขอล้มเหลว
            logger.warning("ไม่สามารถอ่านเวอร์ชัน Liblouis python binding ได้", exc_info=True)
        return "unknown"

    def table_name(self) -> str:
        return self._table

    def is_available(self) -> bool:
        return _python_binding_module_available()

    def check_table(self) -> bool | None:
        if not self.is_available():
            return None
        try:
            module = self._get_module()
        except Exception:  # noqa: BLE001
            return False

        check_fn = getattr(module, "checkTable", None)
        if callable(check_fn):
            try:
                result = check_fn([self._table])
                return bool(result)
            except Exception:  # noqa: BLE001
                logger.warning("louis.checkTable() ล้มเหลว ถือว่าตารางใช้งานไม่ได้", exc_info=True)
                return False

        # binding เวอร์ชันนี้ไม่มี checkTable - ตรวจแบบสำรองด้วยการแปลข้อความสั้น ๆ
        try:
            translate_fn = getattr(module, "translateString")
            translate_fn([self._table], " ")
            return True
        except Exception:  # noqa: BLE001
            logger.warning("ตรวจสอบตารางด้วยการแปลข้อความสั้น ๆ ล้มเหลว ถือว่าตารางใช้งานไม่ได้", exc_info=True)
            return False

    def translate_line(self, line: str) -> str:
        module = self._get_module()
        try:
            translate_fn = getattr(module, "translateString")
            return str(translate_fn([self._table], line))
        except AttributeError as exc:
            raise InternalTranslationError(
                "Liblouis python binding รุ่นนี้ไม่มีฟังก์ชัน translateString ที่คาดไว้ "
                "กรุณาตรวจสอบเวอร์ชัน python binding ที่ติดตั้ง"
            ) from exc
        except BrailleTranslationError:
            raise
        except Exception as exc:  # noqa: BLE001 - ห่อ error ทั้งหมดจาก binding ไม่ให้หลุด traceback ดิบออกไป
            logger.error("Liblouis python binding แปลข้อความล้มเหลว", exc_info=True)
            raise InternalTranslationError(
                "Liblouis ไม่สามารถแปลข้อความนี้ได้ กรุณาลองอีกครั้งหรือรายงานปัญหา"
            ) from exc


class LiblouisSubprocessAdapter:
    """Adapter สำรองที่เรียก Liblouis ผ่านคำสั่งบรรทัดคำสั่ง `lou_translate`
    เมื่อไม่มี Python binding แต่มี Liblouis ระดับระบบติดตั้งอยู่

    คำสั่งที่เรียกจริง: `lou_translate -d unicode.dis <table>` (ข้อความเข้าทาง
    stdin) **ต้องระบุ `-d unicode.dis` เสมอ** - ยืนยันแล้วกับ Liblouis 3.38.0
    (Homebrew) ว่าถ้าไม่ระบุ display table, `lou_translate` จะคืนข้อความเดิม
    กลับมาเฉย ๆ (ไม่ใช่ Unicode Braille) ทำให้ตีความเป็นเซลล์ไม่ได้เลยและถูก
    รายงานเป็น non_braille_output ทุกตัวอักษร ดูค่าคงที่ UNICODE_DISPLAY_TABLE

    ความปลอดภัยของ subprocess:
      - เรียกด้วย argument list เสมอ (ไม่เคยประกอบเป็น shell string)
      - shell=False เสมอ (ค่า default ของ subprocess.run อยู่แล้ว แต่ระบุไว้
        อย่างชัดเจนเพื่อกันการเปลี่ยนแปลงโดยไม่ตั้งใจในอนาคต)
      - มี timeout เสมอ (ค่าเริ่มต้น DEFAULT_SUBPROCESS_TIMEOUT_SECONDS)
      - ข้อความผ่านเข้าทาง stdin ไม่ใช่ argument (กันปัญหาความยาว argument และ
        กันข้อความหลุดไปตีความเป็น flag) - "-d", "unicode.dis", และชื่อตาราง
        เป็นค่าคงที่/config เท่านั้น ไม่มีข้อความผู้ใช้ปนอยู่ใน argv เลย
      - ตรวจขนาดข้อความไว้แล้วที่ชั้น normalize_text_for_braille ก่อนถึงจุดนี้
      - stderr ถูก capture แล้ว log เท่านั้น ไม่ถูกส่งกลับไปยัง browser ตรง ๆ
    """

    def __init__(
        self,
        table: str = DEFAULT_THAI_TABLE,
        timeout: float = DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
    ) -> None:
        self._table = table
        self._timeout = timeout

    def engine_name(self) -> str:
        return "liblouis-cli"

    def engine_version(self) -> str | None:
        path = _cli_tool_path(_LOU_TRANSLATE_CANDIDATES)
        if not path:
            return None
        try:
            completed = subprocess.run(
                [path, "--version"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                shell=False,
                check=False,
            )
            output = (completed.stdout or completed.stderr or "").strip()
            return output.splitlines()[0] if output else "unknown"
        except Exception:  # noqa: BLE001
            logger.warning("ไม่สามารถอ่านเวอร์ชัน lou_translate ได้", exc_info=True)
            return "unknown"

    def table_name(self) -> str:
        return self._table

    def is_available(self) -> bool:
        return _cli_tool_path(_LOU_TRANSLATE_CANDIDATES) is not None

    def check_table(self) -> bool | None:
        if not self.is_available():
            return None

        checktable_path = _cli_tool_path(_LOU_CHECKTABLE_CANDIDATES)
        if checktable_path:
            try:
                completed = subprocess.run(
                    [checktable_path, self._table],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    shell=False,
                    check=False,
                )
                return completed.returncode == 0
            except Exception:  # noqa: BLE001
                logger.warning("lou_checktable ล้มเหลว ถือว่าตารางใช้งานไม่ได้", exc_info=True)
                return False

        # ไม่มี lou_checktable ในเครื่องนี้ - ตรวจแบบสำรองด้วยการแปลข้อความสั้น ๆ
        try:
            self.translate_line(" ")
            return True
        except Exception:  # noqa: BLE001
            return False

    def translate_line(self, line: str) -> str:
        path = _cli_tool_path(_LOU_TRANSLATE_CANDIDATES)
        if not path:
            raise InternalTranslationError("ไม่พบคำสั่ง lou_translate ในเครื่องนี้")

        try:
            completed = subprocess.run(
                [path, "-d", UNICODE_DISPLAY_TABLE, self._table],
                input=line,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TranslationTimeoutError(
                f"การแปลข้อความใช้เวลานานเกิน {self._timeout} วินาที กรุณาลองข้อความที่สั้นลง"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.error("เรียก lou_translate ล้มเหลว", exc_info=True)
            raise InternalTranslationError("ไม่สามารถเรียกใช้เครื่องมือแปลอักษรเบรลล์ได้") from exc

        if completed.returncode != 0:
            # stderr ดิบถูก log ไว้เพื่อ debug เท่านั้น ไม่ส่งกลับไปยัง browser
            logger.error("lou_translate คืนค่า error code %s: %s", completed.returncode, completed.stderr)
            raise InternalTranslationError(
                "เครื่องมือแปลอักษรเบรลล์คืนค่าข้อผิดพลาด กรุณาตรวจสอบการตั้งค่า Liblouis"
            )

        return completed.stdout.rstrip("\n")


def create_default_translator(
    table: str = DEFAULT_THAI_TABLE,
    timeout: float = DEFAULT_SUBPROCESS_TIMEOUT_SECONDS,
):
    """เลือก Liblouis adapter ที่ดีที่สุดที่หาได้ในเครื่องนี้ (Python binding
    ก่อนเสมอถ้ามี ไม่งั้นใช้ CLI) คืน UnavailableBrailleTranslator พร้อมเหตุผล
    ชัดเจนถ้าไม่พบทั้งสองแบบ - ไม่เคย fallback ไปยัง legacy dictionary
    """
    from braille_translation import UnavailableBrailleTranslator

    if _python_binding_module_available():
        return LiblouisPythonAdapter(table=table)

    if _cli_tool_path(_LOU_TRANSLATE_CANDIDATES) is not None:
        return LiblouisSubprocessAdapter(table=table, timeout=timeout)

    return UnavailableBrailleTranslator(
        table=table,
        reason=(
            "ไม่พบ Liblouis ในเครื่องนี้ (ไม่มีทั้ง Python binding 'import louis' "
            "และคำสั่ง lou_translate) กรุณาติดตั้ง Liblouis ระดับระบบก่อน "
            "ดูวิธีติดตั้งใน README.md หัวข้อ 'การแปลข้อความเป็นอักษรเบรลล์'"
        ),
    )
