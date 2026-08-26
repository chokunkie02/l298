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
    const fetchCalls = [];
    function fetchMock(url, opts) {
        fetchCalls.push({ url, opts });
        if (url === '/api/status') {
            return Promise.resolve(defaultStatusResponse());
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
        return Promise.reject(new Error(`unhandled fetch url in test: ${url}`));
    }

    const windowListeners = {};
    const sandbox = {};
    sandbox.window = sandbox;
    sandbox.document = fakeDocument;
    sandbox.console = console;
    sandbox.fetch = fetchMock;
    sandbox.FormData = FakeFormData;
    sandbox.setInterval = () => 0;
    sandbox.clearInterval = () => {};
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
    const scriptPath = path.join(__dirname, '..', '..', 'static', 'script.js');
    const scriptSource = fs.readFileSync(scriptPath, 'utf-8');
    vm.runInContext(scriptSource, context, { filename: 'script.js' });

    // Boot the app the same way a real page load would.
    fakeDocument.dispatch('DOMContentLoaded');

    return {
        elements,
        speechSynthesis,
        fetchCalls,
        queueOcrResponse(body, opts = {}) {
            ocrResponseQueue.push({ body, ...opts });
        },
        queueOcrNetworkError(error) {
            ocrResponseQueue.push({ reject: error || new Error('network down') });
        },
        selectImage(file) {
            elements.ocrImageInput.files = [file];
            elements.ocrImageInput.dispatch('change');
        },
        async processImage() {
            elements.readImageBtn.click();
            // Allow the pending fetch/json microtasks in processImage() to settle.
            await new Promise(resolve => setImmediate(resolve));
            await new Promise(resolve => setImmediate(resolve));
            await new Promise(resolve => setImmediate(resolve));
        },
    };
}

module.exports = { createEnv, FakeElement };
