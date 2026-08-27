# Architecture

## Directory Structure
```text
├── app.py                            # Flask Web Application routes and API endpoints
├── braille_hardware.py               # ESP32 Serial Hardware Transport abstraction
├── braille_hardware_session.py       # Hardware playback session & watchdog management
├── braille_models.py                 # Core domain models (BrailleCell, BrailleTranslation)
├── braille_translation.py            # Text-to-Braille orchestration and normalization
├── legacy_braille_dictionary.py      # Hardcoded Thai/English 6-dot dictionary translator
├── liblouis_translator.py            # Liblouis C-library / Python binding adapter (NO automatic legacy fallback; returns UnavailableBrailleTranslator -> HTTP 503 when Liblouis is absent)
├── ocr_service.py                    # EasyOCR service wrapper
├── image_preprocessing.py            # Image decoding and preprocessing utilities
├── static/
│   ├── braille_hardware.js           # Frontend hardware controls and port selection
│   ├── braille_playback.js           # Simulated & hardware Braille playback engine
│   ├── script.js                     # Main application logic (OCR, translation)
│   └── style.css                     # Responsive modern dark-theme styles
├── templates/
│   └── index.html                    # Main UI HTML layout
└── tests/                            # Unit and integration test suite
```

## Data Flow / Translation Pipeline

```text
[User Input / OCR Text]
         │
         ▼
[normalize_text_for_braille()]
         │
         ▼
[create_default_translator()] ── (Liblouis Available?) ──▶ [Liblouis Adapter]
         │                                                      │
         │ (No Liblouis)                                        │
         ▼                                                      │
[UnavailableBrailleTranslator] ── API returns HTTP 503          │
   translator_unavailable  (NO automatic legacy fallback)       │
                                                                ▼
                                                   [BrailleTranslation Output]
```

`LegacyDictionaryTranslator` เป็น opt-in สำหรับทดสอบด้วยมือระหว่างพัฒนาเท่านั้น
ไม่ถูกเลือกโดยอัตโนมัติในเส้นทางการแปล OCR (ดู `liblouis_translator.create_default_translator`)
