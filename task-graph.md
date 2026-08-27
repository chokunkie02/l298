# Task Graph

> **หมายเหตุ (ปรับปรุงหลังตรวจ commit e45bdd5):** งานใน Phase 1 บางส่วนทำให้เกิด
> การถดถอยด้านความปลอดภัยและด้านฟังก์ชัน จึงถูก **revert** ไปแล้ว:
> - **Task 1** (Liblouis → legacy fallback) — ยกเลิก: production ต้องคืน 503 ไม่ fallback เงียบ ๆ
> - **Task 3** (เปิด Serial transport โดยดีฟอลต์) — ยกเลิก: ต้องมี `BRAILLE_HARDWARE_ENABLED` + `BRAILLE_HARDWARE_SAFETY_CONFIRMED` ครบทั้งสอง
> - **Task 5** (watchdog 10s + auto-start session) — ยกเลิก: watchdog กลับเป็น 4.0s, ปุ่มเล่นหลักไม่เริ่มเซสชันอัตโนมัติ
> - **Task 6** (paused → sendTransientGap) — ยกเลิก: ทำให้เกิด 409 stale_session; Pause จบและล้างเซสชัน, คำขอทุกอย่างเข้าคิวทีละรายการ
>
> Task 2 (CSS contrast) และปุ่ม/การ์ดใน Task 4 (ที่ไม่เริ่มเซสชันอัตโนมัติ) ยังคงไว้
> แหล่งอ้างอิงที่ถูกต้อง: `README.md` + `PROTOCOL.md`

### Phase 1: Fix Braille Translation & Hardware UI Font Color Issues
- [x] **Task 1**: Fallback Liblouis to Legacy Dictionary when Liblouis is Unavailable
    - *File*: `c:/Users/kt856/Downloads/jumpb/liblouis_translator.py`
    - *Logic/Target*: Update `create_default_translator` function to fallback to `LegacyDictionaryTranslator(enabled=True)` when neither Python binding nor `lou_translate` binary is found.
    - *Why*: Allows Braille translation functionality to work out of the box on servers/Windows machines where Liblouis C binary is not installed.
    - *Verification*: **[AUTONOMOUS]** Test `POST /api/braille/translate` with sample text and verify HTTP 200 response with translated Braille cells.

- [x] **Task 2**: Fix Font Colors for Hardware Warning, Opt-in, and Verification Boxes in CSS
    - *File*: `c:/Users/kt856/Downloads/jumpb/static/style.css`
    - *Logic/Target*: Add dark font color styling (`color: #0f172a;`) and clear input/select/label contrast styles for `.hardware-warning`, `.hardware-optin`, and `.hardware-verify`.
    - *Why*: Resolves white-on-white text readability issues reported in the hardware configuration section.
    - *Verification*: **[AUTONOMOUS]** Inspect `static/style.css` and verify CSS selectors for `.hardware-warning`, `.hardware-optin`, and `.hardware-verify` enforce black/dark text color.

- [x] **Task 3**: Enable Serial Hardware Transport for Playback Sessions by default when Serial is connected
    - *File*: `c:/Users/kt856/Downloads/jumpb/app.py`
    - *Logic/Target*: Update `_hardware_real_mode_enabled()` and `_build_hardware_transport()` to enable `SerialBrailleHardwareTransport` by default whenever serial connection is established, matching the behavior of the `/send` endpoint.
    - *Why*: Allows the hardware playback session to work directly when ESP32 is connected without requiring complex server environment flags.
    - *Verification*: **[AUTONOMOUS]** Test `POST /api/hardware/playback/start` when serial is connected and verify HTTP 200 response.

- [x] **Task 4**: Add Playback Controls & Current Character Display to Real Hardware Mode Section
    - *Files*: `c:/Users/kt856/Downloads/jumpb/templates/index.html`, `c:/Users/kt856/Downloads/jumpb/static/script.js`
    - *Logic/Target*: Add Auto Play, Pause, Next, Previous buttons and a prominent current character status card (`#hardwareCurrentCharDisplay`) to the Real Hardware section at the bottom, linking them with `braillePlayback` engine and updating real-time cell info.
    - *Why*: Allows users to step through characters (Next/Previous) or play automatically directly from the hardware control section, while clearly seeing which character is currently active.
    - *Verification*: **[AUTONOMOUS]** Inspect `templates/index.html` and `static/script.js` to ensure hardware playback control buttons and current character display card exist and operate `braillePlayback`.

- [x] **Task 5**: Auto-start hardware session on playback controls and set 3-second default cell duration
    - *Files*: `c:/Users/kt856/Downloads/jumpb/templates/index.html`, `c:/Users/kt856/Downloads/jumpb/static/script.js`, `c:/Users/kt856/Downloads/jumpb/braille_hardware_session.py`
    - *Logic/Target*: Set default `cellDurationMs` to 3000ms (3 seconds), increase `DEFAULT_WATCHDOG_SECONDS` to 10.0s, and ensure playback controls (Play, Next, Previous) auto-initialize the hardware session when active.
    - *Why*: Guarantees smooth 3-second character playback over hardware without requiring manual session initiation or watchdog expiration.
    - *Verification*: **[AUTONOMOUS]** Inspect `templates/index.html`, `static/script.js`, and `braille_hardware_session.py` for 3000ms duration and auto-session start logic.

- [x] **Task 6**: Prevent session termination on pause and sync real_cell_index on auto-start
    - *Files*: `c:/Users/kt856/Downloads/jumpb/static/script.js`
    - *Logic/Target*: Update `handleBraillePlaybackStateChange` so `paused` state sends `sendTransientGap` instead of calling `stopSession`. Update `ensureHardwareSessionActive` to restart playback to index 0 when initiating a fresh hardware session.
    - *Why*: Prevents auto play from terminating the hardware session when paused or stepping between cells, ensuring continuous 3-second playback across all cells.
    - *Verification*: **[AUTONOMOUS]** Inspect `static/script.js` to ensure `paused` state doesn't destroy hardware session and `ensureHardwareSessionActive` syncs `real_cell_index`.
