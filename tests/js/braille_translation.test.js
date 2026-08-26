'use strict';

/**
 * Behavioral tests for the Step 4 accessible Braille-translation UI added on
 * top of the OCR + confirm workflow in static/script.js. Uses the same fake
 * DOM harness as tests/js/ocr_tts.test.js — no external dependencies.
 *
 * Run with: node --test tests/js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { createEnv } = require('./fake-dom');

function pngFile(name = 'sample.png') {
    return { name, type: 'image/png' };
}

async function runSuccessfulOcr(env, { text = 'สวัสดี' } = {}) {
    env.selectImage(pngFile());
    env.queueOcrResponse({ ok: true, text, low_confidence: false });
    await env.processImage();
}

function sampleCell(index, bitPattern, bitmask, dots) {
    return {
        index,
        unicode_braille: String.fromCodePoint(0x2800 + bitmask),
        dot_numbers: dots,
        bitmask,
        bit_pattern: bitPattern,
    };
}

test('confirming non-empty OCR text sends exactly one request to /api/braille/translate', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.queueBrailleResponse({
        ok: true, source_text: 'สวัสดี', normalized_text: 'สวัสดี',
        cells: [sampleCell(0, '111111', 63, [1, 2, 3, 4, 5, 6])],
        line_boundaries: [], cell_count: 1, diagnostics: [],
        engine: 'liblouis', engine_version: '3.29.0', table: 'th-g1.utb', sent_to_hardware: false,
    });

    await env.confirmAndTranslate();

    const brailleCalls = env.fetchCalls.filter(call => call.url === '/api/braille/translate');
    assert.equal(brailleCalls.length, 1);
    assert.equal(JSON.parse(brailleCalls[0].opts.body).text, 'สวัสดี');
    assert.ok(!env.fetchCalls.some(call => call.url === '/send'), 'must never call /send');
    assert.ok(!env.fetchCalls.some(call => call.url === '/api/send'), 'must never call /api/send');
});

test('successful translation announces cell count and shows engine/table/no-hardware summary', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.queueBrailleResponse({
        ok: true, cells: [
            sampleCell(0, '100000', 1, [1]),
            sampleCell(1, '110000', 3, [1, 2]),
        ],
        line_boundaries: [], cell_count: 2, diagnostics: [],
        engine: 'liblouis-python', engine_version: '3.29.0', table: 'th-g1.utb', sent_to_hardware: false,
    });

    await env.confirmAndTranslate();

    assert.match(env.elements.brailleStatus.textContent, /สำเร็จ/);
    assert.match(env.elements.brailleStatus.textContent, /2 เซลล์/);
    assert.equal(env.elements.brailleResultSummary.hidden, false);
    assert.match(env.elements.brailleResultSummary.textContent, /liblouis-python/);
    assert.match(env.elements.brailleResultSummary.textContent, /th-g1\.utb/);
    assert.match(env.elements.brailleResultSummary.textContent, /ยังไม่ถูกส่งไปยัง ESP32/);
    assert.equal(env.elements.retryBrailleBtn.hidden, true);
});

test('diagnostics/warnings are announced in the result summary', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.queueBrailleResponse({
        ok: true, cells: [sampleCell(0, '100000', 1, [1])],
        line_boundaries: [], cell_count: 1,
        diagnostics: [{ severity: 'warning', code: 'unsupported_dots_7_or_8', description: 'x', source_index: 0, character: null }],
        engine: 'liblouis', engine_version: '3.29.0', table: 'th-g1.utb', sent_to_hardware: false,
    });

    await env.confirmAndTranslate();

    assert.match(env.elements.brailleResultSummary.textContent, /คำเตือน.*1 รายการ/);
});

test('structured translation failure is announced clearly and offers retry', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.queueBrailleResponse({
        ok: false,
        error: { code: 'translator_unavailable', message: 'ไม่พบ Liblouis' },
    }, { ok: false });

    await env.confirmAndTranslate();

    assert.match(env.elements.brailleStatus.textContent, /ไม่สำเร็จ/);
    assert.equal(env.elements.brailleStatus.getAttribute('aria-live'), 'assertive');
    assert.equal(env.elements.retryBrailleBtn.hidden, false);
    assert.equal(env.elements.brailleResultSummary.hidden, true);
});

test('network failure calling the translation endpoint is announced and offers retry', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.queueBrailleNetworkError(new Error('network down'));

    await env.confirmAndTranslate();

    assert.match(env.elements.brailleStatus.textContent, /ไม่สามารถเชื่อมต่อ/);
    assert.equal(env.elements.retryBrailleBtn.hidden, false);
});

test('retry button re-sends the same confirmed text to the translation endpoint', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env, { text: 'ทดสอบ' });
    env.queueBrailleNetworkError(new Error('network down'));
    await env.confirmAndTranslate();
    assert.equal(env.elements.retryBrailleBtn.hidden, false);

    env.queueBrailleResponse({
        ok: true, cells: [sampleCell(0, '100000', 1, [1])],
        line_boundaries: [], cell_count: 1, diagnostics: [],
        engine: 'liblouis', engine_version: '3.29.0', table: 'th-g1.utb', sent_to_hardware: false,
    });
    env.elements.retryBrailleBtn.click();
    await env.settle();

    const brailleCalls = env.fetchCalls.filter(call => call.url === '/api/braille/translate');
    assert.equal(brailleCalls.length, 2);
    assert.equal(JSON.parse(brailleCalls[1].opts.body).text, 'ทดสอบ');
    assert.match(env.elements.brailleStatus.textContent, /สำเร็จ/);
    assert.equal(env.elements.retryBrailleBtn.hidden, true);
});

test('confirmed OCR text remains available for Listen Again after translation runs', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env, { text: 'ฟังอีกครั้ง' });
    env.queueBrailleResponse({
        ok: true, cells: [], line_boundaries: [], cell_count: 0, diagnostics: [],
        engine: 'liblouis', engine_version: '3.29.0', table: 'th-g1.utb', sent_to_hardware: false,
    });

    await env.confirmAndTranslate();

    assert.equal(env.elements.ocrRecognizedText.textContent, 'ฟังอีกครั้ง');
});

test('Braille section resets when another image is selected', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.queueBrailleResponse({
        ok: true, cells: [sampleCell(0, '100000', 1, [1])],
        line_boundaries: [], cell_count: 1, diagnostics: [],
        engine: 'liblouis', engine_version: '3.29.0', table: 'th-g1.utb', sent_to_hardware: false,
    });
    await env.confirmAndTranslate();
    assert.equal(env.elements.brailleTranslationSection.hidden, false);

    env.selectImage(pngFile('other.png'));

    assert.equal(env.elements.brailleTranslationSection.hidden, true);
    assert.equal(env.elements.brailleStatus.textContent, '');
    assert.equal(env.elements.retryBrailleBtn.hidden, true);
});

test('developer cell-details view is populated but not required for the accessible summary', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.queueBrailleResponse({
        ok: true, cells: [sampleCell(0, '111111', 63, [1, 2, 3, 4, 5, 6])],
        line_boundaries: [], cell_count: 1, diagnostics: [],
        engine: 'liblouis', engine_version: '3.29.0', table: 'th-g1.utb', sent_to_hardware: false,
    });

    await env.confirmAndTranslate();

    assert.equal(env.elements.brailleCellDetails.hidden, false);
    assert.equal(env.elements.brailleCellList.children.length, 1);
    // The accessible summary must stand on its own without requiring this view.
    assert.match(env.elements.brailleStatus.textContent, /1 เซลล์/);
});

test('translation is never triggered before Confirm is clicked', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);

    assert.ok(!env.fetchCalls.some(call => call.url === '/api/braille/translate'));
    assert.equal(env.elements.brailleTranslationSection.hidden, true);
});

test('empty OCR result never triggers a Braille translation request', async () => {
    const env = createEnv();
    env.selectImage(pngFile());
    env.queueOcrResponse({ ok: true, text: '' });
    await env.processImage();

    assert.ok(!env.fetchCalls.some(call => call.url === '/api/braille/translate'));
});
