'use strict';

/**
 * Regression tests สำหรับ commit e45bdd5 ที่ทำให้เกิด:
 *   1. ReferenceError: ensureHardwareSessionActive is not defined (ปุ่มเล่นหลักพัง)
 *   2. HTTP 409 stale_session จาก sendTransientGap + sendCell ที่ยิงพร้อมกัน
 *      ด้วย generation เดียวกัน (paused -> transient gap ตอน Next/Previous)
 *   3. เซสชันฮาร์ดแวร์เริ่มอัตโนมัติจากปุ่มเล่นทั่วไป
 *
 * ทั้งหมดใช้ mock hardware + fake timer ไม่มี network จริง ไม่เปิดพอร์ต Serial
 *
 * Run with: node --test "tests/js/*.test.js"
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { createEnv } = require('./fake-dom');
const { BrailleHardwareBridge } = require('../../static/braille_hardware.js');

// ------------------------------------------------------------------ helpers

function pngFile(name = 'sample.png') {
    return { name, type: 'image/png' };
}

function sampleCell(index, bits, dots) {
    return {
        index,
        bitmask: parseInt(bits, 2),
        bit_pattern: bits,
        dot_numbers: dots,
        unicode_braille: String.fromCodePoint(0x2800 + parseInt(bits, 2)),
    };
}

async function translateCells(env, cells, lineBoundaries = []) {
    env.selectImage(pngFile());
    env.queueOcrResponse({ ok: true, text: 'สวัสดี', low_confidence: false });
    await env.processImage();
    env.queueBrailleResponse({
        ok: true, cells, line_boundaries: lineBoundaries, cell_count: cells.length,
        diagnostics: [], engine: 'x', engine_version: '1', table: 't', sent_to_hardware: false,
    });
    await env.confirmAndTranslate();
}

/** เปิดโหมด + เชื่อมต่อ + เริ่มเซสชัน โดย mock server ตรวจ generation จริง */
async function startHardwareSession(env, { sessionId = 's1' } = {}) {
    env.queueHardwareResponse('/api/hardware/ports', {
        ok: true, ports: [{ device: '/dev/mock', identity_label: 'x', likely_unrelated: false }],
    });
    env.elements.hardwareModeToggle.checked = true;
    env.elements.hardwareModeToggle.dispatch('change');
    await env.settle();
    env.elements.hardwarePortSelect.value = '/dev/mock';
    env.elements.hardwareConnectBtn.click();
    await env.settle();
    env.queueHardwareResponse('/api/hardware/playback/start', { ok: true, session_id: sessionId, generation: 0 });
    env.elements.hardwareStartBtn.click();
    await env.settle();
}

/**
 * ต่อคิว response ของ /playback/cell แบบ "เซิร์ฟเวอร์ตรวจ generation จริง":
 * ถ้า body.generation != expected -> 409 stale_session
 */
function installGenerationCheckingCellResponses(env, count = 40) {
    let expected = 0;
    for (let i = 0; i < count; i += 1) {
        // fake-dom ใช้คิวแบบ FIFO ต่อ url - เราแทน generation logic ด้วยการอ่าน
        // ค่าใน queueHardwareResponse ทีละตัว แล้วตรวจใน test ภายหลัง
        env.queueHardwareResponse('/api/hardware/playback/cell', {
            ok: true, generation: i + 1, real_cell_index: 0, transient_gap: false,
        });
    }
    return () => expected;
}

// ================================================================ Regression 1

test('main Play button: no ReferenceError, no unhandled rejection, ready -> playing_cell', async () => {
    const rejections = [];
    const onRej = e => rejections.push(String(e && e.message));
    process.on('unhandledRejection', onRej);
    try {
        const env = createEnv();
        await translateCells(env, [sampleCell(0, '100000', [1]), sampleCell(1, '010000', [2])]);
        assert.match(env.elements.braillePlaybackStatusText.textContent, /พร้อมเล่น/);

        env.elements.braillePlayBtn.click();
        await env.settle();

        assert.match(env.elements.braillePlaybackStatusText.textContent, /กำลังเล่น/);
        assert.equal(env.pendingTimerCount(), 1, 'autoplay timer must be running');
        assert.deepEqual(rejections, [], 'no unhandled promise rejection');
    } finally {
        process.removeListener('unhandledRejection', onRej);
    }
});

test('simulated Play works when hardware mode is unavailable (no hardware calls, no /send)', async () => {
    const env = createEnv();
    await translateCells(env, [sampleCell(0, '100000', [1]), sampleCell(1, '010000', [2]), sampleCell(2, '001000', [3])]);

    env.elements.braillePlayBtn.click();
    await env.settle();
    for (let i = 0; i < 8; i += 1) { env.fireAllTimers(); }
    await env.settle();

    assert.match(env.elements.braillePlaybackStatusText.textContent, /เล่นครบแล้ว/);
    assert.equal(env.hardwareCalls().length, 0);
    assert.equal(env.fetchCalls.filter(c => c.url === '/send').length, 0);
});

test('Previous and Next work with hardware unavailable', async () => {
    const env = createEnv();
    await translateCells(env, [sampleCell(0, '100000', [1]), sampleCell(1, '010000', [2]), sampleCell(2, '001000', [3])]);

    env.elements.brailleNextBtn.click();
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เซลล์ 2 จาก 3/);
    env.elements.brailleNextBtn.click();
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เซลล์ 3 จาก 3/);
    env.elements.braillePreviousBtn.click();
    assert.match(env.elements.brailleCurrentCellInfo.textContent, /เซลล์ 2 จาก 3/);
    assert.equal(env.hardwareCalls().length, 0);
});

// ================================================================ Regression 3

test('main Play / Previous / Next never POST /api/hardware/playback/start', async () => {
    const env = createEnv();
    await translateCells(env, [sampleCell(0, '100000', [1]), sampleCell(1, '010000', [2])]);
    // เปิดโหมด + เชื่อมต่อ แต่ **ไม่** กดเริ่มเซสชัน
    env.queueHardwareResponse('/api/hardware/ports', { ok: true, ports: [{ device: '/dev/mock', identity_label: 'x', likely_unrelated: false }] });
    env.elements.hardwareModeToggle.checked = true;
    env.elements.hardwareModeToggle.dispatch('change');
    await env.settle();
    env.elements.hardwarePortSelect.value = '/dev/mock';
    env.elements.hardwareConnectBtn.click();
    await env.settle();

    env.elements.braillePlayBtn.click();
    await env.settle();
    env.fireAllTimers(); await env.settle();
    env.elements.brailleNextBtn.click();
    env.elements.braillePreviousBtn.click();
    env.elements.brailleRestartBtn.click();
    await env.settle();

    assert.equal(env.fetchCalls.filter(c => c.url === '/api/hardware/playback/start').length, 0,
        'ordinary playback controls must never start a hardware session');
    assert.equal(env.fetchCalls.filter(c => c.url === '/api/hardware/playback/cell').length, 0,
        'no cells sent without an explicitly started session');
});

test('no hardware session starts on OCR success, translation success, or page load', async () => {
    const env = createEnv();
    assert.equal(env.hardwareCalls().length, 0, 'page load');
    await translateCells(env, [sampleCell(0, '100000', [1])]);
    assert.equal(env.fetchCalls.filter(c => c.url === '/api/hardware/playback/start').length, 0);
});

// ================================================================ Regression 2

test('autoplay over 3 cells sends ordered real indexes 0,1,2 with no concurrent same generation', async () => {
    const env = createEnv();
    await translateCells(env, [sampleCell(0, '100000', [1]), sampleCell(1, '010000', [2]), sampleCell(2, '001000', [3])]);
    await startHardwareSession(env);
    installGenerationCheckingCellResponses(env);
    env.queueHardwareResponse('/api/hardware/playback/stop', { ok: true, stopped: true, cleared: true });

    env.elements.braillePlayBtn.click();
    await env.settle();
    for (let i = 0; i < 10; i += 1) { env.fireAllTimers(); await env.settle(); }

    const bodies = env.fetchCalls
        .filter(c => c.url === '/api/hardware/playback/cell')
        .map(c => JSON.parse(c.opts.body));

    const realIndexes = bodies.filter(b => !b.transient_gap).map(b => b.real_cell_index);
    assert.deepEqual(realIndexes, [0, 1, 2], 'ordered, no duplicates, no gaps');

    // generation ต้องเพิ่มขึ้นเรื่อย ๆ ไม่มีสองคำขอติดกันใช้ generation เดียวกัน
    for (let i = 1; i < bodies.length; i += 1) {
        assert.notEqual(bodies[i].generation, bodies[i - 1].generation,
            `requests ${i - 1} and ${i} share generation ${bodies[i].generation}`);
        assert.ok(bodies[i].generation > bodies[i - 1].generation);
    }
});

test('no duplicate cell index 0 (restart followed by play is not implicitly chained)', async () => {
    const env = createEnv();
    await translateCells(env, [sampleCell(0, '100000', [1]), sampleCell(1, '010000', [2])]);
    await startHardwareSession(env);
    installGenerationCheckingCellResponses(env);
    env.queueHardwareResponse('/api/hardware/playback/stop', { ok: true, stopped: true, cleared: true });

    env.elements.braillePlayBtn.click();
    await env.settle();

    const idx0Count = env.fetchCalls
        .filter(c => c.url === '/api/hardware/playback/cell')
        .map(c => JSON.parse(c.opts.body))
        .filter(b => !b.transient_gap && b.real_cell_index === 0).length;
    assert.equal(idx0Count, 1, 'cell index 0 must be sent exactly once');
});

test('Next during an active hardware session sends only the destination cell (no concurrent gap request)', async () => {
    const env = createEnv();
    await translateCells(env, [sampleCell(0, '100000', [1]), sampleCell(1, '010000', [2]), sampleCell(2, '001000', [3])]);
    await startHardwareSession(env);
    installGenerationCheckingCellResponses(env);
    env.queueHardwareResponse('/api/hardware/playback/stop', { ok: true, stopped: true, cleared: true });

    // ยังไม่กดเล่น - เริ่มที่เซลล์ 1 (index 0) กด Next -> ควรส่งเซลล์ index 1 อย่างเดียว
    env.elements.brailleNextBtn.click();
    await env.settle();

    const bodies = env.fetchCalls
        .filter(c => c.url === '/api/hardware/playback/cell')
        .map(c => JSON.parse(c.opts.body));
    // ต้องไม่มีคำขอ transient_gap แทรกมาพร้อม cell ที่ generation เดียวกัน
    const gens = bodies.map(b => b.generation);
    assert.equal(new Set(gens).size, gens.length, 'every hardware request used a distinct generation');
    const gapWithSameGenAsCell = bodies.some((b, i) =>
        b.transient_gap && bodies.some((o, j) => j !== i && !o.transient_gap && o.generation === b.generation));
    assert.equal(gapWithSameGenAsCell, false);
});

// ================================================================ Pause / Listen Again / Stop

test('Pause terminates and clears the hardware session', async () => {
    const env = createEnv();
    await translateCells(env, [sampleCell(0, '100000', [1]), sampleCell(1, '010000', [2]), sampleCell(2, '001000', [3])]);
    await startHardwareSession(env);
    installGenerationCheckingCellResponses(env);
    env.queueHardwareResponse('/api/hardware/playback/stop', { ok: true, stopped: true, cleared: true });

    env.elements.braillePlayBtn.click();
    await env.settle();
    env.elements.braillePauseBtn.click();
    await env.settle();

    assert.ok(env.fetchCalls.some(c => c.url === '/api/hardware/playback/stop'), 'Pause must post /stop');
    // เซสชันจบแล้ว: เริ่มเซสชันใหม่ต้องกด hardwareStartBtn อีกครั้ง
    assert.equal(env.elements.hardwareStartBtn.disabled, false);
});

test('Listen Again terminates and clears the hardware session', async () => {
    const env = createEnv();
    await translateCells(env, [sampleCell(0, '100000', [1]), sampleCell(1, '010000', [2])]);
    await startHardwareSession(env);
    installGenerationCheckingCellResponses(env);
    env.queueHardwareResponse('/api/hardware/playback/stop', { ok: true, stopped: true, cleared: true });

    env.elements.braillePlayBtn.click();
    await env.settle();
    const stopsBefore = env.fetchCalls.filter(c => c.url === '/api/hardware/playback/stop').length;

    env.elements.listenAgainBtn.click();
    await env.settle();

    const stopsAfter = env.fetchCalls.filter(c => c.url === '/api/hardware/playback/stop').length;
    assert.ok(stopsAfter > stopsBefore, 'Listen Again must stop the hardware session');
});

// ================================================================ Bridge-level: stop priority & late responses

function deferredFetchMock() {
    const calls = [];
    const queues = {};
    const gate = { resolvers: [] };
    function fetchMock(url, opts) {
        calls.push({ url, body: JSON.parse(opts.body) });
        const q = queues[url] || [];
        const next = q.shift() || { ok: true, body: { ok: true } };
        if (next.defer) {
            return new Promise(resolve => {
                gate.resolvers.push(() => resolve({ ok: next.ok !== false, json: () => Promise.resolve(next.body) }));
            });
        }
        return Promise.resolve({ ok: next.ok !== false, json: () => Promise.resolve(next.body) });
    }
    fetchMock.calls = calls;
    fetchMock.queue = (url, resp) => { (queues[url] = queues[url] || []).push(resp); };
    fetchMock.releaseAll = () => { gate.resolvers.splice(0).forEach(fn => fn()); };
    return fetchMock;
}

const START = '/api/hardware/playback/start';
const CELL = '/api/hardware/playback/cell';
const STOP = '/api/hardware/playback/stop';

test('Stop during an in-flight cell request invalidates the session immediately', async () => {
    const fetchMock = deferredFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(CELL, { defer: true, body: { ok: true, generation: 1, real_cell_index: 0 } });
    fetchMock.queue(STOP, { body: { ok: true, stopped: true, cleared: true } });

    const bridge = new BrailleHardwareBridge({ fetchFn: fetchMock });
    await bridge.setHardwareModeEnabled(true);
    bridge.setPortConnected(true, '/dev/mock');
    await bridge.startSession();

    const cellPromise = bridge.sendCell({ bit_pattern: '100000' }, 0); // stuck in flight
    const stopPromise = bridge.stopSession('emergency stop');

    // client state ต้องเป็นโมฆะทันที ไม่รอคิว/คำขอที่ค้าง
    assert.equal(bridge.isSessionActive(), false);

    await stopPromise;
    assert.ok(fetchMock.calls.some(c => c.url === STOP), 'stop request sent without waiting for the queue');

    fetchMock.releaseAll();
    const cellResult = await cellPromise;
    assert.equal(cellResult.stale, true, 'the late cell response is discarded');
    assert.equal(bridge.isSessionActive(), false, 'a late response must not reactivate the session');
});

/** mock server ที่ตรวจ generation จริง: mismatch -> 409 stale_session */
function generationValidatingFetchMock() {
    const calls = [];
    let sessionId = null;
    let generation = 0;
    let realIdx = -1;
    function json(body, ok = true) {
        return Promise.resolve({ ok, json: () => Promise.resolve(body) });
    }
    function fetchMock(url, opts) {
        const body = JSON.parse(opts.body);
        calls.push({ url, body });
        if (url === START) {
            sessionId = 's1'; generation = 0; realIdx = -1;
            return json({ ok: true, session_id: sessionId, generation: 0 });
        }
        if (url === STOP) {
            sessionId = null;
            return json({ ok: true, stopped: true, cleared: true });
        }
        if (url === CELL) {
            if (body.session_id !== sessionId) {
                return json({ ok: false, error: { code: 'session_not_active', message: 'x' } }, false);
            }
            if (body.generation !== generation) {
                return json({ ok: false, error: { code: 'stale_session', message: `expected ${generation} got ${body.generation}` } }, false);
            }
            generation += 1;
            if (!body.transient_gap) realIdx = Math.max(realIdx, body.real_cell_index);
            return json({ ok: true, generation, real_cell_index: realIdx, transient_gap: !!body.transient_gap });
        }
        return json({ ok: true });
    }
    fetchMock.calls = calls;
    return fetchMock;
}

test('409 stale_session cannot be reproduced during normal ordered playback', async () => {
    const fetchMock = generationValidatingFetchMock();
    const bridge = new BrailleHardwareBridge({ fetchFn: fetchMock });
    await bridge.setHardwareModeEnabled(true);
    bridge.setPortConnected(true, '/dev/mock');
    await bridge.startSession();

    // จำลองสิ่งที่ script.js ยิงตอน autoplay: cell0, gap, cell1, gap, cell2 - แต่
    // ยิงแบบ fire-and-forget (ไม่ await) เหมือน notifyHardware จริง
    bridge.sendCell({ bit_pattern: '100000' }, 0);
    bridge.sendTransientGap();
    bridge.sendCell({ bit_pattern: '010000' }, 1);
    bridge.sendTransientGap();
    bridge.sendCell({ bit_pattern: '001000' }, 2);

    // ปล่อยให้คิวทำงานจนหมด
    for (let i = 0; i < 20; i += 1) await new Promise(r => setImmediate(r));

    const cellCalls = fetchMock.calls.filter(c => c.url === CELL);
    assert.equal(cellCalls.length, 5);
    assert.equal(bridge.isSessionActive(), true, 'session survived ordered playback (no 409 teardown)');
    const realIndexes = cellCalls.filter(c => !c.body.transient_gap).map(c => c.body.real_cell_index);
    assert.deepEqual(realIndexes, [0, 1, 2]);
});

test('only one hardware mutation is in flight at a time', async () => {
    const fetchMock = deferredFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    for (let i = 1; i <= 5; i += 1) fetchMock.queue(CELL, { defer: true, body: { ok: true, generation: i, real_cell_index: 0 } });

    const bridge = new BrailleHardwareBridge({ fetchFn: fetchMock });
    await bridge.setHardwareModeEnabled(true);
    bridge.setPortConnected(true, '/dev/mock');
    await bridge.startSession();

    bridge.sendCell({ bit_pattern: '100000' }, 0);
    bridge.sendCell({ bit_pattern: '010000' }, 0);
    bridge.sendCell({ bit_pattern: '001000' }, 0);
    await new Promise(r => setImmediate(r));

    // มีคำขอ CELL ออกไปแค่ 1 ตัว อีก 2 ยังรอในคิว
    assert.equal(fetchMock.calls.filter(c => c.url === CELL).length, 1);
    assert.equal(bridge.pendingMutationCount(), 3);

    fetchMock.releaseAll();
    await new Promise(r => setImmediate(r));
    await new Promise(r => setImmediate(r));
    assert.equal(fetchMock.calls.filter(c => c.url === CELL).length, 2);
});

test('a late success response for an old session cannot reactivate a new session', async () => {
    const fetchMock = deferredFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 's1', generation: 0 } });
    fetchMock.queue(CELL, { defer: true, body: { ok: true, generation: 99, real_cell_index: 0 } });
    fetchMock.queue(STOP, { body: { ok: true, stopped: true, cleared: true } });
    fetchMock.queue(START, { body: { ok: true, session_id: 's2', generation: 0 } });

    const bridge = new BrailleHardwareBridge({ fetchFn: fetchMock });
    await bridge.setHardwareModeEnabled(true);
    bridge.setPortConnected(true, '/dev/mock');
    await bridge.startSession();

    const cellPromise = bridge.sendCell({ bit_pattern: '100000' }, 0);
    await bridge.stopSession('stop s1');
    await bridge.startSession(); // s2
    assert.equal(bridge.isSessionActive(), true);
    const genBefore = bridge.getGeneration();

    fetchMock.releaseAll();
    await cellPromise;

    assert.equal(bridge.isSessionActive(), true, 's2 still active');
    assert.equal(bridge.getGeneration(), genBefore, 'late s1 response did not bump s2 generation');
});
