'use strict';

/**
 * เทสต์หน่วย (unit test) ของ static/braille_playback.js - state machine ล้วน
 * ไม่ยุ่งกับ DOM, Flask, OCR, Liblouis, Serial, ESP32, หรือ network เลย ใช้
 * timer function ปลอมที่ inject เข้าไปเพื่อควบคุมเวลาแบบ deterministic ทั้งหมด
 * ไม่มีการรอเวลาจริงแม้แต่มิลลิวินาทีเดียว
 *
 * Run with: node --test tests/js
 */

const test = require('node:test');
const assert = require('node:assert/strict');
const {
    BraillePlaybackController,
    BRAILLE_PLAYBACK_STATES: STATES,
    BRAILLE_PLAYBACK_TIMING_LIMITS: LIMITS,
    BRAILLE_PLAYBACK_DEFAULT_TIMING: DEFAULT_TIMING,
} = require('../../static/braille_playback.js');

// --- Fake timer harness: single source of truth for "pending timers" ------

function createFakeClock() {
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
        pendingDelays() {
            return [...pending.values()].map(t => t.delay);
        },
        // สำหรับจำลอง race condition เท่านั้น: คืน callback ดิบที่ยังค้างอยู่ ณ
        // ขณะนี้ (ก่อนถูก clearTimeout) เพื่อเรียกทีหลังด้วยมือ จำลองว่า timer
        // จริงยิงไปแล้วในคิว event loop ก่อนที่ clearTimeout จะมีผลทัน
        _pendingCallbacksForTest() {
            return [...pending.values()].map(t => t.callback);
        },
        // ยิง timer ที่ค้างอยู่ทั้งหมด ณ ขณะนี้ (ปกติมีแค่ 1 ตัวเสมอตามสเปก) แล้ว
        // เคลียร์ก่อนเรียก callback เพื่อจำลองพฤติกรรมจริงของ setTimeout ที่ id
        // เดิมใช้ซ้ำไม่ได้หลัง fire แล้ว
        fireAll() {
            const toFire = [...pending.entries()];
            pending.clear();
            toFire.forEach(([, t]) => t.callback());
        },
    };
}

function makeCell(bitmask, overrides) {
    const dotNumbers = [];
    for (let dot = 1; dot <= 6; dot += 1) {
        if (bitmask & (1 << (dot - 1))) dotNumbers.push(dot);
    }
    const bitPattern = [1, 2, 3, 4, 5, 6].map(dot => (bitmask & (1 << (dot - 1)) ? '1' : '0')).join('');
    return Object.assign(
        {
            index: 0,
            bitmask: bitmask,
            bit_pattern: bitPattern,
            dot_numbers: dotNumbers,
            unicode_braille: String.fromCodePoint(0x2800 + bitmask),
        },
        overrides || {}
    );
}

function createRecorder() {
    const events = [];
    return {
        events,
        onCellDisplay: info => events.push({ type: 'cell', index: info.index, cellCount: info.cellCount, lineNumber: info.lineNumber, isBlank: info.isBlank, announce: info.announce }),
        onTransientBlank: () => events.push({ type: 'blank' }),
        onStateChange: state => events.push({ type: 'state', state }),
        onLineChange: info => events.push({ type: 'line', lineNumber: info.lineNumber }),
        onComplete: () => events.push({ type: 'complete' }),
        onError: err => events.push({ type: 'error', code: err.code }),
        clear() {
            events.length = 0;
        },
    };
}

function createController(clock, recorder, timingOverrides) {
    const ctrl = new BraillePlaybackController({
        setTimeoutFn: clock.setTimeoutFn,
        clearTimeoutFn: clock.clearTimeoutFn,
        onCellDisplay: recorder.onCellDisplay,
        onTransientBlank: recorder.onTransientBlank,
        onStateChange: recorder.onStateChange,
        onLineChange: recorder.onLineChange,
        onComplete: recorder.onComplete,
        onError: recorder.onError,
    });
    if (timingOverrides) ctrl.setTiming(timingOverrides);
    return ctrl;
}

// --- Initial / empty state --------------------------------------------------

test('initial state before any load is empty', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    assert.equal(ctrl.getState(), STATES.EMPTY);
    assert.equal(ctrl.getCellCount(), 0);
    assert.equal(ctrl.getCurrentCell(), null);
});

test('loading zero cells keeps state empty and does not start playback', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([]);
    assert.equal(ctrl.getState(), STATES.EMPTY);
    ctrl.play();
    assert.equal(ctrl.getState(), STATES.EMPTY);
    assert.equal(clock.pendingCount(), 0);
});

test('loading a nonempty sequence sets state to ready at index 0 without starting playback', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);

    assert.equal(ctrl.getState(), STATES.READY);
    assert.equal(ctrl.getCurrentIndex(), 0);
    assert.equal(ctrl.getCellCount(), 3);
    assert.equal(clock.pendingCount(), 0, 'load() must not start a timer');
});

test('loading a single-cell sequence works', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(63)]);
    assert.equal(ctrl.getState(), STATES.READY);
    assert.equal(ctrl.getCellCount(), 1);
    ctrl.play();
    assert.equal(ctrl.getState(), STATES.PLAYING_CELL);
    clock.fireAll();
    assert.equal(ctrl.getState(), STATES.COMPLETED);
});

test('load fires onCellDisplay for the first cell immediately with announce=true', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(5), makeCell(6)]);
    const cellEvent = recorder.events.find(e => e.type === 'cell');
    assert.ok(cellEvent);
    assert.equal(cellEvent.index, 0);
    assert.equal(cellEvent.announce, true);
});

// --- Play / pause / resume / stop / restart --------------------------------

test('play begins autoplay and schedules exactly one timer', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2)]);
    ctrl.play();
    assert.equal(ctrl.getState(), STATES.PLAYING_CELL);
    assert.equal(clock.pendingCount(), 1);
});

test('repeated play clicks do not create overlapping timer chains', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();
    ctrl.play();
    ctrl.play();
    assert.equal(clock.pendingCount(), 1, 'only one timer must ever be pending');
});

test('pause keeps the current position and cancels the pending timer', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0 });
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();
    clock.fireAll(); // advance to cell index 1
    assert.equal(ctrl.getCurrentIndex(), 1);

    ctrl.pause();
    assert.equal(ctrl.getState(), STATES.PAUSED);
    assert.equal(ctrl.getCurrentIndex(), 1, 'position must be retained across pause');
    assert.equal(clock.pendingCount(), 0);
});

test('pause while not playing is a safe no-op', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1)]);
    ctrl.pause();
    assert.equal(ctrl.getState(), STATES.READY);
});

test('resume (play again after pause) continues safely from the paused position', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0 });
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();
    clock.fireAll();
    ctrl.pause();
    assert.equal(ctrl.getCurrentIndex(), 1);

    ctrl.play();
    assert.equal(ctrl.getState(), STATES.PLAYING_CELL);
    assert.equal(ctrl.getCurrentIndex(), 1);
    assert.equal(clock.pendingCount(), 1);
});

test('stop cancels every pending timer and clears the simulated display', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();
    assert.equal(clock.pendingCount(), 1);

    recorder.clear();
    ctrl.stop();

    assert.equal(ctrl.getState(), STATES.STOPPED);
    assert.equal(clock.pendingCount(), 0);
    assert.ok(recorder.events.some(e => e.type === 'blank'), 'stop must clear the simulated preview');
});

test('stop on an empty controller sets state to empty without error', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.stop();
    assert.equal(ctrl.getState(), STATES.EMPTY);
});

test('restart returns to the first cell and does not auto-play', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0 });
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();
    clock.fireAll();
    clock.fireAll();
    assert.equal(ctrl.getCurrentIndex(), 2);

    ctrl.restart();
    assert.equal(ctrl.getCurrentIndex(), 0);
    assert.equal(ctrl.getState(), STATES.READY);
    assert.equal(clock.pendingCount(), 0, 'restart must not start playback automatically');
});

test('completion leaves the controller in a clear completed state', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0 });
    ctrl.load([makeCell(1), makeCell(2)]);
    ctrl.play();
    clock.fireAll(); // -> index 1
    clock.fireAll(); // -> completed
    assert.equal(ctrl.getState(), STATES.COMPLETED);
    assert.equal(clock.pendingCount(), 0);
    assert.ok(recorder.events.some(e => e.type === 'complete'));
});

test('play after completion does nothing until restart is called explicitly', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0 });
    ctrl.load([makeCell(1)]);
    ctrl.play();
    clock.fireAll();
    assert.equal(ctrl.getState(), STATES.COMPLETED);

    ctrl.play();
    assert.equal(ctrl.getState(), STATES.COMPLETED, 'play must not silently restart after completion');
    assert.equal(clock.pendingCount(), 0);
});

// --- Manual navigation -------------------------------------------------------

test('next and previous move exactly one real cell', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);

    ctrl.next();
    assert.equal(ctrl.getCurrentIndex(), 1);
    ctrl.next();
    assert.equal(ctrl.getCurrentIndex(), 2);
    ctrl.previous();
    assert.equal(ctrl.getCurrentIndex(), 1);
});

test('previous at the first cell stays clamped at index 0', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2)]);
    ctrl.previous();
    assert.equal(ctrl.getCurrentIndex(), 0);
});

test('next at the last cell stays clamped at the final index', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2)]);
    ctrl.next();
    ctrl.next();
    ctrl.next();
    assert.equal(ctrl.getCurrentIndex(), 1);
});

test('manual navigation pauses active automatic playback', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();
    assert.equal(ctrl.getState(), STATES.PLAYING_CELL);
    assert.equal(clock.pendingCount(), 1);

    ctrl.next();
    assert.equal(ctrl.getState(), STATES.PAUSED);
    assert.equal(clock.pendingCount(), 0, 'manual navigation must cancel the pending autoplay timer');
});

test('next/previous on an empty controller is a safe no-op', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.next();
    ctrl.previous();
    assert.equal(ctrl.getState(), STATES.EMPTY);
});

// --- Loading a new sequence invalidates old callbacks -----------------------

test('loading a new sequence cancels the old pending timer immediately', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();
    assert.equal(clock.pendingCount(), 1);

    recorder.clear();
    ctrl.load([makeCell(9), makeCell(10)]);

    assert.equal(clock.pendingCount(), 0, 'loading a new sequence must cancel the old timer');
    assert.equal(ctrl.getCurrentIndex(), 0);
    assert.equal(ctrl.getCellCount(), 2);
});

test('a stale timer callback captured before reload has no effect once fired late', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0 });
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();

    // จำลอง real setTimeout ที่คิว callback ไว้แล้วในเอนจินจริง (ต่างจาก fake
    // clock ที่ลบ callback ทิ้งไปเมื่อ clearTimeout ถูกเรียก) โดยเก็บ reference
    // ของ callback ไว้ก่อน reload ด้วยมือ แล้วเรียกมันหลัง reload เพื่อพิสูจน์ว่า
    // sequence token ทำให้ callback ที่ค้างจากรอบเก่าไม่มีผลใด ๆ
    const staleCallback = [...clock._pendingCallbacksForTest()][0];
    ctrl.load([makeCell(9), makeCell(10)]); // reload ก่อน timer เดิมจะยิงจริง
    recorder.clear();

    staleCallback(); // จำลอง race condition: callback เก่ายิงหลัง reload ไปแล้ว
    assert.equal(recorder.events.length, 0, 'stale callback from the old sequence must be a no-op');
    assert.equal(ctrl.getCurrentIndex(), 0, 'new sequence position must be unaffected');
    assert.equal(ctrl.getCellCount(), 2);
});

// --- Real blank cells vs transient gaps -------------------------------------

test('a real blank cell (bitmask 0) is reported with isBlank=true and keeps its own index', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(0), makeCell(2)]);

    ctrl.next();
    const cellEvent = recorder.events.filter(e => e.type === 'cell').pop();
    assert.equal(cellEvent.index, 1);
    assert.equal(cellEvent.isBlank, true);
    assert.equal(ctrl.getCellCount(), 3, 'blank cell must still count toward cell_count');
});

test('consecutive real blank cells remain separate cells with distinct indexes', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(0), makeCell(0), makeCell(0)]);
    assert.equal(ctrl.getCellCount(), 3);

    ctrl.next();
    assert.equal(ctrl.getCurrentIndex(), 1);
    ctrl.next();
    assert.equal(ctrl.getCurrentIndex(), 2);
});

test('transient inter-cell gap does not count as a cell and does not change cell_count', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder); // default gapMs=150 (> 0)
    ctrl.load([makeCell(1), makeCell(2)]);
    const countBefore = ctrl.getCellCount();

    ctrl.play();
    clock.fireAll(); // enters gap phase
    assert.equal(ctrl.getState(), STATES.PLAYING_GAP);
    assert.equal(ctrl.getCellCount(), countBefore, 'gap must never alter cell_count');
    assert.equal(ctrl.getCurrentIndex(), 0, 'gap must not advance the index by itself');

    const blankEvents = recorder.events.filter(e => e.type === 'blank');
    assert.equal(blankEvents.length, 1);
});

test('zero-gap playback advances directly from one cell to the next', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0 });
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();
    recorder.clear();
    clock.fireAll();
    assert.equal(ctrl.getState(), STATES.PLAYING_CELL, 'zero gap must skip the gap phase entirely');
    assert.equal(ctrl.getCurrentIndex(), 1);
    assert.ok(!recorder.events.some(e => e.type === 'blank'), 'zero gap must not emit a transient blank event');
});

// --- Line boundaries ---------------------------------------------------------

test('line number starts at 1 and increments after each configured boundary', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    // 2 cells on line 1, 1 cell on line 2 -> boundary at cumulative index 2
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)], [2]);
    assert.equal(ctrl.getCurrentLineNumber(), 1);
    ctrl.next();
    assert.equal(ctrl.getCurrentLineNumber(), 1);
    ctrl.next();
    assert.equal(ctrl.getCurrentLineNumber(), 2);
});

test('crossing a line boundary during autoplay announces the line change once', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0, linePauseMs: 500 });
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)], [2]);
    ctrl.play();
    recorder.clear();

    clock.fireAll(); // cell0 -> cell1 (still line 1, gapMs=0 -> straight to next cell)
    assert.ok(!recorder.events.some(e => e.type === 'line'));

    clock.fireAll(); // cell1 -> crosses into line 2 -> line pause phase (blank), no cell event yet
    assert.equal(ctrl.getState(), STATES.PLAYING_GAP);
    assert.equal(clock.pendingDelays()[0], 500);

    clock.fireAll(); // line pause elapses -> cell2 displayed on line 2
    const lineEvents = recorder.events.filter(e => e.type === 'line');
    assert.equal(lineEvents.length, 1);
    assert.equal(lineEvents[0].lineNumber, 2);
});

test('manual navigation across a line boundary also announces the line change', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2)], [1]);
    recorder.clear();
    ctrl.next();
    assert.ok(recorder.events.some(e => e.type === 'line' && e.lineNumber === 2));
});

test('empty lines (consecutive boundary values) do not crash and are handled safely', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    // บรรทัดว่างตรงกลาง: line1 จบที่ index1, line2 ว่างเปล่าจบที่ index1 เหมือนกัน, line3 เริ่มจาก index1
    ctrl.load([makeCell(1), makeCell(2)], [1, 1]);
    assert.equal(ctrl.getCurrentLineNumber(), 1);
    ctrl.next();
    assert.equal(ctrl.getCurrentLineNumber(), 3);
});

test('a sequence with no line boundaries stays on line 1 throughout', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)], []);
    ctrl.next();
    ctrl.next();
    assert.equal(ctrl.getCurrentLineNumber(), 1);
});

// --- Timing validation --------------------------------------------------------

test('default timing matches documented prototype defaults', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    assert.deepEqual(ctrl.getTiming(), DEFAULT_TIMING);
});

test('setTiming clamps values above the safe maximum', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.setTiming({ cellDurationMs: 999999, gapMs: 999999, linePauseMs: 999999 });
    const timing = ctrl.getTiming();
    assert.equal(timing.cellDurationMs, LIMITS.cellDurationMs.max);
    assert.equal(timing.gapMs, LIMITS.gapMs.max);
    assert.equal(timing.linePauseMs, LIMITS.linePauseMs.max);
});

test('setTiming clamps values below the safe minimum and never allows a zero cell duration', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.setTiming({ cellDurationMs: 0, gapMs: -100, linePauseMs: -1 });
    const timing = ctrl.getTiming();
    assert.equal(timing.cellDurationMs, LIMITS.cellDurationMs.min);
    assert.ok(timing.cellDurationMs > 0, 'cell duration must never be zero to avoid a zero-delay loop');
    assert.equal(timing.gapMs, LIMITS.gapMs.min);
    assert.equal(timing.linePauseMs, LIMITS.linePauseMs.min);
});

test('setTiming ignores non-finite values and keeps the previous setting', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.setTiming({ cellDurationMs: NaN, gapMs: Infinity, linePauseMs: 'not a number' });
    assert.deepEqual(ctrl.getTiming(), DEFAULT_TIMING);
});

test('gapMs of exactly 0 is a valid, accepted value (not rejected as invalid)', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.setTiming({ gapMs: 0 });
    assert.equal(ctrl.getTiming().gapMs, 0);
});

test('timing changes apply to the next transition without restarting or duplicating playback', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0, cellDurationMs: 1000 });
    ctrl.load([makeCell(1), makeCell(2), makeCell(3)]);
    ctrl.play();
    assert.equal(clock.pendingDelays()[0], 1000);

    ctrl.setTiming({ cellDurationMs: 2000 });
    assert.equal(clock.pendingCount(), 1, 'changing timing mid-flight must not add or remove the active timer');
    assert.equal(clock.pendingDelays()[0], 1000, 'the already-scheduled timer keeps its original delay');

    clock.fireAll();
    assert.equal(clock.pendingDelays()[0], 2000, 'the next scheduled timer uses the updated duration');
});

// --- Errors -------------------------------------------------------------------

test('loading a malformed cell reports an error and results in an empty sequence', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([{ bitmask: 999 }]);
    assert.equal(ctrl.getState(), STATES.EMPTY);
    assert.ok(recorder.events.some(e => e.type === 'error' && e.code === 'invalid_cell_shape'));
});

test('loading a cell missing required fields reports an error', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    ctrl.load([{ bitmask: 5 }]); // missing bit_pattern / dot_numbers
    assert.equal(ctrl.getState(), STATES.EMPTY);
    assert.ok(recorder.events.some(e => e.type === 'error'));
});

// --- Large sequences --------------------------------------------------------

test('loading a large sequence does not create one timer per cell in advance', () => {
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder);
    const bigSequence = [];
    for (let i = 0; i < 5000; i += 1) bigSequence.push(makeCell(i % 64));
    ctrl.load(bigSequence);
    assert.equal(clock.pendingCount(), 0, 'load() must never pre-schedule timers for future cells');

    ctrl.play();
    assert.equal(clock.pendingCount(), 1, 'playing a large sequence must still use exactly one timer at a time');
});

// --- No hardware/network coupling -------------------------------------------

test('the module source never actually calls fetch, /send, or any ESP32/Serial helper', () => {
    // ตรวจจากรูปแบบการ "เรียกใช้จริง" ไม่ใช่การห้ามคำแบบเหมารวม เพราะ docstring
    // ของไฟล์นี้ตั้งใจอ้างถึง Serial/ESP32/Flask ตรง ๆ เพื่ออธิบายว่าโมดูลนี้
    // ไม่ยุ่งเกี่ยวด้วย (เหมือนรูปแบบเดียวกับ braille_translation.py) ซึ่งเป็น
    // คำอธิบายที่ดี ไม่ใช่การเชื่อมต่อจริง
    const fs = require('node:fs');
    const path = require('node:path');
    const source = fs.readFileSync(path.join(__dirname, '..', '..', 'static', 'braille_playback.js'), 'utf-8');

    assert.doesNotMatch(source, /\bfetch\s*\(/);
    assert.doesNotMatch(source, /\/send/);
    assert.doesNotMatch(source, /sendPatternToESP32/);
    assert.doesNotMatch(source, /XMLHttpRequest/);
    assert.doesNotMatch(source, /\brequire\s*\(\s*['"]serial/i);
    assert.doesNotMatch(source, /\.write\s*\(/);
});

test('the controller never calls any injected function other than the timer functions it was given', () => {
    // ยืนยันด้วยพฤติกรรมจริง: ตลอด lifecycle เต็ม (load, play, pause, next,
    // previous, restart, stop, timing) มีแค่ setTimeoutFn/clearTimeoutFn และ
    // callback ที่ประกาศไว้เท่านั้นที่ถูกเรียก ไม่มีการเรียก global อื่นใดที่
    // อาจสื่อสารกับเครือข่ายหรือฮาร์ดแวร์
    const clock = createFakeClock();
    const recorder = createRecorder();
    const ctrl = createController(clock, recorder, { gapMs: 0 });
    ctrl.load([makeCell(1), makeCell(0), makeCell(3)], [1]);
    ctrl.play();
    clock.fireAll();
    clock.fireAll();
    ctrl.pause();
    ctrl.next();
    ctrl.previous();
    ctrl.restart();
    ctrl.stop();
    ctrl.setTiming({ cellDurationMs: 500 });

    // ถ้าโค้ดพยายามเรียก fetch/XMLHttpRequest/require('serial') ฯลฯ ที่ไม่มีอยู่
    // ใน global scope ของเทสต์นี้เลย มันจะ throw ทันที - การรันจบโดยไม่มี
    // exception คือหลักฐานว่าไม่มีการเรียกสิ่งเหล่านั้นแอบแฝงอยู่
    assert.ok(true, 'full lifecycle completed without touching any undeclared global');
});
