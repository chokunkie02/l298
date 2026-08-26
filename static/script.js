/**
 * Braille LED Controller - Frontend Logic System
 */

document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const patternInput = document.getElementById('patternInput');
    const sendBtn = document.getElementById('sendBtn');
    const btnAllOn = document.getElementById('btnAllOn');
    const btnAllOff = document.getElementById('btnAllOff');
    const btnClear = document.getElementById('btnClear');
    const binaryPatternDisplay = document.getElementById('binaryPatternDisplay');
    
    const statusBadge = document.getElementById('statusBadge');
    const statusText = document.getElementById('statusText');
    const portSelect = document.getElementById('portSelect');
    const reconnectBtn = document.getElementById('reconnectBtn');
    
    const terminalLog = document.getElementById('terminalLog');
    const clearLogBtn = document.getElementById('clearLogBtn');
    const alphabetGrid = document.getElementById('alphabetGrid');

    // Accessible OCR workflow elements
    const ocrImageInput = document.getElementById('ocrImageInput');
    const readImageBtn = document.getElementById('readImageBtn');
    const ocrStatus = document.getElementById('ocrStatus');
    const ocrResultPanel = document.getElementById('ocrResultPanel');
    const ocrResultHeading = document.getElementById('ocrResultHeading');
    const ocrRecognizedText = document.getElementById('ocrRecognizedText');
    const ocrConfidenceSummary = document.getElementById('ocrConfidenceSummary');
    const ocrQualityWarnings = document.getElementById('ocrQualityWarnings');
    const listenAgainBtn = document.getElementById('listenAgainBtn');
    const confirmOcrBtn = document.getElementById('confirmOcrBtn');
    const chooseAnotherBtn = document.getElementById('chooseAnotherBtn');

    const speechSupported = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
    let recognizedText = '';
    let resultMayBeUnclear = false;
    let ocrProcessing = false;
    let speechRunId = 0;
    let hasPlayedSpeechOnce = false;
    let activeUtterances = [];
    let cachedVoices = [];

    const LISTEN_FIRST_LABEL = '<i class="fa-solid fa-volume-high" aria-hidden="true"></i> ฟังข้อความที่ตรวจพบ (Listen to detected text)';
    const LISTEN_AGAIN_LABEL = '<i class="fa-solid fa-volume-high" aria-hidden="true"></i> ฟังอีกครั้ง (Listen again)';
    const SPEECH_DONE_MESSAGE = 'อ่านจบแล้ว คุณสามารถยืนยัน ฟังอีกครั้ง หรือเลือกภาพใหม่ได้';
    const SPEECH_ERROR_MESSAGE = 'ไม่สามารถอ่านออกเสียงด้วยเบราว์เซอร์ได้ คุณสามารถใช้โปรแกรมอ่านหน้าจอ ยืนยัน หรือเลือกภาพใหม่ได้';

    // ข้อความคำเตือนคุณภาพภาพ: เป็นเพียง heuristic ไม่ใช่การรับประกันผล OCR
    // และต้องไม่ปิดกั้นการอ่านหรือยืนยันข้อความ (ดู image_preprocessing.py)
    const QUALITY_WARNING_MESSAGES = {
        dark: 'ภาพอาจมืดเกินไป กรุณาเพิ่มแสงหรือถ่ายใหม่',
        bright: 'ภาพอาจสว่างหรือมีแสงสะท้อนมากเกินไป กรุณาลดแสงหรือถ่ายใหม่',
        low_contrast: 'ภาพอาจมีความต่างของสีระหว่างตัวอักษรกับพื้นหลังน้อยเกินไป กรุณาถ่ายในที่ที่ตัวอักษรเห็นชัดเจนขึ้น',
        blurry: 'ภาพอาจเบลอ กรุณาถือกล้องให้นิ่งแล้วถ่ายใหม่',
    };
    const QUALITY_OK_MESSAGE = 'ภาพมีความคมชัดเพียงพอสำหรับการอ่านข้อความ';

    // Dot circles elements (1 to 6)
    const dots = {
        1: document.getElementById('dot1'),
        2: document.getElementById('dot2'),
        3: document.getElementById('dot3'),
        4: document.getElementById('dot4'),
        5: document.getElementById('dot5'),
        6: document.getElementById('dot6'),
    };

    // Client-side Thai & English Braille Mapping Dictionary
    const BRAILLE_DICT = {
        'ก': '110000', 'ข': '101000', 'ค': '100100', 'ง': '010110', 'จ': '110100',
        'ฉ': '101100', 'ช': '100111', 'ซ': '101001', 'ฌ': '010111', 'ญ': '011011',
        'ด': '100110', 'ต': '011010', 'ถ': '011100', 'ท': '011101', 'น': '101110',
        'บ': '111000', 'ป': '111100', 'ผ': '110010', 'ฝ': '110011', 'พ': '110110',
        'ฟ': '110101', 'ภ': '110111', 'ม': '101101', 'ย': '101111', 'ร': '111010',
        'ล': '111000', 'ว': '011101', 'ส': '011100', 'ห': '110010', 'อ': '011011',
        
        'A': '100000', 'B': '110000', 'C': '100100', 'D': '100110', 'E': '100010',
        'F': '110100', 'G': '110110', 'H': '110010', 'I': '010100', 'J': '010110',
        '1': '100000', '2': '110000', '3': '100100', '4': '100110', '5': '100010'
    };

    // Current State
    let currentPattern = "000000";

    // Initialize Page
    initApp();

    function initApp() {
        populateAlphabetKeyboard();
        checkConnectionStatus();
        updateVisualPreview("000000");
        initOcrWorkflow();

        // Set interval to poll status every 5 seconds
        setInterval(checkConnectionStatus, 5000);
    }

    // Accessible two-step OCR flow: choose image, hear result, then explicitly confirm.
    function initOcrWorkflow() {
        ocrImageInput.addEventListener('change', handleImageSelection);
        readImageBtn.addEventListener('click', processImage);
        listenAgainBtn.addEventListener('click', speakRecognizedText);
        confirmOcrBtn.addEventListener('click', confirmOcrResult);
        chooseAnotherBtn.addEventListener('click', chooseAnotherImage);

        window.addEventListener('beforeunload', stopSpeech);

        primeVoices();
        resetOcrResult();
    }

    // Robust voice loading: warm the cache immediately and keep it fresh as the
    // browser loads voices asynchronously, without ever blocking confirmation.
    function primeVoices() {
        if (!speechSupported) return;
        refreshVoiceCache();
        if (typeof window.speechSynthesis.addEventListener === 'function') {
            window.speechSynthesis.addEventListener('voiceschanged', refreshVoiceCache);
        } else {
            window.speechSynthesis.onvoiceschanged = refreshVoiceCache;
        }
    }

    function refreshVoiceCache() {
        if (!speechSupported) return;
        cachedVoices = window.speechSynthesis.getVoices() || [];
    }

    function setConfirmEnabled(enabled) {
        confirmOcrBtn.disabled = !enabled;
        confirmOcrBtn.setAttribute('aria-disabled', String(!enabled));
    }

    function setListenButtonLabel(hasPlayed) {
        listenAgainBtn.innerHTML = hasPlayed ? LISTEN_AGAIN_LABEL : LISTEN_FIRST_LABEL;
    }

    // แสดงคำเตือนคุณภาพภาพแบบไม่พึ่งสีเพียงอย่างเดียว (มีไอคอน + ข้อความเสมอ)
    // คืนค่ารายการข้อความที่แสดง เพื่อนำไปประกาศซ้ำผ่าน ocrStatus ด้วย
    function renderQualityWarnings(warnings) {
        if (!warnings || warnings.length === 0) {
            ocrQualityWarnings.hidden = true;
            ocrQualityWarnings.innerHTML = '';
            return [];
        }

        const messages = warnings
            .map(code => QUALITY_WARNING_MESSAGES[code])
            .filter(Boolean);

        if (!messages.length) {
            ocrQualityWarnings.hidden = true;
            ocrQualityWarnings.innerHTML = '';
            return [];
        }

        ocrQualityWarnings.hidden = false;
        ocrQualityWarnings.innerHTML =
            '<i class="fa-solid fa-triangle-exclamation" aria-hidden="true"></i>' +
            '<strong>คำเตือนคุณภาพภาพ (ไม่ปิดกั้นการอ่านข้อความ):</strong> ' +
            messages.join(' ') +
            ' คุณยังฟังและยืนยันข้อความนี้ได้ตามปกติ หรือกดปุ่ม "ถ่ายหรือเลือกภาพอื่น" เพื่อลองภาพใหม่';

        return messages;
    }

    function setOcrStatus(message, state = 'idle', isError = false) {
        ocrStatus.textContent = `สถานะ: ${message}`;
        ocrStatus.dataset.state = state;
        ocrStatus.setAttribute('aria-live', isError ? 'assertive' : 'polite');
    }

    function resetOcrResult() {
        stopSpeech();
        recognizedText = '';
        resultMayBeUnclear = false;
        hasPlayedSpeechOnce = false;
        ocrRecognizedText.textContent = '';
        ocrRecognizedText.lang = 'th';
        ocrConfidenceSummary.textContent = '';
        ocrConfidenceSummary.hidden = true;
        ocrQualityWarnings.innerHTML = '';
        ocrQualityWarnings.hidden = true;
        ocrResultPanel.hidden = true;
        listenAgainBtn.disabled = false;
        setListenButtonLabel(false);
        setConfirmEnabled(false);
        confirmOcrBtn.innerHTML = '<i class="fa-solid fa-check" aria-hidden="true"></i> ยืนยัน (Confirm)';
    }

    function handleImageSelection() {
        resetOcrResult();

        const imageFile = ocrImageInput.files && ocrImageInput.files[0];
        if (!imageFile) {
            readImageBtn.disabled = true;
            setOcrStatus('ยังไม่ได้เลือกภาพ');
            return;
        }

        if (imageFile.type && !imageFile.type.startsWith('image/')) {
            ocrImageInput.value = '';
            readImageBtn.disabled = true;
            setOcrStatus('ไฟล์ที่เลือกไม่ใช่ไฟล์ภาพ กรุณาเลือกหรือถ่ายภาพใหม่', 'error', true);
            return;
        }

        readImageBtn.disabled = false;
        setOcrStatus(`อัปโหลดภาพ ${imageFile.name} พร้อมสำหรับประมวลผลแล้ว กดปุ่มอ่านข้อความจากภาพ`, 'upload');
    }

    async function processImage() {
        if (ocrProcessing) return;

        const imageFile = ocrImageInput.files && ocrImageInput.files[0];
        if (!imageFile) {
            readImageBtn.disabled = true;
            setOcrStatus('ไม่พบภาพ กรุณาเลือกหรือถ่ายภาพก่อน', 'error', true);
            ocrImageInput.focus();
            return;
        }

        stopSpeech();
        resetOcrResult();
        ocrProcessing = true;
        readImageBtn.disabled = true;
        ocrImageInput.disabled = true;
        setOcrStatus('กำลังประมวลผล OCR โปรดรอสักครู่ การประมวลผลด้วยซีพียูอาจใช้เวลาหลายวินาที', 'processing');
        ocrStatus.focus();

        const formData = new FormData();
        formData.append('image', imageFile, imageFile.name);

        try {
            const response = await fetch('/api/ocr', {
                method: 'POST',
                body: formData
            });
            const data = await response.json().catch(() => null);

            if (!response.ok || !data || !data.ok) {
                const errorMessage = data?.error?.message
                    || 'ไม่สามารถอ่านข้อความจากภาพได้ กรุณาลองอีกครั้ง';
                showOcrFailure(errorMessage);
                return;
            }

            recognizedText = typeof data.text === 'string' ? data.text.trim() : '';
            hasPlayedSpeechOnce = false;
            resultMayBeUnclear = Boolean(data.low_confidence);
            ocrRecognizedText.textContent = recognizedText;
            ocrResultPanel.hidden = false;
            updateConfidenceSummary(data);

            // คำเตือนคุณภาพภาพเป็น heuristic เท่านั้น ไม่ปิดกั้นการอ่านหรือยืนยัน
            const qualityWarnings = data.image_quality ? data.image_quality.warnings : null;
            const qualityMessages = renderQualityWarnings(qualityWarnings);
            const qualitySuffix = qualityMessages.length
                ? ` ${qualityMessages.join(' ')}`
                : (data.image_quality ? ` ${QUALITY_OK_MESSAGE}` : '');

            if (!recognizedText) {
                listenAgainBtn.disabled = true;
                setConfirmEnabled(false);
                ocrRecognizedText.textContent = 'ไม่พบข้อความ';
                setOcrStatus('ไม่พบข้อความในภาพ กรุณาถ่ายหรือเลือกภาพใหม่' + qualitySuffix, 'error', true);
                return;
            }

            // Confirm must be available as soon as OCR succeeds, independent of speech.
            ocrRecognizedText.lang = /[\u0E00-\u0E7F]/.test(recognizedText) ? 'th' : 'en';
            setConfirmEnabled(true);
            setListenButtonLabel(false);

            if (!speechSupported) {
                listenAgainBtn.disabled = true;
                setOcrStatus(
                    'อ่านข้อความสำเร็จ ข้อความที่ตรวจพบแสดงไว้ด้านล่างและอ่านได้ด้วยโปรแกรมอ่านหน้าจอ เบราว์เซอร์นี้ไม่รองรับการอ่านออกเสียงอัตโนมัติ แต่สามารถกดยืนยันได้ทันที' + qualitySuffix,
                    'success'
                );
                ocrResultHeading.focus();
                return;
            }

            listenAgainBtn.disabled = false;
            const hasQualityWarning = qualityMessages.length > 0;
            setOcrStatus(
                (resultMayBeUnclear
                    ? 'อ่านข้อความสำเร็จ แต่ผลอาจไม่ชัดเจน พร้อมยืนยันได้ทันที กดปุ่มฟังข้อความที่ตรวจพบเพื่อฟังผลลัพธ์'
                    : 'อ่านข้อความสำเร็จ พร้อมยืนยันได้ทันที กดปุ่มฟังข้อความที่ตรวจพบเพื่อฟังผลลัพธ์'
                ) + qualitySuffix,
                (resultMayBeUnclear || hasQualityWarning) ? 'warning' : 'success'
            );
            listenAgainBtn.focus();
        } catch (_error) {
            showOcrFailure('ไม่สามารถเชื่อมต่อบริการ OCR ได้ กรุณาตรวจสอบเซิร์ฟเวอร์แล้วลองอีกครั้ง');
        } finally {
            ocrProcessing = false;
            ocrImageInput.disabled = false;
            readImageBtn.disabled = !(ocrImageInput.files && ocrImageInput.files[0]);
        }
    }

    function showOcrFailure(message) {
        recognizedText = '';
        hasPlayedSpeechOnce = false;
        resultMayBeUnclear = false;
        ocrRecognizedText.textContent = '';
        ocrResultPanel.hidden = false;
        listenAgainBtn.disabled = true;
        setConfirmEnabled(false);
        ocrConfidenceSummary.hidden = true;
        ocrQualityWarnings.innerHTML = '';
        ocrQualityWarnings.hidden = true;
        setOcrStatus(message, 'error', true);
    }

    function updateConfidenceSummary(data) {
        if (typeof data.mean_confidence !== 'number') {
            ocrConfidenceSummary.textContent = '';
            ocrConfidenceSummary.hidden = true;
            return;
        }

        const percentage = Math.round(data.mean_confidence * 100);
        ocrConfidenceSummary.textContent = `ข้อมูลช่วยตรวจสอบ: mean_confidence ${percentage}% เป็นค่าเฉลี่ยเลขคณิตของ confidence ทุกส่วน ไม่ใช่ค่ารับประกันความแม่นยำของ OCR`;
        ocrConfidenceSummary.hidden = false;
    }

    function getSpeechSegments(text) {
        const tokens = text.match(/[\u0E00-\u0E7F]+|[A-Za-z]+|[^\u0E00-\u0E7FA-Za-z]+/g) || [text];
        const segments = [];
        let currentText = '';
        let currentLanguage = null;

        tokens.forEach(token => {
            const tokenLanguage = /[\u0E00-\u0E7F]/.test(token)
                ? 'th-TH'
                : /[A-Za-z]/.test(token) ? 'en-US' : null;

            if (tokenLanguage && currentLanguage && tokenLanguage !== currentLanguage) {
                if (currentText.trim()) {
                    segments.push({ text: currentText.trim(), lang: currentLanguage });
                }
                currentText = token;
                currentLanguage = tokenLanguage;
            } else {
                currentText += token;
                if (tokenLanguage) currentLanguage = tokenLanguage;
            }
        });

        if (currentText.trim()) {
            segments.push({
                text: currentText.trim(),
                lang: currentLanguage || 'th-TH'
            });
        }

        return segments;
    }

    function findVoice(lang) {
        const voices = cachedVoices.length
            ? cachedVoices
            : (speechSupported ? window.speechSynthesis.getVoices() : []);
        const languageCode = lang.toLowerCase().split('-')[0];
        return voices.find(voice => voice.lang && voice.lang.toLowerCase() === lang.toLowerCase())
            || voices.find(voice => voice.lang && voice.lang.toLowerCase().startsWith(languageCode))
            || null;
    }

    // Called directly from a button click handler so Chrome treats speech as
    // user-activated, even though it plays back an OCR result fetched earlier.
    function speakRecognizedText() {
        if (!recognizedText) {
            setOcrStatus('ยังไม่มีข้อความให้อ่าน กรุณาเลือกภาพและอ่านข้อความจากภาพก่อน', 'error', true);
            return;
        }

        if (!speechSupported) {
            setOcrStatus('เบราว์เซอร์นี้ไม่รองรับการอ่านข้อความเป็นเสียง คุณสามารถใช้โปรแกรมอ่านหน้าจอหรือกดยืนยันได้เลย', 'error', true);
            return;
        }

        stopSpeech();
        if (window.speechSynthesis.paused) {
            window.speechSynthesis.resume();
        }

        setListenButtonLabel(true);
        hasPlayedSpeechOnce = true;

        const currentRunId = ++speechRunId;
        const segments = getSpeechSegments(recognizedText);
        let completedSegments = 0;
        let speechFailed = false;

        setOcrStatus('กำลังเตรียมอ่านออกเสียง โปรดรอสักครู่', 'processing');

        segments.forEach((segment, index) => {
            const utterance = new SpeechSynthesisUtterance(segment.text);
            utterance.lang = segment.lang;
            const matchingVoice = findVoice(segment.lang);
            if (matchingVoice) utterance.voice = matchingVoice;

            activeUtterances.push(utterance);

            if (index === 0) {
                utterance.onstart = () => {
                    if (currentRunId !== speechRunId) return;
                    setOcrStatus('กำลังอ่านข้อความ', 'processing');
                };
            }

            utterance.onend = () => {
                if (currentRunId !== speechRunId || speechFailed) return;
                completedSegments += 1;
                if (completedSegments === segments.length) {
                    activeUtterances = [];
                    setOcrStatus(SPEECH_DONE_MESSAGE, 'success');
                }
            };

            utterance.onerror = event => {
                if (currentRunId !== speechRunId || ['canceled', 'interrupted'].includes(event.error)) return;
                speechFailed = true;
                activeUtterances = [];
                // Only the error code is logged; it is enough for developer diagnosis.
                console.error('speechSynthesis error code:', event.error);
                window.speechSynthesis.cancel();
                setOcrStatus(SPEECH_ERROR_MESSAGE, 'error', true);
            };

            window.speechSynthesis.speak(utterance);
        });
    }

    function stopSpeech() {
        speechRunId += 1;
        activeUtterances = [];
        if (!speechSupported) return;
        window.speechSynthesis.cancel();
        if (window.speechSynthesis.paused) {
            window.speechSynthesis.resume();
        }
    }

    // Confirmation never depends on speech state: it is only gated by whether
    // OCR produced non-empty text (see setConfirmEnabled callers).
    function confirmOcrResult() {
        if (!recognizedText) {
            return;
        }

        stopSpeech();
        setConfirmEnabled(false);
        confirmOcrBtn.innerHTML = '<i class="fa-solid fa-check-double" aria-hidden="true"></i> ยืนยันแล้ว (Confirmed)';
        setOcrStatus('ยืนยันข้อความแล้ว ผล OCR ถูกเก็บไว้ในหน้านี้และยังไม่ได้ส่งไปยัง ESP32', 'success');
        addLog('ยืนยันผล OCR แล้ว (ยังไม่ได้ส่งข้อมูลไปยัง ESP32)', 'success');
    }

    function chooseAnotherImage() {
        stopSpeech();
        ocrImageInput.disabled = false;
        ocrImageInput.value = '';
        readImageBtn.disabled = true;
        resetOcrResult();
        setOcrStatus('พร้อมเลือกหรือถ่ายภาพอื่น');
        ocrImageInput.click();
    }

    // Populate Thai & English Braille Keyboard Buttons
    function populateAlphabetKeyboard() {
        alphabetGrid.innerHTML = '';
        Object.keys(BRAILLE_DICT).forEach(char => {
            const btn = document.createElement('button');
            btn.className = 'char-btn';
            btn.textContent = char;
            btn.title = `${char} = ${BRAILLE_DICT[char]}`;
            btn.addEventListener('click', () => {
                const pattern = BRAILLE_DICT[char];
                setPattern(pattern);
                sendPatternToESP32(pattern, `ส่งตัวอักษร '${char}' (${pattern})`);
            });
            alphabetGrid.appendChild(btn);
        });
    }

    // Helper: Update state & UI to match pattern string
    function setPattern(patternStr) {
        // Pad or trim to exactly 6 digits
        let validStr = patternStr.replace(/[^01]/g, '');
        if (validStr.length < 6) {
            validStr = validStr.padEnd(6, '0');
        } else if (validStr.length > 6) {
            validStr = validStr.substring(0, 6);
        }

        currentPattern = validStr;
        patternInput.value = currentPattern;
        binaryPatternDisplay.textContent = currentPattern;
        updateVisualPreview(currentPattern);
    }

    // Update 2x3 Matrix Visual Preview
    function updateVisualPreview(pattern) {
        for (let i = 1; i <= 6; i++) {
            const val = pattern.charAt(i - 1);
            if (val === '1') {
                dots[i].classList.add('active');
            } else {
                dots[i].classList.remove('active');
            }
        }
    }

    // Click event on dot wrappers -> Toggle bit 0/1
    document.querySelectorAll('.dot-wrapper').forEach(wrapper => {
        wrapper.addEventListener('click', () => {
            const dotNum = parseInt(wrapper.dataset.dot);
            let patternArray = currentPattern.split('');
            // Toggle bit at dotNum - 1 index
            patternArray[dotNum - 1] = patternArray[dotNum - 1] === '1' ? '0' : '1';
            const newPattern = patternArray.join('');
            setPattern(newPattern);
        });
    });

    // Handle Pattern Input Changes
    patternInput.addEventListener('input', (e) => {
        let val = e.target.value.replace(/[^01]/g, '');
        if (val.length > 6) val = val.substring(0, 6);
        e.target.value = val;
        
        let paddedVal = val.padEnd(6, '0');
        currentPattern = paddedVal;
        binaryPatternDisplay.textContent = paddedVal;
        updateVisualPreview(paddedVal);
    });

    // Send Button Click
    sendBtn.addEventListener('click', () => {
        const pattern = patternInput.value.padEnd(6, '0');
        sendPatternToESP32(pattern);
    });

    // Preset Action Buttons
    btnAllOn.addEventListener('click', () => {
        setPattern("111111");
        sendPatternToESP32("111111", "เปิดทุกจุด (All ON)");
    });

    btnAllOff.addEventListener('click', () => {
        setPattern("000000");
        sendPatternToESP32("000000", "ปิดทุกจุด (All OFF)");
    });

    btnClear.addEventListener('click', () => {
        setPattern("000000");
        addLog("ล้างข้อมูลในช่องกรอกเรียบร้อยแล้ว", "info");
    });

    // Send Payload to Backend via Fetch API
    async function sendPatternToESP32(pattern, customActionLabel = "") {
        addLog(`กำลังส่งข้อมูล ${pattern} ไปยัง ESP32...`, "info");

        try {
            const response = await fetch('/send', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ pattern: pattern })
            });

            const data = await response.json();

            if (response.ok && data.success) {
                const label = customActionLabel ? ` (${customActionLabel})` : '';
                addLog(`✓ ${data.message}${label}`, "success");
            } else {
                addLog(`❌ ข้อผิดพลาด: ${data.message}`, "error");
            }
        } catch (err) {
            addLog(`❌ เกิดข้อผิดพลาดในการเชื่อมต่อเซิร์ฟเวอร์: ${err.message}`, "error");
        }
    }

    // Check Connection Status via GET /api/status
    async function checkConnectionStatus() {
        try {
            const response = await fetch('/api/status');
            const data = await response.json();

            // Populate COM ports dropdown
            updatePortDropdown(data.available_ports, data.active_port);

            if (data.connected) {
                statusBadge.className = "status-badge connected";
                statusText.textContent = `เชื่อมต่อแล้ว (${data.active_port})`;
            } else {
                statusBadge.className = "status-badge disconnected";
                statusText.textContent = `ไม่ได้เชื่อมต่อ (${data.active_port})`;
            }
        } catch (err) {
            statusBadge.className = "status-badge disconnected";
            statusText.textContent = "ไม่พบเซิร์ฟเวอร์ Flask";
        }
    }

    // Update COM Ports Dropdown List
    function updatePortDropdown(availablePorts, activePort) {
        // Only update if not currently open/focused by user
        if (document.activeElement === portSelect) return;

        const ports = availablePorts.length > 0 ? availablePorts : [activePort, 'COM3', 'COM4'];
        const uniquePorts = [...new Set(ports)];

        portSelect.innerHTML = '';
        uniquePorts.forEach(port => {
            const opt = document.createElement('option');
            opt.value = port;
            opt.textContent = port;
            if (port === activePort) opt.selected = true;
            portSelect.appendChild(opt);
        });
    }

    // Reconnect / Switch COM Port Button Click
    reconnectBtn.addEventListener('click', async () => {
        const selectedPort = portSelect.value;
        addLog(`กำลังลองเชื่อมต่อ ESP32 ผ่านพอร์ต ${selectedPort}...`, "system");

        try {
            const response = await fetch('/api/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ port: selectedPort })
            });
            const data = await response.json();

            if (data.success) {
                addLog(`✓ ${data.message}`, "success");
            } else {
                addLog(`❌ ${data.message}`, "error");
            }
            checkConnectionStatus();
        } catch (err) {
            addLog(`❌ ข้อผิดพลาดในการเชื่อมต่อ: ${err.message}`, "error");
        }
    });

    // Add Output Line to Terminal Log Box
    function addLog(message, type = "info") {
        const line = document.createElement('div');
        line.className = `log-line ${type}`;
        
        const timestamp = new Date().toLocaleTimeString();
        line.textContent = `[${timestamp}] ${message}`;

        terminalLog.appendChild(line);
        terminalLog.scrollTop = terminalLog.scrollHeight;
    }

    // Clear Terminal Log Button
    clearLogBtn.addEventListener('click', () => {
        terminalLog.innerHTML = '<div class="log-line info">[SYSTEM] ล้างประวัติการส่งเรียบร้อยแล้ว</div>';
    });
});
