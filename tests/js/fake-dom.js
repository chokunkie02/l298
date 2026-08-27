'use strict';

/**
 * Minimal fake DOM + browser API shim used to execute static/script.js inside
 * a Node vm context for behavioral tests, without any external dependencies
 * (no jsdom / npm packages required).
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ELEMENT_IDS = [
    'patternInput', 'sendBtn', 'btnAllOn', 'btnAllOff', 'btnClear',
    'binaryPatternDisplay', 'statusBadge', 'statusText', 'portSelect',
    'reconnectBtn', 'terminalLog', 'clearLogBtn', 'alphabetGrid',
    'ocrImageInput', 'readImageBtn', 'ocrStatus', 'ocrResultPanel',
    'ocrResultHeading', 'ocrRecognizedText', 'ocrConfidenceSummary',
    'ocrQualityWarnings', 'listenAgainBtn', 'confirmOcrBtn', 'chooseAnotherBtn',
    'dot1', 'dot2', 'dot3', 'dot4', 'dot5', 'dot6',
    'brailleTranslationSection', 'brailleStatus', 'brailleResultSummary',
    'retryBrailleBtn', 'brailleCellDetails', 'brailleCellList',
    'braillePreviewModeLabel', 'braillePlaybackSection', 'braillePlaybackAnnouncer',
    'brailleCurrentCellInfo', 'braillePlaybackStatusText', 'braillePlayBtn',
    'braillePauseBtn', 'braillePreviousBtn', 'brailleNextBtn', 'brailleRestartBtn',
    'brailleStopBtn', 'brailleCellDurationInput', 'brailleGapInput', 'brailleLinePauseInput',
    // Step 6: โหมดฮาร์ดแวร์จริง
    'hardwarePlaybackSection', 'hardwareModeToggle', 'hardwareModeStatus',
    'hardwarePortSelect', 'hardwareRefreshPortsBtn', 'hardwareConnectBtn',
    'hardwareConnectionStatus', 'hardwarePortIdentityNote', 'hardwareStartBtn',
    'hardwareStopBtn', 'hardwareSendStatus', 'hardwareWatchdogStatus',
    'hardwareVerifySection', 'hardwareVerifyPatternSelect', 'hardwareVerifyActivateBtn',
    'hardwareVerifyClearBtn', 'hardwareVerifyObservedInput', 'hardwareVerifyOutcomeSelect',
    'hardwareVerifyRecordBtn', 'hardwareVerifyLog',
];

class FakeClassList {
    constructor() {
        this._set = new Set();
    }
    add(...names) { names.forEach(n => this._set.add(n)); }
    remove(...names) { names.forEach(n => this._set.delete(n)); }
    contains(name) { return this._set.has(name); }
}

class FakeElement {
    constructor(id) {
        this.id = id || null;
        this._listeners = {};
        this.classList = new FakeClassList();
        this.dataset = {};
        this._attributes = {};
        this.hidden = false;
        this.disabled = false;
        this.value = '';
        this.textContent = '';
        this.innerHTML = '';
        this.lang = '';
        this.style = {};
        this.children = [];
        this.focusCallCount = 0;
        this.files = null;
        this.type = '';
    }
    addEventListener(type, cb) {
        (this._listeners[type] = this._listeners[type] || []).push(cb);
    }
    removeEventListener(type, cb) {
        if (!this._listeners[type]) return;
        this._listeners[type] = this._listeners[type].filter(fn => fn !== cb);
    }
    dispatch(type, evt) {
        (this._listeners[type] || []).slice().forEach(cb => cb(evt));
    }
    click() { this.dispatch('click'); }
    focus() { this.focusCallCount += 1; }
    setAttribute(name, value) { this._attributes[name] = String(value); }
    getAttribute(name) {
        return Object.prototype.hasOwnProperty.call(this._attributes, name)
            ? this._attributes[name]
            : null;
    }
    removeAttribute(name) { delete this._attributes[name]; }
    appendChild(child) { this.children.push(child); return child; }
}

class FakeUtterance {
    constructor(text) {
        this.text = text;
        this.lang = '';
        this.voice = null;
        this.onstart = null;
        this.onend = null;
        this.onerror = null;
    }
}

function createSpeechSynthesis() {
    const spoken = [];
    let voiceschangedListeners = [];
    let voices = [];
    const synth = {
        paused: false,
        cancelCallCount: 0,
        resumeCallCount: 0,
        get spoken() { return spoken; },
        getVoices: () => voices,
        setVoices(list) { voices = list; },
        cancel() {
            synth.cancelCallCount += 1;
            synth.paused = false;
        },
        resume() {
            synth.resumeCallCount += 1;
            synth.paused = false;
        },
        pause() { synth.paused = true; },
        speak(utterance) { spoken.push(utterance); },
        addEventListener(type, cb) {
            if (type === 'voiceschanged') voiceschangedListeners.push(cb);
        },
        removeEventListener(type, cb) {
            voiceschangedListeners = voiceschangedListeners.filter(fn => fn !== cb);
        },
        fireVoicesChanged() { voiceschangedListeners.slice().forEach(cb => cb()); },
    };
    return synth;
}

// Timer จำลองแบบ deterministic สำหรับ static/braille_playback.js - ไม่รอเวลา
// จริงเลย เทสต์ต้องเรียก fireAllTimers() เองเพื่อจำลองว่าเวลาผ่านไปครบกำหนด
// ของ timer ที่ค้างอยู่ ณ ขณะนั้น (เหมือนกับ createFakeClock ใน
// braille_playback.test.js แต่ต้องแยกกันเพราะไฟล์นี้รันผ่าน vm sandbox)
function createFakeTimerQueue() {
    const pending = new Map();
    let nextId = 1;
    return {
        setTimeoutFn(callback, delay) {
            const id = nextId++;
            pending.set(id, { callback, delay });
            return id;
        },
        clearTimeoutFn(id) {
            pending.delete(id);
        },
        pendingCount() {
            return pending.size;
        },
        fireAll() {
            const toFire = [...pending.entries()];
            pending.clear();
            toFire.forEach(([, t]) => t.callback());
        },
    };
}

class FakeFormData {
    constructor() { this.entries = []; }
    append(name, value, filename) { this.entries.push([name, value, filename]); }
}

function defaultStatusResponse() {
    return {
        ok: true,
        json: () => Promise.resolve({ connected: false, active_port: 'COM3', available_ports: [] }),
    };
}

/**
 * @param {object} options
 * @param {boolean} [options.speechSupported=true]
 */
function createEnv(options = {}) {
    const speechSupported = options.speechSupported !== false;

    const elements = {};
    ELEMENT_IDS.forEach(id => { elements[id] = new FakeElement(id); });

    const documentListeners = {};
    const fakeDocument = {
        activeElement: null,
        hidden: false,
        visibilityState: 'visible',
        getElementById: id => elements[id] || null,
        querySelectorAll: () => [],
        createElement: tag => new FakeElement(null, tag),
        addEventListener(type, cb) {
            (documentListeners[type] = documentListeners[type] || []).push(cb);
        },
        dispatch(type) {
            (documentListeners[type] || []).forEach(cb => cb());
        },
    };

    let ocrResponseQueue = [];
    let brailleResponseQueue = [];
    const hardwareResponseQueues = {};
    const fetchCalls = [];
    function hardwareResponse(url) {
        const q = hardwareResponseQueues[url] || [];
        const next = q.shift();
        if (!next) {
            // ค่าเริ่มต้นที่ปลอดภัย: ตอบ ok เปล่า ๆ (เทสต์ที่สนใจต้อง queue เอง)
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
        }
        if (next.reject) return Promise.reject(next.reject);
        return Promise.resolve({
            ok: next.ok !== false,
            json: () => Promise.resolve(next.body),
        });
    }
    function fetchMock(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/status') {
            return Promise.resolve(defaultStatusResponse());
        }
        if (typeof url === 'string' && url.startsWith('/api/hardware/')) {
            return hardwareResponse(url);
        }
        if (url === '/api/connect') {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, active_port: 'mock', message: 'ok' }) });
        }
        if (url === '/api/ocr') {
            const next = ocrResponseQueue.shift();
            if (!next) {
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, text: '' }) });
            }
            if (next.reject) {
                return Promise.reject(next.reject);
            }
            return Promise.resolve({
                ok: next.ok !== false,
                json: () => Promise.resolve(next.body),
            });
        }
        if (url === '/api/braille/translate') {
            const next = brailleResponseQueue.shift();
            if (!next) {
                return Promise.reject(new Error('no /api/braille/translate response queued in test'));
            }
            if (next.reject) {
                return Promise.reject(next.reject);
            }
            return Promise.resolve({
                ok: next.ok !== false,
                json: () => Promise.resolve(next.body),
            });
        }
        return Promise.reject(new Error(`unhandled fetch url in test: ${url}`));
    }

    const windowListeners = {};
    const timerQueue = createFakeTimerQueue();
    const sandbox = {};
    sandbox.window = sandbox;
    sandbox.document = fakeDocument;
    sandbox.console = console;
    sandbox.fetch = fetchMock;
    sandbox.FormData = FakeFormData;
    sandbox.setInterval = () => 0;
    sandbox.clearInterval = () => {};
    // static/braille_playback.js ใช้ setTimeout/clearTimeout จริงเป็นค่าเริ่มต้น
    // เมื่อไม่ได้ inject (คือกรณีการใช้งานจริงใน script.js) - vm context ไม่มี
    // timer ของ Node ให้อัตโนมัติ จึงต้องจำลองเองแบบ deterministic ที่นี่
    sandbox.setTimeout = timerQueue.setTimeoutFn;
    sandbox.clearTimeout = timerQueue.clearTimeoutFn;
    sandbox.addEventListener = (type, cb) => {
        (windowListeners[type] = windowListeners[type] || []).push(cb);
    };

    let speechSynthesis = null;
    if (speechSupported) {
        speechSynthesis = createSpeechSynthesis();
        sandbox.speechSynthesis = speechSynthesis;
        sandbox.SpeechSynthesisUtterance = FakeUtterance;
    }

    const context = vm.createContext(sandbox);

    // โหลด braille_playback.js ก่อน script.js เสมอ เลียนแบบลำดับ <script> จริง
    // ในหน้า HTML (ดู templates/index.html) เพื่อให้ window.BraillePlaybackController
    // พร้อมใช้งานตอน script.js สร้าง instance
    const playbackScriptPath = path.join(__dirname, '..', '..', 'static', 'braille_playback.js');
    const playbackScriptSource = fs.readFileSync(playbackScriptPath, 'utf-8');
    vm.runInContext(playbackScriptSource, context, { filename: 'braille_playback.js' });

    const hardwareScriptPath = path.join(__dirname, '..', '..', 'static', 'braille_hardware.js');
    vm.runInContext(fs.readFileSync(hardwareScriptPath, 'utf-8'), context, { filename: 'braille_hardware.js' });

    const scriptPath = path.join(__dirname, '..', '..', 'static', 'script.js');
    const scriptSource = fs.readFileSync(scriptPath, 'utf-8');
    vm.runInContext(scriptSource, context, { filename: 'script.js' });

    // Boot the app the same way a real page load would.
    fakeDocument.dispatch('DOMContentLoaded');

    return {
        elements,
        speechSynthesis,
        fetchCalls,
        document: fakeDocument,
        queueHardwareResponse(url, body, opts = {}) {
            (hardwareResponseQueues[url] = hardwareResponseQueues[url] || []).push({ body, ...opts });
        },
        hardwareCalls() {
            return fetchCalls.filter(c => typeof c.url === 'string' && c.url.startsWith('/api/hardware/'));
        },
        dispatchWindow(type, evt) {
            (windowListeners[type] || []).slice().forEach(cb => cb(evt || {}));
        },
        dispatchDocument(type) {
            fakeDocument.dispatch(type);
        },
        // จำลองเวลาผ่านไปสำหรับ static/braille_playback.js - ยิง timer ที่ค้าง
        // อยู่ทั้งหมด ณ ตอนนี้ (ปกติมีแค่ 1 ตัวตามสเปก Step 5)
        fireAllTimers() {
            timerQueue.fireAll();
        },
        pendingTimerCount() {
            return timerQueue.pendingCount();
        },
        queueOcrResponse(body, opts = {}) {
            ocrResponseQueue.push({ body, ...opts });
        },
        queueOcrNetworkError(error) {
            ocrResponseQueue.push({ reject: error || new Error('network down') });
        },
        queueBrailleResponse(body, opts = {}) {
            brailleResponseQueue.push({ body, ...opts });
        },
        queueBrailleNetworkError(error) {
            brailleResponseQueue.push({ reject: error || new Error('network down') });
        },
        selectImage(file) {
            elements.ocrImageInput.files = [file];
            elements.ocrImageInput.dispatch('change');
        },
        async settle() {
            // Allow pending fetch/json microtasks (OCR or Braille translation) to resolve.
            await new Promise(resolve => setImmediate(resolve));
            await new Promise(resolve => setImmediate(resolve));
            await new Promise(resolve => setImmediate(resolve));
        },
        async processImage() {
            elements.readImageBtn.click();
            await this.settle();
        },
        async confirmAndTranslate() {
            elements.confirmOcrBtn.click();
            await this.settle();
        },
    };
}

module.exports = { createEnv, FakeElement };
