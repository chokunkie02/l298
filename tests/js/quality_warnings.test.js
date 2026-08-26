'use strict';

/**
 * Behavioral tests for the accessible image-quality warning UI added on top
 * of the OCR + TTS workflow in static/script.js. Uses the same fake DOM
 * harness as tests/js/ocr_tts.test.js — no external dependencies.
 *
 * Run with: node --test tests/js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { createEnv } = require('./fake-dom');

function pngFile(name = 'sample.png') {
    return { name, type: 'image/png' };
}

async function runOcr(env, { text = 'สวัสดี', imageQuality } = {}) {
    env.selectImage(pngFile());
    env.queueOcrResponse({
        ok: true,
        text,
        low_confidence: false,
        image_quality: imageQuality,
        preprocessing: { mode: 'resize', upscaled: false },
    });
    await env.processImage();
}

test('quality warnings are rendered with an icon and text, not color alone', async () => {
    const env = createEnv();
    await runOcr(env, {
        imageQuality: { width: 100, height: 100, mean_brightness: 20, contrast: 5, blur_score: 10, warnings: ['dark', 'blurry'] },
    });

    const box = env.elements.ocrQualityWarnings;
    assert.equal(box.hidden, false);
    assert.match(box.innerHTML, /fa-triangle-exclamation/);
    assert.match(box.innerHTML, /ภาพอาจมืดเกินไป/);
    assert.match(box.innerHTML, /ภาพอาจเบลอ/);
});

test('quality warnings do not block Confirm or OCR result availability', async () => {
    const env = createEnv();
    await runOcr(env, {
        imageQuality: { width: 100, height: 100, mean_brightness: 20, contrast: 5, blur_score: 10, warnings: ['dark', 'low_contrast', 'blurry'] },
    });

    assert.equal(env.elements.confirmOcrBtn.disabled, false);
    assert.equal(env.elements.listenAgainBtn.disabled, false);
    assert.equal(env.elements.ocrRecognizedText.textContent, 'สวัสดี');
});

test('no warnings shown when image quality is good', async () => {
    const env = createEnv();
    await runOcr(env, {
        imageQuality: { width: 100, height: 100, mean_brightness: 130, contrast: 60, blur_score: 300, warnings: [] },
    });

    assert.equal(env.elements.ocrQualityWarnings.hidden, true);
    assert.match(env.elements.ocrStatus.textContent, /ภาพมีความคมชัดเพียงพอสำหรับการอ่านข้อความ/);
});

test('quality warning summary is also announced through the existing aria-live status', async () => {
    const env = createEnv();
    await runOcr(env, {
        imageQuality: { width: 100, height: 100, mean_brightness: 230, contrast: 5, blur_score: 300, warnings: ['bright', 'low_contrast'] },
    });

    assert.equal(env.elements.ocrStatus.getAttribute('aria-live'), 'polite');
    assert.match(env.elements.ocrStatus.textContent, /ภาพอาจสว่าง/);
    assert.match(env.elements.ocrStatus.textContent, /ความต่างของสีระหว่างตัวอักษรกับพื้นหลังน้อยเกินไป/);
});

test('Capture Another Image remains available and reachable when quality is poor', async () => {
    const env = createEnv();
    await runOcr(env, {
        imageQuality: { width: 100, height: 100, mean_brightness: 20, contrast: 5, blur_score: 10, warnings: ['dark', 'blurry'] },
    });

    assert.match(env.elements.ocrQualityWarnings.innerHTML, /ถ่ายหรือเลือกภาพอื่น/);
    assert.equal(env.elements.chooseAnotherBtn.disabled, false);
});

test('missing image_quality in the response (older server) does not crash and shows no warning box', async () => {
    const env = createEnv();
    await runOcr(env, { imageQuality: undefined });

    assert.equal(env.elements.ocrQualityWarnings.hidden, true);
    assert.equal(env.elements.confirmOcrBtn.disabled, false);
});

test('quality warning box and aria-live status reset when another image is selected', async () => {
    const env = createEnv();
    await runOcr(env, {
        imageQuality: { width: 100, height: 100, mean_brightness: 20, contrast: 5, blur_score: 10, warnings: ['dark'] },
    });
    assert.equal(env.elements.ocrQualityWarnings.hidden, false);

    env.selectImage(pngFile('other.png'));

    assert.equal(env.elements.ocrQualityWarnings.hidden, true);
    assert.equal(env.elements.ocrQualityWarnings.innerHTML, '');
});

test('quality warnings on an empty-text OCR result still surface and Confirm stays disabled', async () => {
    const env = createEnv();
    await runOcr(env, {
        text: '',
        imageQuality: { width: 100, height: 100, mean_brightness: 20, contrast: 5, blur_score: 10, warnings: ['dark', 'blurry'] },
    });

    assert.equal(env.elements.confirmOcrBtn.disabled, true);
    assert.equal(env.elements.ocrQualityWarnings.hidden, false);
    assert.match(env.elements.ocrStatus.textContent, /ไม่พบข้อความในภาพ/);
    assert.match(env.elements.ocrStatus.textContent, /ภาพอาจมืดเกินไป/);
});
