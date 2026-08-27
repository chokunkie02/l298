'use strict';

/**
 * เทสต์การเดินสาย static/braille_hardware.js เข้ากับ static/script.js (Step 6)
 * ผ่าน fake DOM + fake timer เดียวกับเทสต์อื่น ไม่มี network จริง ไม่รอเวลาจริง
 *
 * Run with: node --test "tests/js/*.test.js"
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const { createEnv } = require('./fake-dom');

function pngFile(name = 'sample.png') {
    return { name, type: 'image/png' };
}

function sampleCell(index, bitmask, dots) {
    const bitPattern = [1, 2, 3, 4, 5, 6].map(d => (bitmask & (1 << (d - 1)) ? '1' : '0')).join('');
    return { index, unicode_braille: String.fromCodePoint(0x2800 + bitmask), dot_numbers: dots, bitmask, bit_pattern: bitPattern };
}

async function confirmWithCells(env, cells, lineBoundaries = []) {
    env.selectImage(pngFile());
    env.queueOcrResponse({ ok: true, text: 'สวัสดี', low_confidence: false });
    await env.processImage();
    env.queueBrailleResponse({
        ok: true, cells, line_boundaries: lineBoundaries, cell_count: cells.length, diagnostics: [],
        engine: 'liblouis-cli', engine_version: '3', table: 'th-g1.utb', sent_to_hardware: false,
    });
    await env.confirmAndTranslate();
}

function queuePorts(env) {
    env.queueHardwareResponse('/api/hardware/ports', {
        ok: true,
        ports: [{ device: '/dev/mock', identity_label: 'อุปกรณ์ Serial ที่ยังไม่ได้ยืนยันชนิด', likely_unrelated: false }],
    });
}

async function enableHardwareSession(env) {
    queuePorts(env);
    env.elements.hardwareModeToggle.checked = true;
    env.elements.hardwareModeToggle.dispatch('change');
    await env.settle();
    env.elements.hardwarePortSelect.value = '/dev/mock';
    env.elements.hardwareConnectBtn.click();
    await env.settle();
    env.queueHardwareResponse('/api/hardware/playback/start', { ok: true, session_id: 's1', generation: 0 });
    env.elements.hardwareStartBtn.click();
    await env.settle();
    // ตอบ generic ให้ทุกคำขอเซลล์ถัดไป
    for (let i = 1; i <= 40; i += 1) {
        env.queueHardwareResponse('/api/hardware/playback/cell', { ok: true, generation: i, real_cell_index: 0, transient_gap: false });
    }
    env.queueHardwareResponse('/api/hardware/playback/stop', { ok: true, stopped: true, cleared: true });
}

// --- ไม่มีการทำงานอัตโนมัติกับฮาร์ดแวร์ ------------------------------------

test('page load makes no /api/hardware request and no automatic session', async () => {
    const env = createEnv();
    assert.equal(env.hardwareCalls().length, 0);
});

test('hardware controls are disabled by default on load', async () => {
    const env = createEnv();
    assert.equal(env.elements.hardwareModeToggle.checked, false);
    assert.equal(env.elements.hardwareStartBtn.disabled, true);
    assert.equal(env.elements.hardwareStopBtn.disabled, true);
    assert.equal(env.elements.hardwarePortSelect.disabled, true);
});

test('translation success does not trigger /send or any hardware call', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    assert.equal(env.hardwareCalls().length, 0);
    assert.ok(!env.fetchCalls.some(c => c.url === '/send'));
});

test('playing simulated playback with hardware mode OFF sends nothing to hardware', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    env.elements.braillePlayBtn.click();
    env.fireAllTimers();
    env.fireAllTimers();
    assert.equal(env.hardwareCalls().length, 0);
});

// --- เปิดโหมด + เชื่อมต่อ + เริ่มเซสชัน ------------------------------------

test('enabling hardware mode requires explicit checkbox and enables Start after connect', async () => {
    const env = createEnv();
    queuePorts(env);
    env.elements.hardwareModeToggle.checked = true;
    env.elements.hardwareModeToggle.dispatch('change');
    await env.settle();
    assert.equal(env.elements.hardwareStartBtn.disabled, true, 'still disabled until a port is connected');

    env.elements.hardwarePortSelect.value = '/dev/mock';
    env.elements.hardwareConnectBtn.click();
    await env.settle();
    assert.equal(env.elements.hardwareStartBtn.disabled, false);
});

test('starting a session posts opt-in and then playback cells go to the hardware cell endpoint', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 0b101, [1, 3]), sampleCell(1, 0b010, [2])]);
    await enableHardwareSession(env);

    const startCall = env.fetchCalls.find(c => c.url === '/api/hardware/playback/start');
    assert.equal(JSON.parse(startCall.opts.body).hardware_playback_opt_in, true);

    env.elements.braillePlayBtn.click();
    await env.settle();

    const cellCalls = env.fetchCalls.filter(c => c.url === '/api/hardware/playback/cell');
    assert.ok(cellCalls.length >= 1);
    const firstBody = JSON.parse(cellCalls[0].opts.body);
    assert.equal(firstBody.bit_pattern, '101000');
    assert.equal(firstBody.real_cell_index, 0);
    assert.equal(firstBody.session_id, 's1');
});

test('transient gap during autoplay posts transient_gap without a real index', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    await enableHardwareSession(env);

    env.elements.braillePlayBtn.click();
    await env.settle();
    env.fireAllTimers(); // cell 0 duration elapses -> gap
    await env.settle();

    const gapCall = env.fetchCalls
        .filter(c => c.url === '/api/hardware/playback/cell')
        .map(c => JSON.parse(c.opts.body))
        .find(b => b.transient_gap === true);
    assert.ok(gapCall, 'a transient_gap cell request must have been sent');
    assert.equal(gapCall.bit_pattern, '000000');
});

test('the Stop-and-clear button ends the hardware session', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    await enableHardwareSession(env);
    env.elements.braillePlayBtn.click();
    await env.settle();

    env.elements.hardwareStopBtn.click();
    await env.settle();

    assert.ok(env.fetchCalls.some(c => c.url === '/api/hardware/playback/stop'));
    assert.equal(env.elements.hardwareStopBtn.disabled, true, 'stop disables itself once session ends');
});

test('hardware bit patterns never carry OCR text and cell indexes are unchanged', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 0, []), sampleCell(2, 3, [1, 2])]);
    await enableHardwareSession(env);
    env.elements.braillePlayBtn.click();
    await env.settle();
    env.fireAllTimers(); await env.settle();
    env.fireAllTimers(); await env.settle();

    const bodies = env.fetchCalls
        .filter(c => c.url === '/api/hardware/playback/cell')
        .map(c => JSON.parse(c.opts.body));
    for (const b of bodies) {
        assert.match(b.bit_pattern, /^[01]{6}$/);
    }
    const realIndexes = bodies.filter(b => !b.transient_gap).map(b => b.real_cell_index);
    // ดัชนีต้องไม่ถอยหลังและไม่กระโดดข้าม
    for (let i = 1; i < realIndexes.length; i += 1) {
        assert.ok(realIndexes[i] >= realIndexes[i - 1]);
    }
});

// --- การจบเซสชันอัตโนมัติ ----------------------------------------------

test('a new OCR image terminates an active hardware session', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    await enableHardwareSession(env);
    env.elements.braillePlayBtn.click();
    await env.settle();
    const stopsBefore = env.fetchCalls.filter(c => c.url === '/api/hardware/playback/stop').length;

    env.selectImage(pngFile('other.png'));
    await env.settle();

    const stopsAfter = env.fetchCalls.filter(c => c.url === '/api/hardware/playback/stop').length;
    assert.ok(stopsAfter > stopsBefore, 'new OCR must stop the hardware session');
});

test('visibilitychange to hidden pauses playback and stops the hardware session', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    await enableHardwareSession(env);
    env.elements.braillePlayBtn.click();
    await env.settle();

    env.document.hidden = true;
    env.document.visibilityState = 'hidden';
    env.dispatchDocument('visibilitychange');
    await env.settle();

    assert.equal(env.pendingTimerCount(), 0, 'playback must be paused');
    assert.ok(env.fetchCalls.some(c => c.url === '/api/hardware/playback/stop'));
});

test('disabling hardware mode mid-playback stops the session', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2])]);
    await enableHardwareSession(env);
    env.elements.braillePlayBtn.click();
    await env.settle();

    env.elements.hardwareModeToggle.checked = false;
    env.elements.hardwareModeToggle.dispatch('change');
    await env.settle();

    assert.ok(env.fetchCalls.some(c => c.url === '/api/hardware/playback/stop'));
});

test('repeated Play clicks do not open duplicate hardware sessions', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1]), sampleCell(1, 2, [2]), sampleCell(2, 3, [1, 2])]);
    await enableHardwareSession(env);

    env.elements.braillePlayBtn.click();
    env.elements.braillePlayBtn.click();
    env.elements.braillePlayBtn.click();
    await env.settle();

    const startCalls = env.fetchCalls.filter(c => c.url === '/api/hardware/playback/start');
    assert.equal(startCalls.length, 1);
});

// --- manual dot verification -------------------------------------------

test('manual verify buttons post single-dot patterns, never all-on', async () => {
    const env = createEnv();
    await confirmWithCells(env, [sampleCell(0, 1, [1])]);
    await enableHardwareSession(env);
    for (let i = 0; i < 10; i += 1) {
        env.queueHardwareResponse('/api/hardware/verify/cell', { ok: true, generation: 100 + i });
    }

    env.elements.hardwareVerifyPatternSelect.value = '001000';
    env.elements.hardwareVerifyActivateBtn.click();
    await env.settle();
    env.elements.hardwareVerifyClearBtn.click();
    await env.settle();

    const verifyBodies = env.fetchCalls
        .filter(c => c.url === '/api/hardware/verify/cell')
        .map(c => JSON.parse(c.opts.body));
    assert.deepEqual(verifyBodies.map(b => b.bit_pattern), ['001000', '000000']);
    assert.ok(!verifyBodies.some(b => b.bit_pattern === '111111'));
});
