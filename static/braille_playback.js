/**
 * Step 5: ตัวควบคุมการเล่นลำดับอักษรเบรลล์ 6 จุดแบบจำลอง (single-cell playback
 * controller) - เป็น state machine บริสุทธิ์ล้วน ไม่ยุ่งกับ Flask, OCR, Liblouis,
 * Serial, ESP32, หรือ network request ใด ๆ เลย ไม่แม้แต่จะรู้จัก DOM
 *
 * รับ timer function (setTimeout/clearTimeout) แบบ inject เข้ามาเสมอ เพื่อให้
 * เทสต์ควบคุมเวลาได้แบบ deterministic โดยไม่ต้องรอเวลาจริง (ดู
 * tests/js/braille_playback.test.js)
 *
 * ไฟล์นี้โหลดได้ทั้งแบบ <script> ธรรมดาในเบราว์เซอร์ (ผูกกับ window) และแบบ
 * require() ใน Node สำหรับเทสต์ (module.exports) - ไม่ต้องใช้ bundler หรือ
 * ES module ให้ตรงกับสถาปัตยกรรมเดิมของโปรเจกต์
 *
 * === เซลล์ว่างจริง vs ช่องว่างชั่วคราวระหว่างเซลล์ ===
 * เซลล์ว่างจริง (bitmask 0, "000000", U+2800) เป็นเซลล์หนึ่งในลำดับที่มี index
 * และระยะเวลาแสดงผลของตัวเอง (เช่น ช่องว่างระหว่างคำในข้อความจริง) ส่วนช่องว่าง
 * ชั่วคราวระหว่างเซลล์ (inter-cell gap) เป็นเพียงจังหวะเว้นระหว่างการแสดงเซลล์
 * สองเซลล์ที่ต่อเนื่องกัน **ไม่นับเป็นเซลล์ ไม่มี index ของตัวเอง ไม่เปลี่ยน
 * cell_count** - ต้องไม่สับสนสองสิ่งนี้เข้าด้วยกันในทุกจุดของโค้ด
 *
 * === line boundaries ===
 * ใช้ metadata line_boundaries จาก API แปลเบรลล์ตรง ๆ (รายการตำแหน่ง cell index
 * สะสมที่ "จบ" แต่ละบรรทัด ยกเว้นบรรทัดสุดท้าย) ไม่มีการสร้างรูปแบบจุดสำหรับ
 * newline เอง และไม่นับ newline เป็นเซลล์ - แค่ใช้ตัดสินว่าเมื่อไหร่ควรหยุดพัก
 * เพิ่มเติมและประกาศว่าขึ้นบรรทัดใหม่แล้วเท่านั้น
 */

(function (root, factory) {
    const exported = factory();
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = exported;
    }
    if (typeof root !== 'undefined') {
        root.BraillePlaybackController = exported.BraillePlaybackController;
        root.BRAILLE_PLAYBACK_STATES = exported.BRAILLE_PLAYBACK_STATES;
        root.BRAILLE_PLAYBACK_TIMING_LIMITS = exported.BRAILLE_PLAYBACK_TIMING_LIMITS;
        root.BRAILLE_PLAYBACK_DEFAULT_TIMING = exported.BRAILLE_PLAYBACK_DEFAULT_TIMING;
    }
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this), function () {
    'use strict';

    // สถานะทั้งหมดของ playback state machine - ชื่อคงที่ ใช้เทียบด้วย === เสมอ
    const BRAILLE_PLAYBACK_STATES = Object.freeze({
        EMPTY: 'empty',
        READY: 'ready',
        PLAYING_CELL: 'playing_cell',
        PLAYING_GAP: 'playing_gap',
        PAUSED: 'paused',
        COMPLETED: 'completed',
        STOPPED: 'stopped',
    });

    // ช่วงค่าปลอดภัยของการตั้งเวลา (มิลลิวินาที) - ค่าเริ่มต้นเป็นค่าที่เลือกไว้
    // สำหรับต้นแบบ (prototype) เท่านั้น ไม่ใช่มาตรฐานตายตัว ปรับได้ผ่าน setTiming()
    // cellDurationMs มีขั้นต่ำ 300ms เสมอเพื่อไม่ให้เกิด loop ที่หน่วงเวลาเป็น 0
    const BRAILLE_PLAYBACK_TIMING_LIMITS = Object.freeze({
        cellDurationMs: Object.freeze({ min: 300, max: 5000 }),
        gapMs: Object.freeze({ min: 0, max: 2000 }),
        linePauseMs: Object.freeze({ min: 0, max: 5000 }),
    });

    const BRAILLE_PLAYBACK_DEFAULT_TIMING = Object.freeze({
        cellDurationMs: 900,
        gapMs: 150,
        linePauseMs: 700,
    });

    function clamp(value, min, max) {
        return Math.min(Math.max(value, min), max);
    }

    // ตรวจว่าเป็นตัวเลขจำกัด (finite) จริง - ปฏิเสธ NaN, Infinity, string, ฯลฯ
    function isFiniteNumber(value) {
        return typeof value === 'number' && Number.isFinite(value);
    }

    // ตรวจโครงสร้างขั้นต่ำของ BrailleCell ที่ได้จาก API (ดู braille_models.py)
    // ไม่ตรวจความถูกต้องทางภาษาศาสตร์ใด ๆ - ตรวจแค่รูปร่างข้อมูลที่ต้องมี
    function isValidCellShape(cell) {
        return (
            cell &&
            typeof cell === 'object' &&
            isFiniteNumber(cell.bitmask) &&
            cell.bitmask >= 0 &&
            cell.bitmask <= 63 &&
            typeof cell.bit_pattern === 'string' &&
            cell.bit_pattern.length === 6 &&
            Array.isArray(cell.dot_numbers)
        );
    }

    function noop() {}

    class BraillePlaybackController {
        /**
         * @param {object} [options]
         * @param {function} [options.setTimeoutFn] - inject เพื่อทดสอบแบบ deterministic
         * @param {function} [options.clearTimeoutFn]
         * @param {function} [options.onCellDisplay] - ({cell, index, cellCount, lineNumber, isBlank, announce}) => void
         * @param {function} [options.onTransientBlank] - () => void - เคลียร์จอจำลองชั่วคราวระหว่างเซลล์ (ไม่ใช่เซลล์ว่างจริง)
         * @param {function} [options.onStateChange] - (state) => void
         * @param {function} [options.onLineChange] - ({lineNumber}) => void
         * @param {function} [options.onComplete] - () => void
         * @param {function} [options.onError] - ({code, message}) => void
         */
        constructor(options) {
            const opts = options || {};
            this._setTimeout = opts.setTimeoutFn || (typeof setTimeout !== 'undefined' ? setTimeout : null);
            this._clearTimeout = opts.clearTimeoutFn || (typeof clearTimeout !== 'undefined' ? clearTimeout : null);
            this._onCellDisplay = opts.onCellDisplay || noop;
            this._onTransientBlank = opts.onTransientBlank || noop;
            this._onStateChange = opts.onStateChange || noop;
            this._onLineChange = opts.onLineChange || noop;
            this._onComplete = opts.onComplete || noop;
            this._onError = opts.onError || noop;

            this._cells = [];
            this._lineBoundaries = [];
            this._currentIndex = 0;
            this._state = BRAILLE_PLAYBACK_STATES.EMPTY;
            this._timerId = null;
            // เพิ่มทุกครั้งที่ load() ถูกเรียก - ใช้ตัด callback ของ timer เก่าที่
            // ยังค้างอยู่จาก sequence ก่อนหน้า ไม่ให้ทำงานทับ sequence ใหม่
            this._sequenceToken = 0;
            this._lastAnnouncedLine = null;

            this._timing = Object.assign({}, BRAILLE_PLAYBACK_DEFAULT_TIMING);
        }

        // --- ข้อมูลลำดับ (sequence) ------------------------------------------

        /**
         * โหลดลำดับเซลล์ใหม่ ยกเลิก timer เก่าทั้งหมดทันที ไม่เริ่มเล่นอัตโนมัติ
         * (ตำแหน่งเริ่มต้นคือเซลล์แรก - ต้องกด "เริ่มเล่น" เอง)
         * @param {Array} cells - รายการ BrailleCell จาก API (index, bitmask, bit_pattern, dot_numbers, unicode_braille)
         * @param {Array<number>} [lineBoundaries] - metadata line_boundaries จาก API
         */
        load(cells, lineBoundaries) {
            this._cancelTimer();
            this._sequenceToken += 1;
            this._lastAnnouncedLine = null;

            const cellArray = Array.isArray(cells) ? cells : [];
            for (let i = 0; i < cellArray.length; i += 1) {
                if (!isValidCellShape(cellArray[i])) {
                    this._cells = [];
                    this._lineBoundaries = [];
                    this._currentIndex = 0;
                    this._setState(BRAILLE_PLAYBACK_STATES.EMPTY);
                    this._onError({
                        code: 'invalid_cell_shape',
                        message: `เซลล์ที่ตำแหน่ง ${i} มีโครงสร้างข้อมูลไม่ถูกต้อง ไม่สามารถโหลดลำดับนี้ได้`,
                    });
                    return;
                }
            }

            this._cells = cellArray.slice();
            this._lineBoundaries = Array.isArray(lineBoundaries) ? lineBoundaries.slice() : [];
            this._currentIndex = 0;

            if (this._cells.length === 0) {
                this._setState(BRAILLE_PLAYBACK_STATES.EMPTY);
                return;
            }

            this._setState(BRAILLE_PLAYBACK_STATES.READY);
            this._displayCurrentCell({ announce: true });
        }

        /** ล้างลำดับทั้งหมดกลับสู่สถานะว่างเปล่า (ใช้ตอนเริ่ม OCR ใหม่) */
        clear() {
            this.load([]);
        }

        // --- การเล่นอัตโนมัติ --------------------------------------------------

        /** เริ่ม/เล่นต่อจากตำแหน่งปัจจุบัน - กดซ้ำระหว่างเล่นอยู่แล้วจะไม่ทำอะไร
         * (ไม่สร้าง timer ซ้อนกัน) */
        play() {
            if (this._cells.length === 0) return;
            if (
                this._state === BRAILLE_PLAYBACK_STATES.PLAYING_CELL ||
                this._state === BRAILLE_PLAYBACK_STATES.PLAYING_GAP
            ) {
                return;
            }
            // เล่นครบแล้วต้องกด "เริ่มใหม่" อย่างชัดเจนก่อน ไม่เล่นซ้ำอัตโนมัติ
            if (this._state === BRAILLE_PLAYBACK_STATES.COMPLETED) return;

            this._beginCellPhase(true);
        }

        /** หยุดชั่วคราว - เก็บตำแหน่งปัจจุบันไว้ ยกเลิก timer ที่ค้างอยู่ */
        pause() {
            if (
                this._state !== BRAILLE_PLAYBACK_STATES.PLAYING_CELL &&
                this._state !== BRAILLE_PLAYBACK_STATES.PLAYING_GAP
            ) {
                return;
            }
            this._cancelTimer();
            this._setState(BRAILLE_PLAYBACK_STATES.PAUSED);
        }

        /** หยุดเล่นทั้งหมด ยกเลิก timer ทุกตัว เคลียร์จอจำลอง (ไม่ย้อนตำแหน่งกลับ) */
        stop() {
            this._cancelTimer();
            if (this._cells.length === 0) {
                this._setState(BRAILLE_PLAYBACK_STATES.EMPTY);
                return;
            }
            this._setState(BRAILLE_PLAYBACK_STATES.STOPPED);
            this._onTransientBlank();
        }

        /** กลับไปเซลล์แรก ไม่เล่นอัตโนมัติ (ต้องกดเริ่มเล่นเอง) */
        restart() {
            if (this._cells.length === 0) return;
            this._cancelTimer();
            this._currentIndex = 0;
            this._lastAnnouncedLine = null;
            this._setState(BRAILLE_PLAYBACK_STATES.READY);
            this._displayCurrentCell({ announce: true });
        }

        // --- การเลื่อนตำแหน่งด้วยมือ --------------------------------------------

        /** ไปเซลล์จริงถัดไปหนึ่งเซลล์ (หยุดการเล่นอัตโนมัติที่กำลังทำงานอยู่ก่อนเสมอ) */
        next() {
            if (this._cells.length === 0) return;
            this._cancelTimer();
            if (this._currentIndex < this._cells.length - 1) {
                this._currentIndex += 1;
            }
            this._setState(BRAILLE_PLAYBACK_STATES.PAUSED);
            this._displayCurrentCell({ announce: true });
        }

        /** ไปเซลล์จริงก่อนหน้าหนึ่งเซลล์ (หยุดการเล่นอัตโนมัติที่กำลังทำงานอยู่ก่อนเสมอ) */
        previous() {
            if (this._cells.length === 0) return;
            this._cancelTimer();
            if (this._currentIndex > 0) {
                this._currentIndex -= 1;
            }
            this._setState(BRAILLE_PLAYBACK_STATES.PAUSED);
            this._displayCurrentCell({ announce: true });
        }

        // --- การตั้งเวลา ---------------------------------------------------------

        /**
         * ปรับค่าการตั้งเวลา - ค่าที่ไม่ใช่ตัวเลขจำกัด (finite) จะถูกละเว้น (คงค่า
         * เดิมไว้) ค่าที่อยู่นอกช่วงปลอดภัยจะถูก clamp ให้อยู่ในช่วงเสมอ ไม่มีทาง
         * ทำให้เกิด loop หน่วงเวลาเป็น 0 การเปลี่ยนแปลงมีผลกับการเปลี่ยนสถานะ
         * ครั้งถัดไปเท่านั้น ไม่กระทบ timer ที่ตั้งไว้แล้วและไม่เริ่มเล่นซ้ำ
         */
        setTiming(partialTiming) {
            const next = partialTiming || {};
            const limits = BRAILLE_PLAYBACK_TIMING_LIMITS;

            if (isFiniteNumber(next.cellDurationMs)) {
                this._timing.cellDurationMs = clamp(next.cellDurationMs, limits.cellDurationMs.min, limits.cellDurationMs.max);
            }
            if (isFiniteNumber(next.gapMs)) {
                this._timing.gapMs = clamp(next.gapMs, limits.gapMs.min, limits.gapMs.max);
            }
            if (isFiniteNumber(next.linePauseMs)) {
                this._timing.linePauseMs = clamp(next.linePauseMs, limits.linePauseMs.min, limits.linePauseMs.max);
            }
        }

        getTiming() {
            return Object.assign({}, this._timing);
        }

        // --- ข้อมูลสถานะปัจจุบัน (สำหรับ UI/เทสต์) --------------------------------

        getState() {
            return this._state;
        }

        getCurrentIndex() {
            return this._currentIndex;
        }

        getCellCount() {
            return this._cells.length;
        }

        getCurrentCell() {
            return this._cells.length === 0 ? null : this._cells[this._currentIndex];
        }

        getCurrentLineNumber() {
            return this._cells.length === 0 ? null : this._computeLineNumber(this._currentIndex);
        }

        // --- ภายใน (private) ----------------------------------------------------

        _setState(nextState) {
            this._state = nextState;
            this._onStateChange(nextState);
        }

        _cancelTimer() {
            if (this._timerId !== null && this._clearTimeout) {
                this._clearTimeout(this._timerId);
            }
            this._timerId = null;
        }

        _computeLineNumber(index) {
            // line_boundaries คือตำแหน่ง cell index สะสมที่ "จบ" แต่ละบรรทัด
            // (ไม่รวมบรรทัดสุดท้าย) - นับเลขบรรทัดเริ่มที่ 1
            let line = 1;
            for (let i = 0; i < this._lineBoundaries.length; i += 1) {
                if (index >= this._lineBoundaries[i]) {
                    line += 1;
                } else {
                    break;
                }
            }
            return line;
        }

        _displayCurrentCell(opts) {
            const options = opts || {};
            const cell = this._cells[this._currentIndex];
            const lineNumber = this._computeLineNumber(this._currentIndex);
            const lineChanged = lineNumber !== this._lastAnnouncedLine;
            this._lastAnnouncedLine = lineNumber;

            this._onCellDisplay({
                cell: cell,
                index: this._currentIndex,
                cellCount: this._cells.length,
                lineNumber: lineNumber,
                isBlank: cell.bitmask === 0,
                announce: options.announce === true,
            });

            if (lineChanged) {
                // การขึ้นบรรทัดใหม่ต้องประกาศเสมอ ไม่ถูกจำกัดด้วย throttling ของ
                // การเล่นอัตโนมัติ เพราะเกิดขึ้นไม่บ่อย (ครั้งเดียวต่อบรรทัด)
                this._onLineChange({ lineNumber: lineNumber });
            }
        }

        _beginCellPhase(announceFirstCell) {
            const token = this._sequenceToken;
            this._setState(BRAILLE_PLAYBACK_STATES.PLAYING_CELL);
            this._displayCurrentCell({ announce: announceFirstCell === true });

            this._timerId = this._setTimeout(() => {
                if (token !== this._sequenceToken) return; // sequence ถูกโหลดใหม่แล้ว ทิ้ง callback นี้
                this._timerId = null;
                this._onCellPhaseComplete(token);
            }, this._timing.cellDurationMs);
        }

        _onCellPhaseComplete(token) {
            if (token !== this._sequenceToken) return;

            const isLastCell = this._currentIndex >= this._cells.length - 1;
            if (this._timing.gapMs > 0 && !isLastCell) {
                this._beginGapPhase(token);
            } else {
                this._advanceOrComplete(token);
            }
        }

        _beginGapPhase(token) {
            this._setState(BRAILLE_PLAYBACK_STATES.PLAYING_GAP);
            this._onTransientBlank();

            this._timerId = this._setTimeout(() => {
                if (token !== this._sequenceToken) return;
                this._timerId = null;
                this._advanceOrComplete(token);
            }, this._timing.gapMs);
        }

        _advanceOrComplete(token) {
            if (token !== this._sequenceToken) return;

            if (this._currentIndex >= this._cells.length - 1) {
                this._setState(BRAILLE_PLAYBACK_STATES.COMPLETED);
                this._onComplete();
                return;
            }

            const lineBeforeAdvance = this._computeLineNumber(this._currentIndex);
            this._currentIndex += 1;
            const lineAfterAdvance = this._computeLineNumber(this._currentIndex);
            const crossedLine = lineAfterAdvance !== lineBeforeAdvance;

            if (crossedLine && this._timing.linePauseMs > 0) {
                this._setState(BRAILLE_PLAYBACK_STATES.PLAYING_GAP);
                this._onTransientBlank();
                this._timerId = this._setTimeout(() => {
                    if (token !== this._sequenceToken) return;
                    this._timerId = null;
                    this._beginCellPhase(false);
                }, this._timing.linePauseMs);
            } else {
                this._beginCellPhase(false);
            }
        }
    }

    return {
        BraillePlaybackController: BraillePlaybackController,
        BRAILLE_PLAYBACK_STATES: BRAILLE_PLAYBACK_STATES,
        BRAILLE_PLAYBACK_TIMING_LIMITS: BRAILLE_PLAYBACK_TIMING_LIMITS,
        BRAILLE_PLAYBACK_DEFAULT_TIMING: BRAILLE_PLAYBACK_DEFAULT_TIMING,
    };
});
