'use strict';

/**
 * เทสต์การเชื่อม static/braille_playback.js เข้ากับ DOM ใน static/script.js
 * (Step 5) - ใช้ fake DOM harness เดียวกับเทสต์อื่น ๆ พร้อม fake timer queue
 * แบบ deterministic (env.fireAllTimers()) ไม่มีการรอเวลาจริงเลย
 *
 * Run with: node --test tests/js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { createEnv } = require('./fake-dom');

function pngFile(name = 'sample.png') {
    return { name, type: 'image/png' };
}

function sampleCell(index, bitmask, dots) {
    const bitPattern = [1, 2, 3, 4, 5, 6].map(d => (bitmask & (1 << (d - 1)) ? '1' : '0')).join('');
    return {
        index,
        unicode_braille: String.fromCodePoint(0x2800 + bitmask),
        dot_numbers: dots,
        bitmask,
        bit_pattern: bitPattern,
    };
}

async function runSuccessfulOcr(env, { text = 'สวัสดี' } = {}) {
    env.selectImage(pngFile());
    env.queueOcrResponse({ ok: true, text, low_confidence: false });
    await env.processImage();
}

async function confirmWithBrailleCells(env, cells, lineBoundaries = [], text = 'สวัสดี') {
    await runSuccessfulOcr(env, { text });
    env.queueBrailleResponse({
        ok: true, cells, line_boundaries: lineBoundaries, cell_count: cells.length, diagnostics: [],
        engine: 'liblouis-cli', engine_version: '3.38.0', table: 'th-g1.utb', sent_to_hardware: false,
    });
    await env.confirmAndTranslate();
}

// --- Translation success/failure initializes/clears playback ---------------

test('successful translation loads playback but does not start it automatically', async () => {
    const env = createEnv();
    const cells = [sampleCell(0, 1, [1]), sampleCell(1, 2, [2]), sampleCell(2, 3, [1, 2])];
    await confirmWithBrailleCells(env, cells);

    assert.equal(env.elements.braillePlaybackSection.hidden, false);
    assert.match(env.elements.braillePlaybackStatusText.textContent, /พร้อมเล่น/);
    assert.equal(env.pendingTimerCount(), 0, 'loading must never start an automatic timer');
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เซลล์ 1 จาก 3/);
});

test('successful translation moves focus to the Play button', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1])]);
    assert.ok(env.elements.braillePlayBtn.focusCallCount > 0);
});

test('translation failure clears playback and keeps the playback section hidden', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.queueBrailleResponse({ ok: false, error: { code: 'translator_unavailable', message: 'x' } }, { ok: false });
    await env.confirmAndTranslate();

    assert.equal(env.elements.braillePlaybackSection.hidden, true);
});

test('network failure during translation clears playback too', async () => {
    const env = createEnv();
    await runSuccessfulOcr(env);
    env.queueBrailleNetworkError(new Error('down'));
    await env.confirmAndTranslate();

    assert.equal(env.elements.braillePlaybackSection.hidden, true);
});

test('a new OCR image resets any existing playback sequence', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    assert.equal(env.elements.braillePlaybackSection.hidden, false);

    env.selectImage(pngFile('other.png'));

    assert.equal(env.elements.braillePlaybackSection.hidden, true);
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /ยังไม่เริ่มเล่น/);
});

test('retrying translation resets the old playback sequence and old timers', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2]), sampleCell(2, 3, [1, 2])]);
    env.elements.braillePlayBtn.click();
    assert.equal(env.pendingTimerCount(), 1);

    env.queueBrailleResponse({
        ok: true, cells: [sampleCell(0, 5, [1, 3])], line_boundaries: [], cell_count: 1, diagnostics: [],
        engine: 'liblouis-cli', engine_version: '3.38.0', table: 'th-g1.utb', sent_to_hardware: false,
    });
    env.elements.retryBrailleBtn.hidden = false; // reachable regardless of visibility in the fake DOM
    env.elements.retryBrailleBtn.click();
    await env.settle();

    assert.equal(env.pendingTimerCount(), 0, 'retry must cancel the old sequence timer');
});

// --- Manual controls wired to the controller --------------------------------

test('Play button starts autoplay and updates the simulated dot preview', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 0b101, [1, 3]), sampleCell(1, 0, [])]);

    env.elements.braillePlayBtn.click();

    assert.equal(env.elements.dot1.classList.contains('active'), true);
    assert.equal(env.elements.dot2.classList.contains('active'), false);
    assert.equal(env.elements.dot3.classList.contains('active'), true);
    assert.equal(env.elements.braillePreviewModeLabel.hidden, false);
});

test('Pause keeps the position and cancels the pending timer', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2]), sampleCell(2, 3, [1, 2])]);
    env.elements.braillePlayBtn.click();
    env.elements.braillePauseBtn.click();

    assert.equal(env.pendingTimerCount(), 0);
    assert.match(env.elements.braillePlaybackStatusText.textContent, /หยุดชั่วคราว/);
});

test('Next and Previous move exactly one cell and update the accessible info text', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [
        sampleCell(0, 1, [1]),
        sampleCell(1, 0b101010, [2, 4, 6]),
        sampleCell(2, 3, [1, 2]),
    ]);

    env.elements.brailleNextBtn.click();
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เซลล์ 2 จาก 3/);
    assert.match(env.elements.braillePlaybackAnnouncer.textContent, /เซลล์ 2 จาก 3/);
    assert.match(env.elements.braillePlaybackAnnouncer.textContent, /2 4 และ 6/);

    env.elements.braillePreviousBtn.click();
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เซลล์ 1 จาก 3/);
});

test('manual navigation pauses active autoplay in the real DOM wiring too', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2]), sampleCell(2, 3, [1, 2])]);
    env.elements.braillePlayBtn.click();
    assert.equal(env.pendingTimerCount(), 1);

    env.elements.brailleNextBtn.click();
    assert.equal(env.pendingTimerCount(), 0);
    assert.match(env.elements.braillePlaybackStatusText.textContent, /หยุดชั่วคราว/);
});

test('Restart returns to the first cell without auto-playing', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    env.elements.brailleNextBtn.click();
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เซลล์ 2/);

    env.elements.brailleRestartBtn.click();
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เซลล์ 1/);
    assert.equal(env.pendingTimerCount(), 0);
});

test('Stop cancels timers and clears the simulated dot preview', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 63, [1, 2, 3, 4, 5, 6]), sampleCell(1, 1, [1])]);
    env.elements.braillePlayBtn.click();
    assert.equal(env.elements.dot1.classList.contains('active'), true);

    env.elements.brailleStopBtn.click();

    assert.equal(env.pendingTimerCount(), 0);
    for (let d = 1; d <= 6; d += 1) {
        assert.equal(env.elements[`dot${d}`].classList.contains('active'), false);
    }
    assert.match(env.elements.braillePlaybackStatusText.textContent, /หยุดเล่นแล้ว/);
});

test('completion announces via the aria-live announcer', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1])]);
    env.elements.braillePlayBtn.click();
    env.fireAllTimers();

    assert.match(env.elements.braillePlaybackAnnouncer.textContent, /เล่นลำดับเบรลล์ครบแล้ว/);
    assert.match(env.elements.braillePlaybackStatusText.textContent, /เล่นครบแล้ว/);
});

test('a real blank cell during playback is identified as blank, not a transient gap', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 0, []), sampleCell(1, 1, [1])]);

    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เป็นช่องว่าง/);
    for (let d = 1; d <= 6; d += 1) {
        assert.equal(env.elements[`dot${d}`].classList.contains('active'), false);
    }
});

test('line change is announced when navigating across a line boundary', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(
        env,
        [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])],
        [1]
    );
    env.elements.brailleNextBtn.click();
    assert.match(env.elements.braillePlaybackAnnouncer.textContent, /ขึ้นบรรทัดที่ 2/);
});

// --- Accessible control states ----------------------------------------------

test('Play is disabled and aria-disabled once playback completes; Restart re-enables it', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1])]);
    env.elements.braillePlayBtn.click();
    env.fireAllTimers();

    assert.equal(env.elements.braillePlayBtn.disabled, true);
    assert.equal(env.elements.braillePlayBtn.getAttribute('aria-disabled'), 'true');

    env.elements.brailleRestartBtn.click();
    assert.equal(env.elements.braillePlayBtn.disabled, false);
    assert.equal(env.elements.braillePlayBtn.getAttribute('aria-disabled'), 'false');
});

test('Pause is disabled until playback is actually active', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    assert.equal(env.elements.braillePauseBtn.disabled, true);

    env.elements.braillePlayBtn.click();
    assert.equal(env.elements.braillePauseBtn.disabled, false);
});

// --- Timing configuration ----------------------------------------------------

test('timing inputs apply and clamp values through the controller', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);

    env.elements.brailleCellDurationInput.value = '999999';
    env.elements.brailleCellDurationInput.dispatch('change');
    assert.equal(env.elements.brailleCellDurationInput.value, 5000);

    env.elements.brailleGapInput.value = '-50';
    env.elements.brailleGapInput.dispatch('change');
    assert.equal(env.elements.brailleGapInput.value, 0);
});

test('changed timing takes effect on the next playback transition', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2]), sampleCell(2, 3, [1, 2])]);
    env.elements.brailleGapInput.value = '0';
    env.elements.brailleGapInput.dispatch('change');

    env.elements.braillePlayBtn.click();
    env.fireAllTimers(); // cell0 duration elapses; with gap=0 should jump straight to cell1
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เซลล์ 2 จาก 3/);
});

// --- Listen Again interaction with playback ---------------------------------

test('Listen Again pauses active Braille playback before speech starts', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2]), sampleCell(2, 3, [1, 2])]);
    env.elements.braillePlayBtn.click();
    assert.equal(env.pendingTimerCount(), 1);

    env.elements.listenAgainBtn.click();

    assert.equal(env.pendingTimerCount(), 0, 'Listen Again must pause active Braille playback first');
});

test('Listen Again does not alter the confirmed OCR text used by playback', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1])], [], 'ข้อความต้นฉบับ');
    env.elements.listenAgainBtn.click();
    assert.equal(env.elements.ocrRecognizedText.textContent, 'ข้อความต้นฉบับ');
});

// --- No-hardware boundary ----------------------------------------------------

test('no playback action ever calls fetch("/send") or "/api/send"', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [
        sampleCell(0, 1, [1]), sampleCell(1, 2, [2]), sampleCell(2, 0, []), sampleCell(3, 3, [1, 2]),
    ]);

    env.elements.braillePlayBtn.click();
    env.fireAllTimers();
    env.fireAllTimers();
    env.elements.braillePauseBtn.click();
    env.elements.brailleNextBtn.click();
    env.elements.braillePreviousBtn.click();
    env.elements.brailleRestartBtn.click();
    env.elements.braillePlayBtn.click();
    env.elements.brailleStopBtn.click();

    assert.ok(!env.fetchCalls.some(c => c.url === '/send'));
    assert.ok(!env.fetchCalls.some(c => c.url === '/api/send'));
});

test('no playback action calls any endpoint other than the original translation request', async () => {
    const env = createEnv();
    await confirmWithBrailleCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    const callsBeforePlayback = env.fetchCalls.length;

    env.elements.braillePlayBtn.click();
    env.fireAllTimers();
    env.elements.brailleNextBtn.click();
    env.elements.brailleStopBtn.click();

    assert.equal(env.fetchCalls.length, callsBeforePlayback, 'playback controls must never trigger network requests');
});
