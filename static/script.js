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

        // Set interval to poll status every 5 seconds
        setInterval(checkConnectionStatus, 5000);
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
