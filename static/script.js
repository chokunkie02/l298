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

    // Step 4: การแปลข้อความที่ยืนยันแล้วเป็นอักษรเบรลล์ 6 จุด (โครงสร้างข้อมูลเท่านั้น
    // ไม่ส่งไปยัง ESP32 ในขั้นตอนนี้)
    const brailleSection = document.getElementById('brailleTranslationSection');
    const brailleStatus = document.getElementById('brailleStatus');
    const brailleResultSummary = document.getElementById('brailleResultSummary');
    const retryBrailleBtn = document.getElementById('retryBrailleBtn');
    const brailleCellDetails = document.getElementById('brailleCellDetails');
    const brailleCellList = document.getElementById('brailleCellList');

    // Step 5: เล่นลำดับอักษรเบรลล์แบบจำลอง (ยังไม่ส่งไปยัง ESP32)
    const braillePreviewModeLabel = document.getElementById('braillePreviewModeLabel');
    const braillePlaybackSection = document.getElementById('braillePlaybackSection');
    const braillePlaybackAnnouncer = document.getElementById('braillePlaybackAnnouncer');
    const brailleCurrentCellInfo = document.getElementById('brailleCurrentCellInfo');
    const braillePlaybackStatusText = document.getElementById('braillePlaybackStatusText');
    const braillePlayBtn = document.getElementById('braillePlayBtn');
    const braillePauseBtn = document.getElementById('braillePauseBtn');
    const braillePreviousBtn = document.getElementById('braillePreviousBtn');
    const brailleNextBtn = document.getElementById('brailleNextBtn');
    const brailleRestartBtn = document.getElementById('brailleRestartBtn');
    const brailleStopBtn = document.getElementById('brailleStopBtn');
    const brailleCellDurationInput = document.getElementById('brailleCellDurationInput');
    const brailleGapInput = document.getElementById('brailleGapInput');
    const brailleLinePauseInput = document.getElementById('brailleLinePauseInput');

    // Step 6: โหมดฮาร์ดแวร์จริง (ปิดอยู่เสมอตอนโหลดหน้า)
    const hardwareModeToggle = document.getElementById('hardwareModeToggle');
    const hardwareModeStatus = document.getElementById('hardwareModeStatus');
    const hardwarePortSelect = document.getElementById('hardwarePortSelect');
    const hardwareRefreshPortsBtn = document.getElementById('hardwareRefreshPortsBtn');
    const hardwareConnectBtn = document.getElementById('hardwareConnectBtn');
    const hardwareConnectionStatus = document.getElementById('hardwareConnectionStatus');
    const hardwareStartBtn = document.getElementById('hardwareStartBtn');
    const hardwareStopBtn = document.getElementById('hardwareStopBtn');
    const hardwarePlayBtn = document.getElementById('hardwarePlayBtn');
    const hardwarePauseBtn = document.getElementById('hardwarePauseBtn');
    const hardwarePrevBtn = document.getElementById('hardwarePrevBtn');
    const hardwareNextBtn = document.getElementById('hardwareNextBtn');
    const hardwareCurrentCharDisplay = document.getElementById('hardwareCurrentCharDisplay');
    const hardwareCurrentCellDetail = document.getElementById('hardwareCurrentCellDetail');
    const hardwareCountdownBadge = document.getElementById('hardwareCountdownBadge');
    const hardwareSendStatus = document.getElementById('hardwareSendStatus');
    const hardwareWatchdogStatus = document.getElementById('hardwareWatchdogStatus');
    const hardwareVerifyPatternSelect = document.getElementById('hardwareVerifyPatternSelect');
    const hardwareVerifyActivateBtn = document.getElementById('hardwareVerifyActivateBtn');
    const hardwareVerifyClearBtn = document.getElementById('hardwareVerifyClearBtn');
    const hardwareVerifyObservedInput = document.getElementById('hardwareVerifyObservedInput');
    const hardwareVerifyOutcomeSelect = document.getElementById('hardwareVerifyOutcomeSelect');
    const hardwareVerifyRecordBtn = document.getElementById('hardwareVerifyRecordBtn');
    const hardwareVerifyLog = document.getElementById('hardwareVerifyLog');

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

        const modeTabImage = document.getElementById('modeTabImage');
        const modeTabText = document.getElementById('modeTabText');
        const imageInputPanel = document.getElementById('imageInputPanel');
        const textInputPanel = document.getElementById('textInputPanel');

        if (modeTabImage && modeTabText) {
            modeTabImage.addEventListener('click', () => {
                modeTabImage.className = 'btn btn-primary';
                modeTabImage.style.background = '';
                modeTabImage.style.color = '';
                modeTabText.className = 'btn btn-secondary';
                modeTabText.style.background = '#e2e8f0';
                modeTabText.style.color = '#1e293b';
                if (imageInputPanel) imageInputPanel.hidden = false;
                if (textInputPanel) textInputPanel.hidden = true;
            });

            modeTabText.addEventListener('click', () => {
                modeTabText.className = 'btn btn-primary';
                modeTabText.style.background = '';
                modeTabText.style.color = '';
                modeTabImage.className = 'btn btn-secondary';
                modeTabImage.style.background = '#e2e8f0';
                modeTabImage.style.color = '#1e293b';
                if (imageInputPanel) imageInputPanel.hidden = true;
                if (textInputPanel) textInputPanel.hidden = false;
            });
        }

        const directTextInput = document.getElementById('directTextInput');
        const directTranslateBtn = document.getElementById('directTranslateBtn');

        if (directTranslateBtn) {
            directTranslateBtn.addEventListener('click', async () => {
                const text = directTextInput ? directTextInput.value.trim() : '';
                if (!text) {
                    alert('กรุณากรอกข้อความก่อนกดแปล');
                    return;
                }
                await ensureHardwareSessionActive();
                await translateConfirmedTextToBraille(text);
            });
        }

        if (directTextInput) {
            directTextInput.addEventListener('keypress', async (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    if (directTranslateBtn) directTranslateBtn.click();
                }
            });
        }

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
        resetBrailleTranslation();
    }

    function resetBrailleTranslation() {
        brailleSection.hidden = true;
        brailleStatus.textContent = '';
        brailleResultSummary.textContent = '';
        brailleResultSummary.hidden = true;
        retryBrailleBtn.hidden = true;
        brailleCellDetails.hidden = true;
        brailleCellList.innerHTML = '';
        resetBraillePlayback();
    }

    // ============================================================
    // Step 5: การเล่นลำดับอักษรเบรลล์แบบจำลอง (single-cell playback)
    // ============================================================
    // ตัวควบคุมสถานะ/เวลาทั้งหมดอยู่ใน static/braille_playback.js (pure module
    // ไม่ยุ่งกับ DOM) ไฟล์นี้มีหน้าที่แค่เชื่อม callback เข้ากับ DOM/aria-live
    // เท่านั้น - ไม่มีจุดใดเรียก fetch('/send') หรือ sendPatternToESP32() เลย

    const BRAILLE_PLAYBACK_STATE_LABELS = {
        empty: 'ยังไม่มีลำดับให้เล่น',
        ready: 'พร้อมเล่น',
        playing_cell: 'กำลังเล่น',
        playing_gap: 'กำลังเล่น',
        paused: 'หยุดชั่วคราว',
        completed: 'เล่นครบแล้ว',
        stopped: 'หยุดเล่นแล้ว',
    };

    // ติดตามว่าการประกาศเซลล์ล่าสุด (แบบ live) เกิดขึ้นในจังหวะเดียวกับที่กำลัง
    // จะประกาศเปลี่ยนบรรทัดหรือไม่ เพื่อรวมสองข้อความเป็นประกาศเดียว แทนที่จะยิง
    // aria-live ซ้อนกันสองครั้งติด ๆ กัน (ดู handleBraillePlaybackLineChange)
    let brailleCellAnnouncedThisTransition = false;

    const braillePlayback = new BraillePlaybackController({
        onCellDisplay: handleBraillePlaybackCellDisplay,
        onTransientBlank: handleBraillePlaybackTransientBlank,
        onStateChange: handleBraillePlaybackStateChange,
        onLineChange: handleBraillePlaybackLineChange,
        onComplete: handleBraillePlaybackComplete,
        onError: handleBraillePlaybackError,
    });

    // ============================================================
    // Step 6: สะพานเชื่อมการเล่นเข้ากับ Serial จริง (โหมดฮาร์ดแวร์)
    // ============================================================
    // hardwareBridge เป็น null ถ้าโหลด braille_hardware.js ไม่สำเร็จ - ทุกจุดที่
    // เรียกใช้ต้องเช็ก null ก่อนเสมอ การเล่นแบบจำลองต้องทำงานได้โดยไม่ขึ้นกับสิ่งนี้
    const hardwareBridge = (typeof BrailleHardwareBridge === 'function')
        ? new BrailleHardwareBridge({
            fetchFn: (url, opts) => fetch(url, opts),
            onSendStatus: info => {
                if (!hardwareSendStatus) return;
                hardwareSendStatus.textContent = `สถานะการส่ง: ${info.message}` +
                    (info.detail ? ` (${info.detail})` : '');
            },
            onConnectionStatus: info => {
                if (!hardwareConnectionStatus) return;
                hardwareConnectionStatus.textContent = `สถานะการเชื่อมต่อ: ${info.message}`;
            },
            onWatchdogStatus: info => {
                if (!hardwareWatchdogStatus) return;
                hardwareWatchdogStatus.textContent = `ความปลอดภัย: ${info.message}`;
            },
            onModeChange: enabled => {
                if (hardwareModeStatus) {
                    hardwareModeStatus.textContent = enabled
                        ? 'สถานะ: โหมดฮาร์ดแวร์จริงเปิดอยู่ — อุปกรณ์อาจขยับหรือจ่ายพลังงาน'
                        : 'สถานะ: โหมดฮาร์ดแวร์จริงปิดอยู่';
                }
                updateHardwareControlAvailability();
            },
            onSessionChange: () => updateHardwareControlAvailability(),
        })
        : null;

    // เรียกแบบ fire-and-forget เสมอ - callback ของ playback เป็น sync ห้าม await
    function notifyHardware(method, ...args) {
        if (!hardwareBridge) return;
        try {
            const result = hardwareBridge[method](...args);
            if (result && typeof result.catch === 'function') result.catch(() => {});
        } catch (_err) {
            /* โหมดฮาร์ดแวร์ต้องไม่ทำให้การเล่นจำลองพัง */
        }
    }

    // เรียงหมายเลขจุดแบบไทย เช่น [1,3,5] -> "1 3 และ 5" (จุดเดียวไม่มี "และ")
    function formatDotList(dotNumbers) {
        if (!dotNumbers || dotNumbers.length === 0) return '';
        if (dotNumbers.length === 1) return String(dotNumbers[0]);
        return dotNumbers.slice(0, -1).join(' ') + ' และ ' + dotNumbers[dotNumbers.length - 1];
    }

    function setBraillePlaybackAnnouncement(text) {
        braillePlaybackAnnouncer.textContent = text;
    }

    function setBrailleButtonEnabled(button, enabled) {
        button.disabled = !enabled;
        button.setAttribute('aria-disabled', String(!enabled));
    }

    // เปิด/ปิดปุ่มควบคุมตามสถานะปัจจุบัน - ปุ่มที่กดแล้วไม่มีผลใด ๆ ต้องถูกปิดไว้
    // เสมอ (เช่น เล่นครบแล้วต้องกด "เริ่มใหม่" ก่อนกด "เริ่มเล่น" ได้อีกครั้ง)
    function updateBraillePlaybackControls(state) {
        const hasCells = braillePlayback.getCellCount() > 0;
        const isPlaying = state === 'playing_cell' || state === 'playing_gap';
        const isCompleted = state === 'completed';

        setBrailleButtonEnabled(braillePlayBtn, hasCells && !isPlaying && !isCompleted);
        setBrailleButtonEnabled(braillePauseBtn, isPlaying);
        setBrailleButtonEnabled(braillePreviousBtn, hasCells);
        setBrailleButtonEnabled(brailleNextBtn, hasCells);
        setBrailleButtonEnabled(brailleRestartBtn, hasCells);
        setBrailleButtonEnabled(brailleStopBtn, hasCells && state !== 'empty' && state !== 'stopped');
    }

    // จอแสดงผลจำลอง (dot matrix เดิม) - updateVisualPreview() เป็นฟังก์ชัน
    // บริสุทธิ์ล้วน (แค่ toggle classList) ไม่เรียก /send หรือแตะ patternInput/
    // binaryPatternDisplay ที่ใช้ควบคุมฮาร์ดแวร์ด้วยมือเลย จึงใช้ซ้ำได้อย่าง
    // ปลอดภัยตรงนี้โดยไม่ต้องสร้างฟังก์ชันใหม่ (ดู README.md หัวข้อ Step 5)
    let countdownIntervalId = null;

    function startHardwareCountdown(durationMs) {
        clearInterval(countdownIntervalId);
        if (!hardwareCountdownBadge) return;

        let remSeconds = Math.ceil(durationMs / 1000);
        if (remSeconds <= 0) {
            hardwareCountdownBadge.hidden = true;
            return;
        }

        hardwareCountdownBadge.hidden = false;
        hardwareCountdownBadge.textContent = `⏱️ อีก ${remSeconds}วิ...`;

        countdownIntervalId = setInterval(() => {
            remSeconds -= 1;
            if (remSeconds > 0) {
                hardwareCountdownBadge.textContent = `⏱️ อีก ${remSeconds}วิ...`;
            } else {
                hardwareCountdownBadge.textContent = `⏱️ กำลังเปลี่ยนคำ...`;
                clearInterval(countdownIntervalId);
            }
        }, 1000);
    }

    function stopHardwareCountdown() {
        clearInterval(countdownIntervalId);
        if (hardwareCountdownBadge) {
            hardwareCountdownBadge.hidden = true;
        }
    }

    let hardwareLogCountNum = 0;

    function addHardwareLog(message, type = 'info') {
        const list = document.getElementById('hardwareLogList');
        const countSpan = document.getElementById('hardwareLogCount');
        if (!list) return;
        
        hardwareLogCountNum += 1;
        if (countSpan) countSpan.textContent = `${hardwareLogCountNum} รายการ`;

        const now = new Date();
        const timeStr = now.toTimeString().split(' ')[0];
        const icon = type === 'error' ? '❌' : (type === 'success' ? '🟢' : 'ℹ️');
        const color = type === 'error' ? '#f87171' : (type === 'success' ? '#4ade80' : '#38bdf8');
        
        const line = document.createElement('div');
        line.style.color = color;
        line.style.marginTop = '2px';
        line.innerHTML = `<span style="color: #64748b;">[${timeStr}]</span> ${icon} ${message}`;
        list.appendChild(line);
        list.scrollTop = list.scrollHeight;
    }

    function handleBraillePlaybackCellDisplay(info) {
        braillePreviewModeLabel.hidden = false;
        updateVisualPreview(info.cell.bit_pattern);
        if (patternInput && binaryPatternDisplay) {
            patternInput.value = info.cell.bit_pattern;
            binaryPatternDisplay.textContent = info.cell.bit_pattern;
        }

        notifyHardware('sendCell', info.cell, info.index);

        const cellNumber = info.index + 1;
        const displayChar = info.cell.source_text || info.cell.unicode_braille || info.cell.bit_pattern;
        addHardwareLog(`ส่งเซลล์ที่ ${cellNumber}/${info.cellCount} ('${displayChar}' => ${info.cell.bit_pattern}) ไปยัง ESP32`, 'success');

        const cellText = info.isBlank
            ? `เซลล์ ${cellNumber} จาก ${info.cellCount} เป็นช่องว่าง`
            : `เซลล์ ${cellNumber} จาก ${info.cellCount} จุด ${formatDotList(info.cell.dot_numbers)}`;

        brailleCurrentCellInfo.textContent =
            `${cellText} (บรรทัดที่ ${info.lineNumber}, รูปแบบ 6 บิต: ${info.cell.bit_pattern})`;

        if (hardwareCurrentCharDisplay) {
            const displayChar = info.cell.source_text || info.cell.unicode_braille || info.cell.bit_pattern;
            hardwareCurrentCharDisplay.textContent = `${displayChar}`;
            if (hardwareCurrentCellDetail) {
                const dotStr = info.cell.dot_numbers && info.cell.dot_numbers.length ? info.cell.dot_numbers.join(', ') : 'ไม่มี (ล้าง)';
                hardwareCurrentCellDetail.textContent = `เซลล์ที่ ${cellNumber} จาก ${info.cellCount} | ตัวอักษร: '${displayChar}' | รูปแบบ 6 บิต: ${info.cell.bit_pattern} | จุดเปิด: [${dotStr}] | บรรทัดที่ ${info.lineNumber}`;
            }
        }

        const timing = braillePlayback.getTiming();
        const state = braillePlayback.getState();
        if (state === 'playing_cell') {
            startHardwareCountdown(timing.cellDurationMs);
        } else {
            stopHardwareCountdown();
        }

        brailleCellAnnouncedThisTransition = info.announce === true;
        if (info.announce) {
            setBraillePlaybackAnnouncement(cellText);
        }
    }

    function handleBraillePlaybackTransientBlank() {
        updateVisualPreview('000000');
        stopHardwareCountdown();
        notifyHardware('sendTransientGap');
    }

    function handleBraillePlaybackStateChange(state) {
        updateBraillePlaybackControls(state);
        updateHardwareControlAvailability();
        braillePlaybackStatusText.textContent = `สถานะ: ${BRAILLE_PLAYBACK_STATE_LABELS[state] || state}`;

        if (state !== 'playing_cell' && state !== 'playing_gap') {
            stopHardwareCountdown();
        }

        if (state === 'paused') {
            setBraillePlaybackAnnouncement('หยุดชั่วคราว');
            notifyHardware('sendTransientGap');
        } else if (state === 'stopped') {
            setBraillePlaybackAnnouncement('หยุดเล่นและล้างจอแสดงผลจำลองแล้ว');
            braillePreviewModeLabel.hidden = true;
            notifyHardware('handlePlaybackEnded', 'กดหยุดการเล่น');
        } else if (state === 'empty') {
            braillePreviewModeLabel.hidden = true;
            notifyHardware('handlePlaybackEnded', 'ล้างลำดับการเล่น');
        }
    }

    // การขึ้นบรรทัดใหม่ต้องประกาศเสมอ (ไม่ถูกจำกัดแบบเซลล์ระหว่างเล่นอัตโนมัติ)
    // ถ้าจังหวะเดียวกันมีการประกาศเซลล์แบบ live อยู่แล้ว ให้รวมเป็นข้อความเดียว
    // แทนที่จะยิง aria-live ซ้อนกันสองครั้งติดกัน
    function handleBraillePlaybackLineChange(info) {
        const lineText = `ขึ้นบรรทัดที่ ${info.lineNumber}`;
        if (brailleCellAnnouncedThisTransition) {
            setBraillePlaybackAnnouncement(lineText + ' ' + braillePlaybackAnnouncer.textContent);
        } else {
            setBraillePlaybackAnnouncement(lineText);
        }
        brailleCellAnnouncedThisTransition = false;
    }

    function handleBraillePlaybackComplete() {
        setBraillePlaybackAnnouncement('เล่นลำดับเบรลล์ครบแล้ว');
        notifyHardware('handlePlaybackEnded', 'เล่นครบลำดับ');
    }

    function handleBraillePlaybackError(error) {
        setBraillePlaybackAnnouncement('เกิดข้อผิดพลาดขณะเตรียมลำดับอักษรเบรลล์สำหรับเล่น');
        addLog(`❌ Braille playback error: ${error.message}`, 'error');
        notifyHardware('handlePlaybackEnded', 'เกิดข้อผิดพลาดในการเล่น');
    }

    function resetBraillePlayback() {
        braillePlayback.clear();
        // OCR ใหม่ / แปลใหม่ / รีเซ็ต ทั้งหมดต้องจบเซสชันฮาร์ดแวร์อย่างปลอดภัย
        notifyHardware('handlePlaybackEnded', 'เริ่มลำดับใหม่');
        braillePlaybackSection.hidden = true;
        braillePreviewModeLabel.hidden = true;
        brailleCurrentCellInfo.textContent = 'ยังไม่เริ่มเล่น';
        braillePlaybackAnnouncer.textContent = '';
    }

    braillePlayBtn.addEventListener('click', async () => {
        await ensureHardwareSessionActive();
        stopSpeech();
        applyBrailleTimingFromInputs();
        braillePlayback.play();
    });
    braillePauseBtn.addEventListener('click', () => braillePlayback.pause());
    braillePreviousBtn.addEventListener('click', async () => {
        await ensureHardwareSessionActive();
        applyBrailleTimingFromInputs();
        braillePlayback.previous();
    });
    brailleNextBtn.addEventListener('click', async () => {
        await ensureHardwareSessionActive();
        applyBrailleTimingFromInputs();
        braillePlayback.next();
    });
    brailleRestartBtn.addEventListener('click', () => braillePlayback.restart());
    brailleStopBtn.addEventListener('click', () => braillePlayback.stop());

    // ปรับค่าเวลาแบบ 'change' (ไม่ใช่ 'input') เพื่อไม่ตรวจสอบ/clamp ทุกครั้งที่
    // พิมพ์แต่ละตัวอักษร - ค่าที่ clamp แล้วจะถูกสะท้อนกลับไปยัง input เสมอ
    function applyBrailleTimingFromInputs() {
        braillePlayback.setTiming({
            cellDurationMs: Number(brailleCellDurationInput.value),
            gapMs: Number(brailleGapInput.value),
            linePauseMs: Number(brailleLinePauseInput.value),
        });
        const timing = braillePlayback.getTiming();
        brailleCellDurationInput.value = timing.cellDurationMs;
        brailleGapInput.value = timing.gapMs;
        brailleLinePauseInput.value = timing.linePauseMs;
    }

    brailleCellDurationInput.addEventListener('change', applyBrailleTimingFromInputs);
    brailleGapInput.addEventListener('change', applyBrailleTimingFromInputs);
    brailleLinePauseInput.addEventListener('change', applyBrailleTimingFromInputs);

    // ============================================================
    // Step 6: การเดินสายปุ่มควบคุมโหมดฮาร์ดแวร์จริง
    // ============================================================
    // ปุ่มฮาร์ดแวร์ทั้งหมด disabled จนกว่าจะเปิด checkbox โหมดฮาร์ดแวร์อย่างชัดเจน
    // ไม่มีการเรียก /api/hardware/* ใด ๆ ตอนโหลดหน้า (ไม่ auto-connect ไม่ auto-start)
    const hardwareVerifyRecords = [];

    async function ensureHardwareSessionActive() {
        if (hardwareBridge) {
            if (!hardwareBridge.isHardwareModeEnabled() && hardwareModeToggle) {
                hardwareModeToggle.checked = true;
                await hardwareBridge.setHardwareModeEnabled(true);
            }
            if (!hardwareBridge.isPortConnected()) {
                const activePort = (typeof hardwarePortSelect !== 'undefined' && hardwarePortSelect.value) ? hardwarePortSelect.value : 'COM3';
                hardwareBridge.setSelectedPort(activePort);
                hardwareBridge.setPortConnected(true, activePort);
            }
            if (!hardwareBridge.isSessionActive()) {
                await hardwareBridge.startSession({ watchdogSeconds: 10 });
            }
        }
        if (braillePlayback.getCellCount() > 0 && (braillePlayback.getState() === 'completed' || braillePlayback.getState() === 'stopped')) {
            braillePlayback.restart();
        }
    }

    function hardwareControlsPresent() {
        return hardwareBridge && hardwareModeToggle && hardwareStartBtn && hardwareStopBtn;
    }

    function setEnabled(el, enabled) {
        if (!el) return;
        el.disabled = !enabled;
        el.setAttribute('aria-disabled', String(!enabled));
    }

    function updateHardwareControlAvailability() {
        if (!hardwareControlsPresent()) return;
        const modeOn = hardwareBridge.isHardwareModeEnabled();
        const connected = hardwareBridge.isPortConnected();
        const sessionActive = hardwareBridge.isSessionActive();

        const hasCells = braillePlayback.getCellCount() > 0;
        const state = braillePlayback.getState();
        const isPlaying = state === 'playing_cell' || state === 'playing_gap';
        const isCompleted = state === 'completed';

        setEnabled(hardwarePortSelect, modeOn && !sessionActive);
        setEnabled(hardwareRefreshPortsBtn, modeOn);
        setEnabled(hardwareConnectBtn, modeOn && !sessionActive);
        setEnabled(hardwareStartBtn, modeOn && connected && !sessionActive);
        // ปุ่มหยุดต้องกดได้ทุกครั้งที่มีเซสชัน และเข้าถึงด้วยคีย์บอร์ดได้เสมอ
        setEnabled(hardwareStopBtn, sessionActive);

        setEnabled(hardwarePlayBtn, modeOn && connected && hasCells && !isPlaying && !isCompleted);
        setEnabled(hardwarePauseBtn, modeOn && connected && isPlaying);
        setEnabled(hardwarePrevBtn, modeOn && connected && hasCells);
        setEnabled(hardwareNextBtn, modeOn && connected && hasCells);

        setEnabled(hardwareVerifyActivateBtn, modeOn && connected && sessionActive);
        setEnabled(hardwareVerifyClearBtn, modeOn && connected && sessionActive);
    }

    async function refreshHardwarePorts() {
        if (!hardwareBridge) return;
        try {
            const res = await fetch('/api/hardware/ports');
            const data = await res.json().catch(() => null);
            if (!data || !data.ok || !hardwarePortSelect) return;
            hardwarePortSelect.innerHTML = '';
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = '— เลือกพอร์ต —';
            hardwarePortSelect.appendChild(placeholder);
            (data.ports || []).forEach(port => {
                const opt = document.createElement('option');
                opt.value = port.device;
                // ไม่เดาชนิดอุปกรณ์ - แสดงป้ายกลาง ๆ เสมอ
                opt.textContent = `${port.device} — ${port.identity_label}` +
                    (port.likely_unrelated ? ' (น่าจะไม่เกี่ยวข้อง)' : '');
                hardwarePortSelect.appendChild(opt);
            });
        } catch (_err) {
            /* เงียบไว้ - ผู้ใช้กดรีเฟรชใหม่ได้ */
        }
    }

    function initHardwareControls() {
        if (!hardwareControlsPresent()) return;
        // ค่าเริ่มต้น: ปิดทุกอย่าง (checkbox ไม่ติ๊ก)
        hardwareModeToggle.checked = false;
        updateHardwareControlAvailability();

        hardwareModeToggle.addEventListener('change', async () => {
            await hardwareBridge.setHardwareModeEnabled(hardwareModeToggle.checked);
            if (hardwareModeToggle.checked) refreshHardwarePorts();
        });

        if (hardwareRefreshPortsBtn) {
            hardwareRefreshPortsBtn.addEventListener('click', refreshHardwarePorts);
        }

        if (hardwareConnectBtn) {
            hardwareConnectBtn.addEventListener('click', async () => {
                const port = hardwarePortSelect ? hardwarePortSelect.value : '';
                if (!port) {
                    if (hardwareConnectionStatus) {
                        hardwareConnectionStatus.textContent = 'สถานะการเชื่อมต่อ: กรุณาเลือกพอร์ตก่อน';
                    }
                    return;
                }
                // ใช้เส้นทาง /api/connect เดิมของแอปในการเปิดพอร์ต (ไม่สร้าง Serial ซ้ำ)
                try {
                    const res = await fetch('/api/connect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ port }),
                    });
                    const data = await res.json().catch(() => null);
                    const isConnected = Boolean(data && data.success);
                    hardwareBridge.setSelectedPort(port);
                    hardwareBridge.setPortConnected(isConnected, port);
                    if (isConnected) {
                        hardwareModeToggle.checked = true;
                        await hardwareBridge.setHardwareModeEnabled(true);
                    }
                } catch (_err) {
                    hardwareBridge.setPortConnected(false, port);
                }
                updateHardwareControlAvailability();
            });
        }

        hardwareStartBtn.addEventListener('click', async () => {
            const res = await hardwareBridge.startSession();
            if (!res.ok && hardwareSendStatus) {
                hardwareSendStatus.textContent = `สถานะการส่ง: เริ่มเซสชันไม่สำเร็จ (${res.message})`;
            }
            updateHardwareControlAvailability();
        });

        hardwareStopBtn.addEventListener('click', async () => {
            // หยุดการเล่นจำลองด้วย เพื่อไม่ให้ timer ยิงเซลล์ใหม่หลังหยุดฮาร์ดแวร์
            braillePlayback.pause();
            await hardwareBridge.stopSession('กดปุ่มหยุดและล้างเซลล์');
            updateHardwareControlAvailability();
        });

    async function ensureHardwareSessionActive() {
        if (hardwareBridge && hardwareBridge.isHardwareModeEnabled() && hardwareBridge.isPortConnected() && !hardwareBridge.isSessionActive()) {
            await hardwareBridge.startSession({ watchdogSeconds: 10 });
            if (braillePlayback.getCellCount() > 0 && (braillePlayback.getState() === 'completed' || braillePlayback.getState() === 'stopped')) {
                braillePlayback.restart();
            }
        }
    }

    if (hardwarePlayBtn) {
        hardwarePlayBtn.addEventListener('click', async () => {
            await ensureHardwareSessionActive();
            stopSpeech();
            applyBrailleTimingFromInputs();
            braillePlayback.play();
            updateHardwareControlAvailability();
        });
    }

    if (hardwarePauseBtn) {
        hardwarePauseBtn.addEventListener('click', () => {
            braillePlayback.pause();
            updateHardwareControlAvailability();
        });
    }

    if (hardwarePrevBtn) {
        hardwarePrevBtn.addEventListener('click', async () => {
            await ensureHardwareSessionActive();
            applyBrailleTimingFromInputs();
            braillePlayback.previous();
            updateHardwareControlAvailability();
        });
    }

    if (hardwareNextBtn) {
        hardwareNextBtn.addEventListener('click', async () => {
            await ensureHardwareSessionActive();
            applyBrailleTimingFromInputs();
            braillePlayback.next();
            updateHardwareControlAvailability();
        });
    }

        if (hardwareVerifyActivateBtn) {
            hardwareVerifyActivateBtn.addEventListener('click', () => {
                const pattern = hardwareVerifyPatternSelect ? hardwareVerifyPatternSelect.value : '';
                notifyHardware('verifyPattern', pattern);
            });
        }

        if (hardwareVerifyClearBtn) {
            hardwareVerifyClearBtn.addEventListener('click', () => {
                notifyHardware('verifyPattern', '000000');
            });
        }

        if (hardwareVerifyRecordBtn) {
            hardwareVerifyRecordBtn.addEventListener('click', () => {
                const record = {
                    pattern: hardwareVerifyPatternSelect ? hardwareVerifyPatternSelect.value : '',
                    expected_dot: hardwareVerifyPatternSelect
                        ? hardwareVerifyPatternSelect.selectedOptions?.[0]?.textContent
                        : '',
                    observed_dot: hardwareVerifyObservedInput ? hardwareVerifyObservedInput.value : '',
                    outcome: hardwareVerifyOutcomeSelect ? hardwareVerifyOutcomeSelect.value : 'unknown',
                };
                hardwareVerifyRecords.push(record);
                if (hardwareVerifyLog) {
                    const li = document.createElement('li');
                    li.textContent = `รูปแบบ ${record.pattern} | คาดหวัง: ${record.expected_dot} | ` +
                        `สังเกต: ${record.observed_dot || '—'} | ผล: ${record.outcome} ` +
                        '(บันทึกในหน้านี้เท่านั้น ยืนยันเฉพาะลำดับจุดเชิงตรรกะ ไม่ใช่ขา GPIO)';
                    hardwareVerifyLog.appendChild(li);
                }
            });
        }
    }

    // อายุการใช้งานของเบราว์เซอร์ (Step 6 ข้อ 7) - จัดการแบบระมัดระวัง เอกสารระบุ
    // ชัดว่า event เหล่านี้ "ไม่รับประกัน" ว่าจะยิง watchdog ฝั่งเซิร์ฟเวอร์เป็น
    // ด่านหลัก
    document.addEventListener('visibilitychange', () => {
        if (document.hidden || document.visibilityState === 'hidden') {
            braillePlayback.pause();
            notifyHardware('stopSession', 'แท็บถูกซ่อน (visibilitychange)');
        }
    });
    window.addEventListener('pagehide', () => {
        notifyHardware('stopSession', 'ออกจากหน้า (pagehide)');
    });
    // beforeunload เป็นสัญญาณเสริม best-effort เท่านั้น ไม่ใช่กลไกความปลอดภัยหลัก
    window.addEventListener('beforeunload', () => {
        notifyHardware('stopSession', 'ปิดหน้า (beforeunload)');
    });

    initHardwareControls();

    // Initialize Page - เรียกหลังประกาศ braillePlayback แล้วเท่านั้น เพราะ
    // initOcrWorkflow() -> resetOcrResult() -> resetBrailleTranslation() ต้อง
    // ใช้งาน braillePlayback ได้ทันที (ก่อนหน้านี้ initApp() เคยถูกเรียกไว้บนสุด
    // ของไฟล์ ทำให้ชน temporal dead zone ของ const braillePlayback)
    initApp();

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

        // นโยบายที่เลือกใช้ (Step 5 ข้อ 10): ถ้าผู้ใช้กด "ฟังข้อความอีกครั้ง"
        // ระหว่างกำลังเล่นเบรลล์อยู่ ให้หยุดการเล่นเบรลล์ชั่วคราวก่อนเสมอ (ไม่ใช่
        // หยุดเสียงพูด) เพื่อไม่ให้ทั้งสองอย่างแข่งกันดึงความสนใจของผู้ใช้พร้อมกัน
        // ตำแหน่งการเล่นเบรลล์ยังคงอยู่ ผู้ใช้กดเล่นต่อได้เองหลังฟังจบ
        braillePlayback.pause();

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

        // เริ่มแปลเป็นอักษรเบรลล์แบบ async แยกต่างหาก - ไม่บล็อกการยืนยันข้างบน
        // และห้าม throw ออกมาเป็น unhandled rejection ไม่ว่ากรณีใด
        translateConfirmedTextToBraille(recognizedText).catch(() => {});
    }

    const BRAILLE_ERROR_MESSAGES = {
        invalid_request_body: 'คำขอไม่ถูกต้อง',
        missing_text: 'ไม่พบข้อความที่จะแปล',
        invalid_text_type: 'ชนิดข้อมูลของข้อความไม่ถูกต้อง',
        empty_text: 'ข้อความว่างเปล่า ไม่สามารถแปลงเป็นอักษรเบรลล์ได้',
        text_too_long: 'ข้อความยาวเกินกำหนดสำหรับการแปลงเป็นอักษรเบรลล์',
        translator_unavailable: 'เครื่องมือแปลอักษรเบรลล์ (Liblouis) ยังไม่พร้อมใช้งานบนเซิร์ฟเวอร์นี้',
        table_unavailable: 'ไม่พบตารางอักษรเบรลล์ไทยที่ต้องใช้บนเซิร์ฟเวอร์นี้',
        translation_timeout: 'การแปลงเป็นอักษรเบรลล์ใช้เวลานานเกินไป',
        invalid_translator_output: 'ผลลัพธ์จากเครื่องมือแปลอักษรเบรลล์ไม่ถูกต้อง',
        translation_failed: 'การแปลงเป็นอักษรเบรลล์ล้มเหลว',
    };

    function renderBrailleCellDetails(cells) {
        brailleCellList.innerHTML = '';
        cells.forEach(cell => {
            const item = document.createElement('li');
            item.textContent = `เซลล์ ${cell.index + 1}: ${cell.bit_pattern} (${cell.unicode_braille}) จุด: ${cell.dot_numbers.join(', ') || 'ไม่มีจุดเปิด (เซลล์ว่าง)'}`;
            brailleCellList.appendChild(item);
        });
        brailleCellDetails.hidden = cells.length === 0;
    }

    // เรียกหลังยืนยันข้อความ OCR เสมอ (และเมื่อกดปุ่ม "ลองแปลงใหม่") ห่อทุก
    // เส้นทางความล้มเหลวไว้ภายในฟังก์ชันนี้ ไม่ throw ออกไปให้ caller ต้อง catch
    async function translateConfirmedTextToBraille(text) {
        if (!text) return;

        brailleSection.hidden = false;
        retryBrailleBtn.hidden = true;
        brailleResultSummary.hidden = true;
        brailleCellDetails.hidden = true;
        brailleStatus.textContent = 'กำลังแปลงข้อความที่ยืนยันแล้วเป็นอักษรเบรลล์ 6 จุด โปรดรอสักครู่';
        // เริ่มแปลใหม่ (รวมถึงตอนกด "ลองแปลงใหม่") ต้องล้างการเล่นเบรลล์เดิมทิ้ง
        // ก่อนเสมอ ยกเลิก timer เก่าทั้งหมด ไม่ให้ลำดับเก่าค้างอยู่ระหว่างรอผลใหม่
        resetBraillePlayback();

        try {
            const response = await fetch('/api/braille/translate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text }),
            });
            const data = await response.json().catch(() => null);

            if (!response.ok || !data || !data.ok) {
                const code = data?.error?.code;
                const friendlyMessage = BRAILLE_ERROR_MESSAGES[code] || 'ไม่สามารถแปลงข้อความเป็นอักษรเบรลล์ได้';
                const detail = data?.error?.message ? ` (${data.error.message})` : '';
                brailleStatus.textContent = `แปลงเป็นอักษรเบรลล์ไม่สำเร็จ: ${friendlyMessage}${detail} คุณยังฟังข้อความเดิมซ้ำและยืนยันแล้วได้ตามปกติ ลองแปลงใหม่ได้ด้วยปุ่มด้านล่าง`;
                brailleStatus.setAttribute('aria-live', 'assertive');
                retryBrailleBtn.hidden = false;
                addLog(`❌ แปลงอักษรเบรลล์ไม่สำเร็จ: ${friendlyMessage}`, 'error');
                return;
            }

            brailleStatus.setAttribute('aria-live', 'polite');
            brailleStatus.textContent = `แปลงเป็นอักษรเบรลล์สำเร็จ จำนวน ${data.cell_count} เซลล์`;

            const warningCount = (data.diagnostics || []).length;
            const warningNote = warningCount > 0
                ? ` มีคำเตือนระหว่างแปล ${warningCount} รายการ (ดูรายละเอียดในส่วนสำหรับนักพัฒนา)`
                : ' ไม่มีคำเตือนระหว่างแปล';
            brailleResultSummary.textContent =
                `เครื่องมือแปล: ${data.engine}${data.engine_version ? ' เวอร์ชัน ' + data.engine_version : ''} ` +
                `ตาราง: ${data.table}${warningNote} ` +
                'ข้อมูลนี้ยังไม่ถูกส่งไปยัง ESP32';
            brailleResultSummary.hidden = false;

            renderBrailleCellDetails(data.cells || []);
            addLog(`✓ แปลงข้อความเป็นอักษรเบรลล์สำเร็จ (${data.cell_count} เซลล์, ยังไม่ส่งไปยัง ESP32)`, 'success');

            // Step 5: โหลดลำดับเข้าตัวเล่น - "โหลดสำเร็จ" ไม่ได้แปลว่า "เริ่มเล่น
            // อัตโนมัติ" ผู้ใช้ต้องกด "เริ่มเล่น" เอง ย้าย focus ไปที่ปุ่มเริ่มเล่น
            // เพื่อให้ผู้ใช้โปรแกรมอ่านหน้าจอไปถึงส่วนควบคุมได้ทันที
            braillePlaybackSection.hidden = false;
            braillePlayback.load(data.cells || [], data.line_boundaries || []);
            braillePlayBtn.focus();
        } catch (_error) {
            brailleStatus.setAttribute('aria-live', 'assertive');
            brailleStatus.textContent = 'ไม่สามารถเชื่อมต่อบริการแปลงอักษรเบรลล์ได้ กรุณาตรวจสอบเซิร์ฟเวอร์แล้วลองอีกครั้ง';
            retryBrailleBtn.hidden = false;
            addLog('❌ ไม่สามารถเชื่อมต่อบริการแปลงอักษรเบรลล์ได้', 'error');
        }
    }

    retryBrailleBtn.addEventListener('click', () => {
        translateConfirmedTextToBraille(recognizedText).catch(() => {});
    });

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
                if (hardwareCurrentCharDisplay) {
                    hardwareCurrentCharDisplay.textContent = `'${char}'`;
                    if (hardwareCurrentCellDetail) {
                        hardwareCurrentCellDetail.textContent = `รูปแบบ 6 บิต: ${pattern} (ส่งข้อมูลตัวอักษรเดี่ยวสำเร็จ)`;
                    }
                }
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
                if (hardwareBridge && !hardwareBridge.isHardwareModeEnabled()) {
                    hardwareBridge.setSelectedPort(data.active_port || 'COM3');
                    hardwareBridge.setPortConnected(true, data.active_port || 'COM3');
                    if (hardwareModeToggle) hardwareModeToggle.checked = true;
                    hardwareBridge.setHardwareModeEnabled(true);
                }
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
