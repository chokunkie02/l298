# Skill Instructions & Guidelines

> **หมายเหตุ (ปรับปรุงหลัง commit e45bdd5):** เอกสารนี้เป็นบันทึกงานเก่า
> **ไม่ใช่แหล่งอ้างอิงที่มีอำนาจ** แหล่งอ้างอิงที่ถูกต้องคือ `README.md` หัวข้อ
> "การเชื่อมต่อฮาร์ดแวร์แบบมีการ์ด" และ `PROTOCOL.md` ข้อ 1.1 ด้านล่าง
> **ถูกยกเลิก** (ดูเหตุผลด้านล่าง)

## 1. Project Standards & Rules

### 1.1 Braille Translation Fallback Rule — **ยกเลิกแล้ว (SUPERSEDED)**
- ~~**Rule**: If Liblouis C library binary or `louis` Python package is not available on the server, the system MUST fallback gracefully to `LegacyDictionaryTranslator`~~
- **กฎที่ใช้จริง**: production **ห้าม** fallback ไป `LegacyDictionaryTranslator`
  โดยอัตโนมัติ (พจนานุกรมนั้นยังไม่ได้ตรวจสอบความถูกต้อง) หากไม่พบ Liblouis
  ทั้ง Python binding และ CLI → คืน `UnavailableBrailleTranslator` และ API ตอบ
  `503 translator_unavailable` การแปลผิดเงียบ ๆ อันตรายกว่าการแจ้ง error ชัดเจน
  `LegacyDictionaryTranslator` เป็น opt-in สำหรับทดสอบด้วยมือระหว่างพัฒนาเท่านั้น

### 1.2 UI Theme & Color Contrast Rule
- **Rule**: Light-background containers inside the dark theme (such as `.hardware-warning`, `.hardware-optin`, `.hardware-verify`) MUST explicitly define dark font colors (`color: #0f172a;`) for all text, labels, inputs, options, and summary headers to maintain high contrast and readability.
