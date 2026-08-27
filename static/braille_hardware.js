/**
 * Step 6: สะพานเชื่อมการเล่นเบรลล์แบบจำลอง (Step 5) เข้ากับเส้นทาง Serial จริง
 * ผ่านเซสชันฮาร์ดแวร์ฝั่งเซิร์ฟเวอร์ - แบบมี opt-in ชัดเจน หยุดปลอดภัย และ
 * validate เข้ม
 *
 * โมดูลนี้ **ไม่รู้จัก DOM** เลย (เหมือน static/braille_playback.js) - รับ
 * fetch function และ callback ทั้งหมดแบบ inject เพื่อให้เทสต์ควบคุมได้แบบ
 * deterministic ไม่มีการเรียก fetch จริงในเทสต์
 *
 * กติกา:
 *  - โหมดฮาร์ดแวร์จริง **ปิดอยู่เสมอ** ตอนสร้าง instance และตอนโหลดหน้าใหม่
 *  - ไม่ส่งอะไรไปเซิร์ฟเวอร์เลยจนกว่า setHardwareModeEnabled(true) + startSession()
 *  - onCell -> ส่ง bit_pattern ของเซลล์นั้น (พร้อม real_cell_index)
 *  - onTransientBlank -> ส่ง "000000" แต่ไม่เพิ่ม real-cell index
 *  - onStop / onComplete / onError -> หยุดเซสชันและล้างเซลล์
 *  - callback ที่ล้าสมัย (เซสชันถูกปิดไปแล้ว) จะถูกทิ้ง ไม่ส่งต่อ
 *
 * === การจัดคิว (serialization) ===
 * ทุกคำขอที่เปลี่ยนสถานะฮาร์ดแวร์ (display cell, transient gap, verify) ของ
 * เซสชันหนึ่ง ถูกจัดคิวและทำ **ทีละคำขอเท่านั้น** ไม่มีทางที่สองคำขอจะออกพร้อม
 * กันด้วย generation เดียวกัน (ซึ่งจะทำให้คำขอที่สองได้ 409 stale_session)
 * แต่ละคำขอในคิวใช้ generation ล่าสุดที่ได้จาก response ของคำขอก่อนหน้า
 * การหยุด (stopSession) มีลำดับความสำคัญสูงสุด: ทำให้เซสชัน client เป็นโมฆะ
 * ทันที ล้างคิว แล้วส่งคำขอ stop/clear แบบ best-effort โดยไม่รอคิว
 *
 * "สำเร็จ" มีสี่ระดับ (ดู README): accepted_by_server / written_to_serial /
 * acknowledged_by_device (unknown) / physically_displayed (unknown) - โมดูลนี้
 * ห้ามแปลง written_to_serial เป็นข้อความว่าอุปกรณ์แสดงผลสำเร็จ
 */

(function (root, factory) {
    const exported = factory();
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = exported;
    }
    if (typeof root !== 'undefined') {
        root.BrailleHardwareBridge = exported.BrailleHardwareBridge;
        root.BRAILLE_HARDWARE_ENDPOINTS = exported.BRAILLE_HARDWARE_ENDPOINTS;
        root.BRAILLE_HARDWARE_UNCONFIRMED_MESSAGE = exported.BRAILLE_HARDWARE_UNCONFIRMED_MESSAGE;
    }
})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this), function () {
    'use strict';

    const BRAILLE_HARDWARE_ENDPOINTS = Object.freeze({
        status: '/api/hardware/status',
        ports: '/api/hardware/ports',
        start: '/api/hardware/playback/start',
        cell: '/api/hardware/playback/cell',
        stop: '/api/hardware/playback/stop',
        verifyCell: '/api/hardware/verify/cell',
    });

    // ข้อความมาตรฐานหลัง write() - **ห้าม** เปลี่ยนเป็น "ESP32 แสดงผลสำเร็จ"
    const BRAILLE_HARDWARE_UNCONFIRMED_MESSAGE =
        'ส่งคำสั่งผ่าน Serial แล้ว แต่ยังไม่ได้รับการยืนยันจากอุปกรณ์';

    const CLEAR_PATTERN = '000000';
    const SIX_BIT_RE = /^[01]{6}$/;

    function noop() {}

    class BrailleHardwareBridge {
        /**
         * @param {object} [options]
         * @param {function} [options.fetchFn] - (url, opts) => Promise<Response-like>
         * @param {function} [options.onSendStatus] - ({phase, message, detail}) => void
         * @param {function} [options.onConnectionStatus] - ({connected, port, message}) => void
         * @param {function} [options.onWatchdogStatus] - ({message}) => void
         * @param {function} [options.onModeChange] - (enabled) => void
         * @param {function} [options.onSessionChange] - ({active, sessionId}) => void
         */
        constructor(options) {
            const opts = options || {};
            this._fetch = opts.fetchFn || (typeof fetch !== 'undefined' ? fetch.bind(null) : null);
            this._onSendStatus = opts.onSendStatus || noop;
            this._onConnectionStatus = opts.onConnectionStatus || noop;
            this._onWatchdogStatus = opts.onWatchdogStatus || noop;
            this._onModeChange = opts.onModeChange || noop;
            this._onSessionChange = opts.onSessionChange || noop;

            // ปิดเสมอตอนสร้าง - ไม่มีทางเปิดโดยไม่มีการกระทำที่ชัดเจนของผู้ใช้
            this._hardwareModeEnabled = false;
            this._selectedPort = null;
            this._portConnected = false;

            this._sessionId = null;
            this._generation = null;
            this._sessionActive = false;
            // เพิ่มทุกครั้งที่เริ่ม/หยุดเซสชัน - ใช้ทิ้ง callback/คำขอที่ค้างจาก
            // เซสชันเก่า (queue item ที่ epoch ไม่ตรงจะถูกทิ้งเป็น stale)
            this._sessionEpoch = 0;

            // คิวคำสั่งที่เปลี่ยนสถานะฮาร์ดแวร์ - ทำทีละคำขอ
            this._mutationQueue = [];
            this._queueRunning = false;
        }

        // --- สถานะ ---------------------------------------------------------

        isHardwareModeEnabled() { return this._hardwareModeEnabled; }
        isSessionActive() { return this._sessionActive; }
        getSelectedPort() { return this._selectedPort; }
        isPortConnected() { return this._portConnected; }
        getGeneration() { return this._generation; }
        // จำนวนคำขอที่รอในคิว + ที่กำลังทำอยู่ (สำหรับเทสต์/สถานะ)
        pendingMutationCount() { return this._mutationQueue.length + (this._queueRunning ? 1 : 0); }

        setSelectedPort(port) {
            this._selectedPort = port || null;
        }

        setPortConnected(connected, port) {
            this._portConnected = connected === true;
            if (port) this._selectedPort = port;
            this._onConnectionStatus({
                connected: this._portConnected,
                port: this._selectedPort,
                message: this._portConnected
                    ? `เชื่อมต่อพอร์ต ${this._selectedPort || ''} แล้ว (ยังไม่ยืนยันชนิดอุปกรณ์)`
                    : 'ยังไม่ได้เชื่อมต่อพอร์ต Serial',
            });
        }

        /**
         * เปิด/ปิดโหมดฮาร์ดแวร์จริง - การปิดจะสั่งหยุดเซสชันและล้างเซลล์เสมอ
         */
        async setHardwareModeEnabled(enabled) {
            const next = enabled === true;
            if (next === this._hardwareModeEnabled) return;
            this._hardwareModeEnabled = next;
            this._onModeChange(next);
            if (!next && this._sessionActive) {
                await this.stopSession('ปิดโหมดฮาร์ดแวร์จริง');
            }
        }

        // --- เซสชัน -------------------------------------------------------

        /**
         * เริ่มเซสชันฮาร์ดแวร์ - ต้องเปิดโหมด + เชื่อมต่อพอร์ต + ยืนยัน opt-in
         * @param {object} [opts]
         * @param {number} [opts.watchdogSeconds]
         */
        async startSession(opts) {
            const options = opts || {};
            if (!this._hardwareModeEnabled) {
                return this._fail('hardware_mode_disabled', 'ยังไม่ได้เปิดโหมดฮาร์ดแวร์จริง');
            }
            if (!this._portConnected) {
                return this._fail('serial_not_connected', 'ต้องเลือกและเชื่อมต่อพอร์ต Serial ก่อน');
            }
            if (this._sessionActive) {
                return { ok: true, sessionId: this._sessionId, alreadyActive: true };
            }

            const body = { hardware_playback_opt_in: true };
            if (typeof options.watchdogSeconds === 'number') {
                body.watchdog_seconds = options.watchdogSeconds;
            }

            const res = await this._request(BRAILLE_HARDWARE_ENDPOINTS.start, body);
            if (!res.ok) {
                return this._fail(res.code, res.message);
            }
            // เซสชันใหม่ทำให้คิว/response ของเซสชันเก่าเป็นโมฆะทั้งหมด
            this._sessionEpoch += 1;
            this._clearQueue();
            this._sessionId = res.data.session_id;
            this._generation = res.data.generation;
            this._sessionActive = true;
            this._onSessionChange({ active: true, sessionId: this._sessionId });
            this._onSendStatus({
                phase: 'session_started',
                message: 'เริ่มเซสชันฮาร์ดแวร์แล้ว (ล้างเซลล์ก่อนเริ่ม) — ยังไม่มีการยืนยันจากอุปกรณ์',
            });
            return { ok: true, sessionId: this._sessionId };
        }

        /**
         * หยุดเซสชัน - ยกเลิกฝั่ง client "ก่อน" แล้วจึงแจ้งเซิร์ฟเวอร์ให้ล้างเซลล์
         * ป้องกัน timer/callback ที่ค้างไม่ให้ส่งอะไรอีกหลังจากนี้
         */
        async stopSession(reason) {
            const wasActive = this._sessionActive;
            const sessionId = this._sessionId;
            // 1) ยกเลิกฝั่ง client "ก่อน" ทำงานอื่นเสมอ - stop มีลำดับความสำคัญ
            //    สูงสุด ต้องไม่ถูกบล็อกอยู่หลังคิวคำขอที่ยาว
            this._sessionEpoch += 1;
            this._sessionActive = false;
            this._sessionId = null;
            this._generation = null;
            // ทิ้งคำขอที่ค้างในคิวทั้งหมด (คำขอที่กำลังทำอยู่จะกลายเป็น stale เอง
            // ตอน response กลับมา เพราะ epoch เปลี่ยนแล้ว)
            this._clearQueue();
            this._onSessionChange({ active: false, sessionId: null });

            if (!wasActive) {
                return { ok: true, wasActive: false };
            }

            // 2) แจ้งเซิร์ฟเวอร์ให้ล้างเซลล์ (best-effort, ไม่ผ่านคิว)
            //    เส้นทาง /stop ฝั่งเซิร์ฟเวอร์เป็น idempotent และไม่ตรวจ generation
            const res = await this._request(BRAILLE_HARDWARE_ENDPOINTS.stop, { session_id: sessionId });
            this._onSendStatus({
                phase: 'session_stopped',
                message: reason
                    ? `หยุดเซสชันฮาร์ดแวร์แล้ว (${reason})`
                    : 'หยุดเซสชันฮาร์ดแวร์และล้างเซลล์แล้ว',
                detail: res.ok
                    ? (res.data.cleared ? 'ส่งคำสั่งล้างเซลล์แล้ว' : 'พยายามล้างเซลล์แต่ไม่สำเร็จ')
                    : res.message,
            });
            return { ok: true, wasActive: true, serverResult: res.ok ? res.data : null };
        }

        // --- callback จาก playback (Step 5) --------------------------------

        /**
         * เชื่อมกับ onCellDisplay ของ BraillePlaybackController
         * ส่งเฉพาะตอนโหมดเปิด + เซสชัน active + เป็นการแสดงเซลล์จริง (มี index)
         * @param {object} cell - ต้องมี bit_pattern (^[01]{6}$)
         * @param {number} realCellIndex
         */
        async sendCell(cell, realCellIndex) {
            if (!this._canSend()) return { ok: false, skipped: true };
            const pattern = cell && cell.bit_pattern;
            if (typeof pattern !== 'string' || !SIX_BIT_RE.test(pattern)) {
                return this._fail('invalid_pattern', 'รูปแบบจุดของเซลล์ไม่ถูกต้อง (ต้องเป็น 0/1 หกหลัก)');
            }
            if (typeof realCellIndex !== 'number' || realCellIndex < 0) {
                return this._fail('invalid_pattern', 'ดัชนีเซลล์จริงไม่ถูกต้อง');
            }
            return this._enqueueMutation(() => this._sendToEndpoint(BRAILLE_HARDWARE_ENDPOINTS.cell, {
                bit_pattern: pattern,
                real_cell_index: realCellIndex,
            }));
        }

        /**
         * เชื่อมกับ onTransientBlank - ส่ง "000000" แต่ไม่เพิ่ม real-cell index
         * ใช้ทั้งช่องว่างชั่วคราวระหว่างเซลล์ และช่วงหยุดขึ้นบรรทัดใหม่
         */
        async sendTransientGap() {
            if (!this._canSend()) return { ok: false, skipped: true };
            return this._enqueueMutation(() => this._sendToEndpoint(BRAILLE_HARDWARE_ENDPOINTS.cell, {
                transient_gap: true,
                bit_pattern: CLEAR_PATTERN,
            }));
        }

        /**
         * โหมดตรวจสอบลำดับจุดด้วยมือ - ส่งรูปแบบจุดเดียว (หรือ "000000") ผ่าน
         * เส้นทาง verify ต้องมีเซสชัน active (ใช้ watchdog เดียวกันจำกัดเวลา)
         */
        async verifyPattern(pattern) {
            if (!this._canSend()) {
                return this._fail('session_not_active', 'ต้องเปิดโหมด + เชื่อมต่อ + เริ่มเซสชันก่อนทดสอบ');
            }
            if (typeof pattern !== 'string' || !SIX_BIT_RE.test(pattern) || pattern === '111111') {
                return this._fail('invalid_pattern', 'โหมดตรวจสอบรับเฉพาะรูปแบบจุดเดียวหรือรูปแบบล้าง');
            }
            return this._enqueueMutation(() => this._sendToEndpoint(
                BRAILLE_HARDWARE_ENDPOINTS.verifyCell,
                { bit_pattern: pattern },
                { detailPrefix: `ทดสอบรูปแบบ ${pattern}` },
            ));
        }

        /** onComplete / onError / onStop ทั้งหมดจบเซสชันแบบเดียวกัน */
        async handlePlaybackEnded(reason) {
            if (!this._sessionActive) return { ok: true, wasActive: false };
            return this.stopSession(reason || 'การเล่นสิ้นสุด');
        }

        // --- ภายใน -------------------------------------------------------

        _canSend() {
            return this._hardwareModeEnabled && this._sessionActive && this._sessionId !== null;
        }

        /**
         * ใส่คำสั่งที่เปลี่ยนสถานะฮาร์ดแวร์เข้าคิว - ทำทีละคำขอตามลำดับ
         * @param {function} run - () => Promise<result> เรียกตอนถึงคิว (อ่าน
         *   this._generation สด ณ ตอนนั้น จึงได้ค่าล่าสุดจาก response ก่อนหน้า)
         */
        _enqueueMutation(run) {
            return new Promise((resolve) => {
                this._mutationQueue.push({ epoch: this._sessionEpoch, run, resolve });
                this._pumpQueue();
            });
        }

        async _pumpQueue() {
            if (this._queueRunning) return;
            this._queueRunning = true;
            try {
                while (this._mutationQueue.length > 0) {
                    const item = this._mutationQueue.shift();
                    // เซสชันถูกหยุด/รีสตาร์ต หรือหมดอายุ ระหว่างรอคิว -> ทิ้ง
                    if (item.epoch !== this._sessionEpoch || !this._sessionActive) {
                        item.resolve({ ok: false, stale: true });
                        continue;
                    }
                    let result;
                    try {
                        result = await item.run();
                    } catch (err) {
                        result = this._fail('write_failed', `คำสั่งฮาร์ดแวร์ล้มเหลว: ${err && err.message}`);
                    }
                    item.resolve(result);
                }
            } finally {
                this._queueRunning = false;
            }
        }

        /** ทิ้งคำขอที่รอในคิวทั้งหมด (คำขอที่กำลังทำอยู่ปล่อยให้จบเองเป็น stale) */
        _clearQueue() {
            const items = this._mutationQueue;
            this._mutationQueue = [];
            items.forEach(it => it.resolve({ ok: false, aborted: true }));
        }

        async _sendToEndpoint(url, extraBody, opts) {
            const options = opts || {};
            const epoch = this._sessionEpoch;
            const body = Object.assign(
                { session_id: this._sessionId, generation: this._generation },
                extraBody
            );
            const res = await this._request(url, body);

            // เซสชันถูกหยุด/รีสตาร์ตระหว่างรอ response -> ทิ้งผลนี้ ไม่ส่งต่อ
            // (late response ห้ามปลุกเซสชันใหม่ให้ทำงานเด็ดขาด)
            if (epoch !== this._sessionEpoch) {
                return { ok: false, stale: true };
            }
            if (!res.ok) {
                // เซิร์ฟเวอร์บอกว่าเซสชันหมดอายุ/หมดเวลา -> ปิดฝั่ง client + ล้างคิว
                if (['stale_session', 'session_not_active', 'watchdog_expired', 'session_conflict'].includes(res.code)) {
                    this._sessionEpoch += 1;
                    this._sessionActive = false;
                    this._sessionId = null;
                    this._generation = null;
                    this._clearQueue();
                    this._onSessionChange({ active: false, sessionId: null });
                    if (res.code === 'watchdog_expired') {
                        this._onWatchdogStatus({
                            message: 'ระบบความปลอดภัยฝั่งโฮสต์ (watchdog) สั่งล้างเซลล์เนื่องจากไม่มีคำสั่งต่อเนื่อง',
                        });
                    }
                }
                this._onSendStatus({ phase: 'error', message: res.message, detail: res.code });
                return this._fail(res.code, res.message);
            }

            this._generation = res.data.generation;
            this._onSendStatus({
                phase: 'written',
                message: BRAILLE_HARDWARE_UNCONFIRMED_MESSAGE,
                detail: options.detailPrefix
                    ? options.detailPrefix
                    : (res.data.transient_gap
                        ? 'ช่องว่างชั่วคราว (ล้างเซลล์)'
                        : `เซลล์จริงลำดับที่ ${(res.data.real_cell_index || 0) + 1}`),
            });
            return { ok: true, data: res.data };
        }

        async _request(url, body) {
            if (this._fetch === null) {
                return { ok: false, code: 'write_failed', message: 'ไม่มี fetch ให้ใช้งาน' };
            }
            try {
                const response = await this._fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await response.json().catch(() => null);
                if (!response.ok || !data || data.ok === false) {
                    return {
                        ok: false,
                        code: (data && data.error && data.error.code) || 'write_failed',
                        message: (data && data.error && data.error.message) || 'คำสั่งฮาร์ดแวร์ล้มเหลว',
                    };
                }
                return { ok: true, data: data };
            } catch (err) {
                return { ok: false, code: 'write_failed', message: `เชื่อมต่อเซิร์ฟเวอร์ไม่ได้: ${err.message}` };
            }
        }

        _fail(code, message) {
            return { ok: false, code: code, message: message };
        }
    }

    return {
        BrailleHardwareBridge: BrailleHardwareBridge,
        BRAILLE_HARDWARE_ENDPOINTS: BRAILLE_HARDWARE_ENDPOINTS,
        BRAILLE_HARDWARE_UNCONFIRMED_MESSAGE: BRAILLE_HARDWARE_UNCONFIRMED_MESSAGE,
    };
});
