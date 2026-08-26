'use strict';

/**
 * Behavioral tests for the accessible OCR + text-to-speech workflow in
 * static/script.js. Uses Node's built-in test runner and a hand-rolled fake
 * DOM (tests/js/fake-dom.js) so no external test framework or npm install is
 * required.
 *
 * Run with: node --test tests/js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { createEnv } = require('./fake-dom');

function pngFile(name = 'sample.png') {
    return { name, type: 'image/png' };
}

async function runSuccessfulOcr(env, { text = 'สวัสดี', lowConfidence = false } = {}) {
    env.selectImage(pngFile());
    env.queueOcrResponse({ ok: true, text, low_confidence: lowConfidence });
    await env.processImage();
}

test('OCR success enables Confirm immediately', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);

    assert.equal(env.elements.confirmOcrBtn.disabled, false);
    assert.equal(env.elements.confirmOcrBtn.getAttribute('aria-disabled'), 'false');
});

test('Confirm does not wait for speech.onend', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);

    // No speech has been started at all (listenAgainBtn never clicked), yet
    // Confirm must already be usable and produce the local confirmation.
    assert.equal(env.elements.confirmOcrBtn.disabled, false);
    env.elements.confirmOcrBtn.click();

    assert.match(env.elements.ocrStatus.textContent, /ยืนยันข้อความแล้ว/);
});

test('Speech starts from an explicit button click', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);

    assert.equal(env.speechSynthesis.spoken.length, 0);
    env.elements.listenAgainBtn.click();

    assert.ok(env.speechSynthesis.spoken.length > 0, 'speak() should be called from the click handler');
    assert.ok(env.speechSynthesis.cancelCallCount >= 1, 'a fresh play should cancel any prior speech first');
});

test('Empty initial voice list is handled without crashing and without blocking Confirm', async () => {
    const env = createEnv();
    env.speechSynthesis.setVoices([]); // getVoices() returns [] initially, as in real browsers
    await runSuccessfulOcr(env);

    assert.doesNotThrow(() => env.elements.listenAgainBtn.click());
    assert.ok(env.speechSynthesis.spoken.length > 0);
    assert.equal(env.speechSynthesis.spoken[0].voice, null);
    assert.equal(env.elements.confirmOcrBtn.disabled, false);
});

test('voiceschanged updates the available voices used for playback', async () => {
    const env = createEnv();
    env.speechSynthesis.setVoices([]);
    await runSuccessfulOcr(env, { text: 'Hello' });

    const enVoice = { name: 'English Voice', lang: 'en-US' };
    env.speechSynthesis.setVoices([enVoice]);
    env.speechSynthesis.fireVoicesChanged();

    env.elements.listenAgainBtn.click();
    assert.equal(env.speechSynthesis.spoken[0].voice, enVoice);
});

test('Missing Thai voice uses a safe lang fallback instead of crashing', async () => {
    const env = createEnv();
    env.speechSynthesis.setVoices([{ name: 'English Voice', lang: 'en-US' }]);
    await runSuccessfulOcr(env, { text: 'สวัสดี' });

    env.elements.listenAgainBtn.click();

    const utterance = env.speechSynthesis.spoken[0];
    assert.equal(utterance.voice, null);
    assert.equal(utterance.lang, 'th-TH');
    assert.equal(env.elements.confirmOcrBtn.disabled, false);
});

test('speech.onerror leaves Confirm enabled and announces a fallback message', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);

    env.elements.listenAgainBtn.click();
    const utterance = env.speechSynthesis.spoken[0];
    assert.equal(env.elements.confirmOcrBtn.disabled, false);

    utterance.onerror({ error: 'synthesis-failed' });

    assert.equal(env.elements.confirmOcrBtn.disabled, false, 'Confirm must stay enabled after a speech error');
    assert.match(env.elements.ocrStatus.textContent, /ไม่สามารถอ่านออกเสียงด้วยเบราว์เซอร์ได้/);
});

test('onstart only fires the "reading" status after speak() is called, not before', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);

    env.elements.listenAgainBtn.click();
    // Immediately after the click, speak() has been invoked but onstart has
    // not fired yet — status must not already claim playback started.
    assert.doesNotMatch(env.elements.ocrStatus.textContent, /^สถานะ: กำลังอ่านข้อความ$/);

    env.speechSynthesis.spoken[0].onstart();
    assert.match(env.elements.ocrStatus.textContent, /กำลังอ่านข้อความ/);
});

test('onend announces completion and keeps Confirm enabled', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env, { text: 'Hi' });

    env.elements.listenAgainBtn.click();
    const utterance = env.speechSynthesis.spoken[0];
    utterance.onstart();
    utterance.onend();

    assert.match(env.elements.ocrStatus.textContent, /อ่านจบแล้ว คุณสามารถยืนยัน ฟังอีกครั้ง หรือเลือกภาพใหม่ได้/);
    assert.equal(env.elements.confirmOcrBtn.disabled, false);
});

test('Reset cancels speech and disables Confirm', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.elements.listenAgainBtn.click();
    assert.equal(env.elements.confirmOcrBtn.disabled, false);

    const cancelsBefore = env.speechSynthesis.cancelCallCount;
    env.selectImage(pngFile('other.png'));

    assert.ok(env.speechSynthesis.cancelCallCount > cancelsBefore, 'selecting another image must cancel speech');
    assert.equal(env.elements.confirmOcrBtn.disabled, true);
    assert.equal(env.elements.confirmOcrBtn.getAttribute('aria-disabled'), 'true');
});

test('Confirm during speech cancels playback and completes locally without calling ESP32', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.elements.listenAgainBtn.click();

    const cancelsBefore = env.speechSynthesis.cancelCallCount;
    env.elements.confirmOcrBtn.click();

    assert.ok(env.speechSynthesis.cancelCallCount > cancelsBefore, 'confirming during playback must cancel speech');
    assert.match(env.elements.ocrStatus.textContent, /ยืนยันข้อความแล้ว/);
    assert.ok(!env.fetchCalls.some(call => call.url === '/send'), 'confirming must never call the ESP32 /send endpoint');
});

test('No OCR result is sent to ESP32 during the whole OCR + confirm flow', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.elements.listenAgainBtn.click();
    env.speechSynthesis.spoken[0].onend();
    env.elements.confirmOcrBtn.click();

    assert.ok(!env.fetchCalls.some(call => call.url === '/send'));
    const ocrCalls = env.fetchCalls.filter(call => call.url === '/api/ocr');
    assert.equal(ocrCalls.length, 1);
});

test('Empty OCR text keeps Confirm disabled', async () => {
    const env = createEnv();
    env.selectImage(pngFile());
    env.queueOcrResponse({ ok: true, text: '' });
    await env.processImage();

    assert.equal(env.elements.confirmOcrBtn.disabled, true);
    assert.equal(env.elements.confirmOcrBtn.getAttribute('aria-disabled'), 'true');
});

test('Confirm is disabled before OCR has run and while it is processing', async () => {
    const env = createEnv();
    assert.equal(env.elements.confirmOcrBtn.disabled, true, 'disabled before any OCR run');

    env.selectImage(pngFile());
    // Do not resolve the fetch yet — simulate "processing" by not awaiting.
    env.queueOcrResponse({ ok: true, text: 'สวัสดี' });
    env.elements.readImageBtn.click();
    assert.equal(env.elements.confirmOcrBtn.disabled, true, 'still disabled while OCR request is in flight');

    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
    await new Promise(resolve => setImmediate(resolve));
});

test('Confirm stays enabled and available when the browser has no speech support', async () => {
    const env = createEnv({ speechSupported: false });
    await runSuccessfulOcr(env);

    assert.equal(env.elements.confirmOcrBtn.disabled, false);
    env.elements.confirmOcrBtn.click();
    assert.match(env.elements.ocrStatus.textContent, /ยืนยันข้อความแล้ว/);
});
