# Task Graph

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

- [x] **Task 7**: Implement 3-Second Live Countdown Badge and Dual Display (ESP32 + 6-Dot Matrix) Sync
    - *Files*: `c:/Users/kt856/Downloads/jumpb/templates/index.html`, `c:/Users/kt856/Downloads/jumpb/static/script.js`
    - *Logic/Target*: Add a live countdown badge (`#hardwareCountdownBadge`) to the character card, update 6-dot matrix in sync with Serial outputs, and auto-enable hardware mode on connect.
    - *Why*: Gives users visual countdown feedback (3s -> 2s -> 1s) and simultaneous dual-display (ESP32 hardware + 6-dot UI matrix).
    - *Verification*: **[AUTONOMOUS]** Inspect `templates/index.html` and `static/script.js` for `#hardwareCountdownBadge` countdown interval logic and dual display sync.

- [x] **Task 8**: Implement Automatic Hardware Connect on Page Load and Clean Up Top Manual Controls UI
    - *Files*: `c:/Users/kt856/Downloads/jumpb/templates/index.html`, `c:/Users/kt856/Downloads/jumpb/static/script.js`
    - *Logic/Target*: Automatically connect COM3 / active port and enable hardware mode in `initApp()`, while hiding redundant top manual port configuration UI for a clean, direct user experience.
    - *Why*: Streamlines the application so users can immediately translate and play Braille directly on ESP32 hardware without manual setup steps.
    - *Verification*: **[AUTONOMOUS]** Inspect `static/script.js` and `templates/index.html` for auto-connection on init and cleaned top UI controls.

- [x] **Task 9**: Fix JS ReferenceError and Ensure Seamless Cell Countdown Transition
    - *Files*: `c:/Users/kt856/Downloads/jumpb/static/script.js`
    - *Logic/Target*: Fix undefined `data` variable in `hardwareConnectBtn` handler causing JS crash, and harden `ensureHardwareSessionActive` so cell playback advances continuously through all characters.
    - *Why*: Resolves UI freeze at '⏱️ กำลังเปลี่ยนคำ...' by preventing JS exceptions and ensuring hardware session is initialized on play.
    - *Verification*: **[AUTONOMOUS]** Inspect `static/script.js` for data declaration fix and robust `ensureHardwareSessionActive`.

- [x] **Task 10**: Add Direct Text Translation Input Box for Easy Testing & Hardware Debugging
    - *Files*: `c:/Users/kt856/Downloads/jumpb/templates/index.html`, `c:/Users/kt856/Downloads/jumpb/static/script.js`
    - *Logic/Target*: Add `#directTextInput` and `#directTranslateBtn` allowing users/developers to type text directly (e.g. "ABC", "ทดสอบ") and click translate without needing an image file upload.
    - *Why*: Provides instant text-to-braille hardware testing capability directly on the web application.
    - *Verification*: **[AUTONOMOUS]** Inspect `templates/index.html` and `static/script.js` for direct text input elements and translation handler.

- [x] **Task 11**: Add Tab Switcher between Image OCR and Direct Text Input
    - *Files*: `c:/Users/kt856/Downloads/jumpb/templates/index.html`, `c:/Users/kt856/Downloads/jumpb/static/script.js`
    - *Logic/Target*: Add Tab buttons (`#modeTabImage` and `#modeTabText`) allowing users to easily switch between uploading an image file or typing text directly into a text area.
    - *Why*: Gives users intuitive options to either upload images or type text directly for translation and hardware testing.
    - *Verification*: **[AUTONOMOUS]** Inspect `templates/index.html` and `static/script.js` for tab switcher buttons and panel toggling handlers.

- [x] **Task 12**: Fix TypeError Illegal Invocation in BraillePlaybackController and Add Real-Time Hardware Log Box
    - *Files*: `c:/Users/kt856/Downloads/jumpb/static/braille_playback.js`, `c:/Users/kt856/Downloads/jumpb/templates/index.html`, `c:/Users/kt856/Downloads/jumpb/static/script.js`
    - *Logic/Target*: Wrap setTimeout/clearTimeout in arrow functions in `braille_playback.js` constructor to fix native `TypeError: Illegal invocation` exception, and add a real-time timestamped log console (`#hardwareLogList`) to the hardware section.
    - *Why*: Allows continuous character playback to step smoothly from cell 1 to cell N while giving full real-time log transparency for user testing.
    - *Verification*: **[AUTONOMOUS]** Inspect `braille_playback.js` for wrapped setTimeout and `index.html` for `#hardwareLogList` console.

- [x] **Task 13**: Remove Misleading 'fa-font' Icon and Enhance Hardware Current Character Display Badge
    - *Files*: `c:/Users/kt856/Downloads/jumpb/templates/index.html`, `c:/Users/kt856/Downloads/jumpb/static/script.js`
    - *Logic/Target*: Replace FontAwesome `fa-font` (which renders as a static letter 'A') with emoji `🔤 แสดงผลตัวอักษรบน ESP32:`, and format `#hardwareCurrentCharDisplay` with clear, bold character styling.
    - *Why*: Eliminates confusion where users thought the system was stuck displaying 'A' for every character due to the 'fa-font' icon.
    - *Verification*: **[AUTONOMOUS]** Inspect `templates/index.html` for replaced icon and `script.js` for updated char badge text.
