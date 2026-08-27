# Skill Instructions & Guidelines

## 1. Project Standards & Rules

### 1.1 Braille Translation Fallback Rule
- **Rule**: If Liblouis C library binary or `louis` Python package is not available on the server, the system MUST fallback gracefully to `LegacyDictionaryTranslator` so that user text can still be translated without throwing a 503 error.

### 1.2 UI Theme & Color Contrast Rule
- **Rule**: Light-background containers inside the dark theme (such as `.hardware-warning`, `.hardware-optin`, `.hardware-verify`) MUST explicitly define dark font colors (`color: #0f172a;`) for all text, labels, inputs, options, and summary headers to maintain high contrast and readability.
