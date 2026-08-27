'use strict';

/**
 * เทสต์หน่วยของ static/braille_hardware.js - ใช้ mock fetch ล้วน ไม่มี DOM ไม่มี
 * network จริง ไม่มีการรอเวลาจริง
 *
 * Run with: node --test "tests/js/*.test.js"
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const {
    BrailleHardwareBridge,
    BRAILLE_HARDWARE_UNCONFIRMED_MESSAGE,
} = require('../../static/braille_hardware.js');

// --- mock fetch: คิว response ต่อ endpoint ---------------------------------

function createFetchMock() {
    const calls = [];
    const queues = {};
    function fetchMock(url, opts) {
        calls.push({ url, body: JSON.parse(opts.body) });
        const q = queues[url] || [];
        const next = q.shift() || { ok: true, body: { ok: true } };
        if (next.throw) return Promise.reject(next.throw);
        return Promise.resolve({
            ok: next.ok !== false,
            json: () => Promise.resolve(next.body),
        });
    }
    fetchMock.calls = calls;
    fetchMock.queue = (url, resp) => {
        (queues[url] = queues[url] || []).push(resp);
    };
    return fetchMock;
}

function makeBridge(fetchMock, opts = {}) {
    const events = { send: [], watchdog: [], session: [], mode: [] };
    const bridge = new BrailleHardwareBridge({
        fetchFn: fetchMock,
        onSendStatus: e => events.send.push(e),
        onWatchdogStatus: e => events.watchdog.push(e),
        onSessionChange: e => events.session.push(e),
        onModeChange: e => events.mode.push(e),
        ...opts,
    });
    return { bridge, events };
}

const START = '/api/hardware/playback/start';
const CELL = '/api/hardware/playback/cell';
const STOP = '/api/hardware/playback/stop';

async function enabledConnectedBridge(fetchMock) {
    const { bridge, events } = makeBridge(fetchMock);
    await bridge.setHardwareModeEnabled(true);
    bridge.setPortConnected(true, '/dev/cu.usbserial-1');
    return { bridge, events };
}

// --- default state --------------------------------------------------------

test('hardware mode is disabled on construction', () => {
    const { bridge } = makeBridge(createFetchMock());
    assert.equal(bridge.isHardwareModeEnabled(), false);
    assert.equal(bridge.isSessionActive(), false);
});

test('no request is made before mode is enabled and session started', async () => {
    const fetchMock = createFetchMock();
    const { bridge } = makeBridge(fetchMock);
    await bridge.sendCell({ bit_pattern: '101010' }, 0);
    await bridge.sendTransientGap();
    assert.equal(fetchMock.calls.length, 0);
});

test('startSession fails without explicit mode enable', async () => {
    const fetchMock = createFetchMock();
    const { bridge } = makeBridge(fetchMock);
    const res = await bridge.startSession();
    assert.equal(res.ok, false);
    assert.equal(res.code, 'hardware_mode_disabled');
    assert.equal(fetchMock.calls.length, 0);
});

test('startSession fails when no port connected', async () => {
    const fetchMock = createFetchMock();
    const { bridge } = makeBridge(fetchMock);
    await bridge.setHardwareModeEnabled(true);
    const res = await bridge.startSession();
    assert.equal(res.code, 'serial_not_connected');
});

// --- session lifecycle ---------------------------------------------------

test('startSession posts opt-in and stores session id + generation', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    const { bridge } = await enabledConnectedBridge(fetchMock);

    const res = await bridge.startSession();
    assert.equal(res.ok, true);
    assert.equal(bridge.isSessionActive(), true);
    assert.equal(fetchMock.calls[0].url, START);
    assert.equal(fetchMock.calls[0].body.hardware_playback_opt_in, true);
});

test('sendCell posts exact bit pattern with real_cell_index and advances generation', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(CELL, { body: { ok: true, session_id: 'abc', generation: 1, real_cell_index: 0, transient_gap: false } });
    const { bridge, events } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();

    const res = await bridge.sendCell({ bit_pattern: '101010' }, 0);
    assert.equal(res.ok, true);
    const cellCall = fetchMock.calls.find(c => c.url === CELL);
    assert.equal(cellCall.body.bit_pattern, '101010');
    assert.equal(cellCall.body.real_cell_index, 0);
    assert.equal(cellCall.body.generation, 0);
    // generation ถัดไปต้องใช้ค่าใหม่จาก response
    assert.equal(events.send.at(-1).message, BRAILLE_HARDWARE_UNCONFIRMED_MESSAGE);
});

test('second sendCell uses the refreshed generation', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(CELL, { body: { ok: true, generation: 1, real_cell_index: 0, transient_gap: false } });
    fetchMock.queue(CELL, { body: { ok: true, generation: 2, real_cell_index: 1, transient_gap: false } });
    const { bridge } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();
    await bridge.sendCell({ bit_pattern: '100000' }, 0);
    await bridge.sendCell({ bit_pattern: '010000' }, 1);
    const cellCalls = fetchMock.calls.filter(c => c.url === CELL);
    assert.equal(cellCalls[1].body.generation, 1);
});

test('sendTransientGap posts transient_gap and clear pattern, no real index', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(CELL, { body: { ok: true, generation: 1, transient_gap: true, real_cell_index: null } });
    const { bridge } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();
    await bridge.sendTransientGap();
    const call = fetchMock.calls.find(c => c.url === CELL);
    assert.equal(call.body.transient_gap, true);
    assert.equal(call.body.bit_pattern, '000000');
});

test('sendCell rejects malformed bit patterns without any request', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    const { bridge } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();
    const callsBefore = fetchMock.calls.length;
    for (const bad of ['10101', '1010102', 'abcdef', '', undefined]) {
        const res = await bridge.sendCell({ bit_pattern: bad }, 0);
        assert.equal(res.ok, false);
        assert.equal(res.code, 'invalid_pattern');
    }
    assert.equal(fetchMock.calls.length, callsBefore);
});

test('sendCell never sends OCR text', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    const { bridge } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();
    const res = await bridge.sendCell({ bit_pattern: 'สวัสดี' }, 0);
    assert.equal(res.code, 'invalid_pattern');
});

// --- stop / disable safety --------------------------------------------------

test('stopSession invalidates client state before awaiting server, then posts stop', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(STOP, { body: { ok: true, stopped: true, cleared: true } });
    const { bridge } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();

    const p = bridge.stopSession('ทดสอบ');
    assert.equal(bridge.isSessionActive(), false, 'client state must be invalidated synchronously');
    await p;
    assert.ok(fetchMock.calls.some(c => c.url === STOP));
});

test('a cell response that arrives after stop is discarded (stale)', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(CELL, { body: { ok: true, generation: 1, real_cell_index: 0 } });
    fetchMock.queue(STOP, { body: { ok: true, stopped: true, cleared: true } });
    const { bridge } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();

    const cellPromise = bridge.sendCell({ bit_pattern: '101010' }, 0);
    await bridge.stopSession('หยุดระหว่างส่ง');
    const res = await cellPromise;
    assert.equal(res.stale, true);
});

test('disabling hardware mode stops an active session', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(STOP, { body: { ok: true, stopped: true, cleared: true } });
    const { bridge } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();
    await bridge.setHardwareModeEnabled(false);
    assert.equal(bridge.isSessionActive(), false);
    assert.ok(fetchMock.calls.some(c => c.url === STOP));
});

test('handlePlaybackEnded stops the session (complete/error/stop share one path)', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(STOP, { body: { ok: true, stopped: true, cleared: true } });
    const { bridge } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();
    await bridge.handlePlaybackEnded('เล่นครบ');
    assert.equal(bridge.isSessionActive(), false);
});

// --- server-driven session termination -----------------------------------

test('watchdog_expired from server ends the client session and reports it', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(CELL, { ok: false, body: { ok: false, error: { code: 'watchdog_expired', message: 'หมดเวลา' } } });
    const { bridge, events } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();
    await bridge.sendCell({ bit_pattern: '101010' }, 0);
    assert.equal(bridge.isSessionActive(), false);
    assert.equal(events.watchdog.length, 1);
});

test('stale_session from server ends the client session', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(CELL, { ok: false, body: { ok: false, error: { code: 'stale_session', message: 'x' } } });
    const { bridge } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();
    await bridge.sendCell({ bit_pattern: '101010' }, 0);
    assert.equal(bridge.isSessionActive(), false);
});

test('success status message never claims the device displayed the cell', async () => {
    const fetchMock = createFetchMock();
    fetchMock.queue(START, { body: { ok: true, session_id: 'abc', generation: 0 } });
    fetchMock.queue(CELL, { body: { ok: true, generation: 1, real_cell_index: 0, transient_gap: false } });
    const { bridge, events } = await enabledConnectedBridge(fetchMock);
    await bridge.startSession();
    await bridge.sendCell({ bit_pattern: '101010' }, 0);
    const msg = events.send.at(-1).message;
    assert.doesNotMatch(msg, /แสดงผลสำเร็จ/);
    assert.match(msg, /ยังไม่ได้รับการยืนยันจากอุปกรณ์/);
});
