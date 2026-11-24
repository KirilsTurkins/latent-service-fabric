// Finite ordinary TCP Socket API. The compiler supplies this factory's backend;
// applications select normal imports, never a transport/caller id/resource.
export function createNodeNetModule(transport, Buffer, snapshotActive, target = globalThis) {
  const queue = target.queueMicrotask.bind(target);
  const sameValue = Object.is;
  const setTimer = target.setTimeout.bind(target), clearTimer = target.clearTimeout.bind(target);
  let queuedBytes = 0, queuedRecords = 0;
  const maxQueuedBytes = 65536, maxQueuedRecords = 16, windowBytes = 16384;
  const codes = Object.freeze({
    'invalid-input': 'EINVAL', 'invalid-state': 'ERR_INVALID_STATE', unsupported: 'ENOTSUP',
    denied: 'EACCES', revoked: 'EACCES', exhausted: 'ERR_LSF_RESOURCE_EXHAUSTED',
    'dns-failed': 'ERR_LSF_DNS_FAILED', 'tls-failed': 'ERR_LSF_TLS_FAILED',
    'connect-failed': 'ERR_LSF_CONNECT_FAILED', timeout: 'ETIMEDOUT', cancelled: 'ABORT_ERR',
    'io-failed': 'EIO', uncertain: 'ERR_LSF_UNCERTAIN',
  });
  function error(code, syscall, original, accepted = 0, possible = false) {
    const value = new target.Error('lsf-node-net:' + code);
    value.code = code; value.syscall = syscall;
    value.acceptedPrefixBytes = accepted;
    value.mayHaveApplied = possible || original !== undefined && syscall === 'write';
    const payload = original?.payload;
    if (payload && Object.hasOwn(codes, payload.code) &&
        Number.isInteger(payload.acceptedPrefixBytes) && payload.acceptedPrefixBytes >= 0 &&
        payload.acceptedPrefixBytes <= windowBytes && typeof payload.mayHaveApplied === 'boolean') {
      value.code = codes[payload.code]; value.streamCode = payload.code;
      value.acceptedPrefixBytes += payload.acceptedPrefixBytes;
      value.nativeAcceptedPrefixBytes = payload.acceptedPrefixBytes;
      value.nativeMayHaveApplied = payload.mayHaveApplied;
      value.mayHaveApplied = payload.mayHaveApplied || accepted > 0 || payload.acceptedPrefixBytes > 0;
    }
    if (original !== undefined) value.cause = original;
    return value;
  }
  const unsupported = (name, possible = false) => error('ERR_LSF_UNSUPPORTED_OPERATION', name, undefined, 0, possible);
  function object(value, allowed) {
    if (value === null || typeof value !== 'object' || Array.isArray(value) ||
        Object.keys(value).some(name => !allowed.includes(name))) throw error('ERR_INVALID_ARG_VALUE', 'options');
    return value;
  }
  function destination(args) {
    let options, listener;
    if (args[0] !== null && typeof args[0] === 'object') {
      options = object(args[0], ['host', 'port']); listener = args[1];
      if (args.length > 2) throw error('ERR_INVALID_ARG_VALUE', 'connect');
    } else {
      if (args.length > 3) throw error('ERR_INVALID_ARG_VALUE', 'connect');
      options = {port: args[0], host: typeof args[1] === 'string' ? args[1] : undefined};
      listener = typeof args[1] === 'function' ? args[1] : args[2];
    }
    let port = options.port;
    if (typeof port === 'string' && /^[1-9][0-9]{0,4}$/.test(port)) port = Number(port);
    if (!Number.isInteger(port) || port < 1 || port > 65535 ||
        listener !== undefined && typeof listener !== 'function') throw error('ERR_INVALID_ARG_VALUE', 'connect');
    const host = options.host === undefined ? 'localhost' : options.host;
    if (typeof host !== 'string' || !host.length || host.length > 253 ||
        /[^a-zA-Z0-9.:-]/.test(host)) throw error('ERR_INVALID_ARG_VALUE', 'connect');
    return [{host: host.toLowerCase(), port, transport: 'tcp', timeoutMillis: undefined}, listener];
  }
  function copyBytes(data, encoding) {
    if (typeof data === 'string') {
      if (data.length > windowBytes) throw error('ERR_OUT_OF_RANGE', 'write');
      return Buffer.from(data, encoding);
    }
    if (!(data instanceof target.Uint8Array) || data.byteLength > maxQueuedBytes || encoding !== undefined)
      throw error('ERR_INVALID_ARG_TYPE', 'write');
    return Buffer.from(data);
  }
  class Socket {
    #token; #listeners = new Map(); #writes = []; #dataAdmission;
    #endCallbacks; #nextEndCallback = 0; #endFailureQueued = false; #endWriteGate;
    #invalidEndCallbacks; #nextInvalidEndCallback = 0; #invalidEndError;
    #invalidEndQueued = false; #invalidEndAdmitted = false;
    #readBusy = false; #writeBusy = false; #connectBusy = false; #chunk;
    #progressing = false; #stopReady = false; #stopUncertain = false; #closeStarted = false; #nativeClosed = false;
    #cleanupFailed = false; #notificationQueued = false; #notificationDone = false;
    #connecting = false; #connected = false; #destroyed = false; #closed = false;
    #ending = false; #finished = false; #eof = false; #flowing = false; #buffered;
    #needDrain = false; #error; #bytesRead = 0; #bytesWritten = 0; #queued = 0;
    #halfOpen = false; #highWaterMark = windowBytes;
    #timeout; #timer; #remotePort; #writeAttempted = false;
    constructor(options = {}) {
      object(options, ['allowHalfOpen', 'highWaterMark']);
      if (options.allowHalfOpen !== undefined && typeof options.allowHalfOpen !== 'boolean' ||
          options.highWaterMark !== undefined && (!Number.isInteger(options.highWaterMark) ||
          options.highWaterMark < 1 || options.highWaterMark > windowBytes))
        throw error('ERR_INVALID_ARG_VALUE', 'Socket');
      this.#halfOpen = options.allowHalfOpen ?? false;
      this.#highWaterMark = options.highWaterMark ?? windowBytes;
    }
    #emit(name, ...args) {
      const rows = this.#listeners.get(name);
      if (!rows?.length) { if (name === 'error') throw args[0]; return false; }
      const held = this.#token && !this.#notificationDone;
      if (held) transport.enterTail(this.#token);
      try {
        for (const row of rows.slice()) {
          // false = persistent, true = pending once, null = consumed once.
          // Nested emit can consume a row still held by this snapshot. Remove
          // this registration, not the last registration of the same function;
          // a replacement array/listener installed during emit must survive.
          if (row.once === null) continue;
          if (row.once) {
            row.once = null;
            const index = rows.indexOf(row);
            if (index >= 0) rows.splice(index, 1);
          }
          Reflect.apply(row.listener, this, args);
        }
        return true;
      } finally {
        // A synchronous emit error caught by the application is not poison.
        if (held) transport.leaveTail(this.#token);
      }
    }
    #user(callback, args) {
      const held = this.#token && !this.#notificationDone;
      if (held) transport.enterTail(this.#token);
      try { return Reflect.apply(callback, undefined, args); }
      finally { if (held) transport.leaveTail(this.#token); }
    }
    #owned(callback) {
      const held = this.#token && !this.#notificationDone;
      if (held) transport.enterTail(this.#token);
      try { return Reflect.apply(callback, this, []); }
      catch (cause) { if (held) transport.poison(this.#token, cause); throw cause; }
      finally { if (held) transport.leaveTail(this.#token); }
    }
    #queuedUser(callback, args, writeRecord) {
      const held = this.#token && !this.#notificationDone;
      if (held) transport.enterTail(this.#token);
      try {
        queue(() => {
          try { this.#user(callback, args); }
          catch (cause) { if (held) transport.poison(this.#token, cause); throw cause; }
          finally {
            if (writeRecord) --queuedRecords;
            if (held) transport.leaveTail(this.#token);
          }
        });
      } catch (cause) { if (held) transport.poison(this.#token, cause); throw cause; }
    }
    #retainEndCallback(callback, invalid) {
      if (queuedRecords >= maxQueuedRecords) throw error('ERR_LSF_RESOURCE_EXHAUSTED', 'end');
      const record = {callback};
      // The reservation precedes publication in either callback list. If
      // allocation fails with uncertain mutation, retain it and fence the
      // original socket instead of admitting another record on that basis.
      ++queuedRecords;
      try {
        if (invalid) (this.#invalidEndCallbacks ??= []).push(record);
        else (this.#endCallbacks ??= []).push(record);
      } catch (cause) {
        if (this.#token) transport.poison(this.#token, cause);
        throw cause;
      }
      return record;
    }
    #rollbackEndCallback(record) {
      const callbacks = this.#endCallbacks;
      if (!callbacks) return false;
      for (let index = this.#nextEndCallback; index < callbacks.length; ++index) {
        if (callbacks[index] !== record) continue;
        for (let next = index + 1; next < callbacks.length; ++next) callbacks[next - 1] = callbacks[next];
        --callbacks.length; --queuedRecords;
        return true;
      }
      return false;
    }
    #deliverEndCallbacks(cause) {
      const callbacks = this.#endCallbacks;
      if (!callbacks) return;
      const end = callbacks.length, args = [cause];
      while (this.#nextEndCallback < end) {
        const index = this.#nextEndCallback;
        this.#user(callbacks[index].callback, args);
        callbacks[index] = undefined; this.#nextEndCallback = index + 1;
        --queuedRecords;
      }
      if (this.#nextEndCallback === callbacks.length) {
        this.#endCallbacks = undefined; this.#nextEndCallback = 0;
      }
    }
    #queueFailedEndCallbacks() {
      if (!this.#endCallbacks || this.#nextEndCallback === this.#endCallbacks.length ||
          this.#endFailureQueued) return;
      this.#endFailureQueued = true;
      const cause = this.#error ?? error('ERR_STREAM_DESTROYED', 'write');
      // A single job retains the original socket tail through every callback.
      // If scheduling is uncertain, leave both the list and tail quarantined.
      let admitted = false;
      this.#queuedUser(() => { if (admitted && !this.#stopUncertain) this.#deliverEndCallbacks(cause); }, [], false);
      admitted = true;
    }
    #deliverInvalidEndCallbacks() {
      const callbacks = this.#invalidEndCallbacks;
      if (!callbacks) return;
      const args = [this.#error ?? this.#invalidEndError];
      while (this.#nextInvalidEndCallback < callbacks.length) {
        const index = this.#nextInvalidEndCallback;
        this.#user(callbacks[index].callback, args);
        callbacks[index] = undefined; this.#nextInvalidEndCallback = index + 1;
        --queuedRecords;
      }
      this.#invalidEndCallbacks = undefined; this.#nextInvalidEndCallback = 0;
    }
    on(name, listener) { return this.#add(name, listener, false); }
    addListener(name, listener) { return this.on(name, listener); }
    once(name, listener) { return this.#add(name, listener, true); }
    #add(name, listener, once) {
      if (!['connect', 'ready', 'data', 'drain', 'end', 'finish', 'error', 'close', 'timeout'].includes(name) ||
          typeof listener !== 'function') throw error('ERR_INVALID_ARG_VALUE', 'listener');
      const rows = this.#listeners.get(name) || [];
      const row = name === 'data'
        ? {listener, once, admissionFailed: false, admissionFault: undefined}
        : {listener, once};
      rows.push(row); this.#listeners.set(name, rows);
      if (name === 'data') {
        const previous = this.#dataAdmission;
        this.#dataAdmission = row;
        try { this.resume(); }
        catch (cause) {
          if (row.admissionFailed && sameValue(row.admissionFault, cause)) {
            // Only the built-in resume admission can be rolled back here.
            // Preserve reentrant replacements and avoid allocating in refusal.
            // A now-empty private array may remain as this socket's state.
            for (let index = 0; index < rows.length; ++index) {
              if (rows[index] !== row) continue;
              for (let next = index + 1; next < rows.length; ++next) rows[next - 1] = rows[next];
              --rows.length;
              break;
            }
          }
          throw cause;
        } finally {
          this.#dataAdmission = previous;
          row.admissionFailed = false; row.admissionFault = undefined;
        }
      }
      return this;
    }
    off(name, listener) { return this.removeListener(name, listener); }
    removeListener(name, listener) {
      const rows = this.#listeners.get(name);
      if (rows) { const index = rows.findLastIndex(row => row.listener === listener); if (index >= 0) rows.splice(index, 1); }
      return this;
    }
    removeAllListeners(name) {
      if (name === undefined) this.#listeners.clear(); else this.#listeners.delete(name);
      return this;
    }
    listenerCount(name) { return this.#listeners.get(name)?.length || 0; }
    emit(name, ...args) { return this.#emit(name, ...args); }
    #prepareConnect(listener) {
      this.#touch();
      if (listener) this.once('connect', listener);
      if (this.#destroyed) throw error('ERR_SOCKET_CLOSED', 'connect');
    }
    connect(...args) {
      if (snapshotActive()) throw error('ERR_LSF_SNAPSHOT_EFFECT', 'connect');
      if (this.#token || this.#connecting || this.#connected || this.#destroyed)
        throw error('ERR_SOCKET_CLOSED', 'connect');
      const [request, listener] = destination(args);
      this.#connecting = true;
      try { this.#token = transport.reserve(this.#afterTail, this, this.#prepareConnect, listener); }
      catch (cause) { this.#connecting = false; throw cause; }
      this.#connectBusy = true; this.#remotePort = request.port;
      let failed = false, cause;
      try { transport.connect(this.#token, request, this.#onConnect, this); }
      catch (value) { failed = true; cause = value; }
      if (failed) { this.#connectBusy = false; this.destroy(error('ERR_LSF_CONNECT_FAILED', 'connect', cause)); }
      return this;
    }
    #onConnect(record) {
      this.#connectBusy = false;
      if (record.borrowFailed || record.logicalFailed) {
        if (!this.#destroyed) this.destroy(error('ERR_LSF_CONNECT_FAILED', 'connect',
          record.borrowFailed ? record.borrowFault : record.logicalFault));
        return;
      }
      if (this.#destroyed) return;
      this.#connecting = false; this.#connected = true; this.#touch();
      // Outside all native translators. The join retains this entire tail.
      this.#emit('connect'); this.#emit('ready');
    }
    #touch() {
      if (this.#timer !== undefined) {
        const previous = this.#timer; this.#timer = undefined; clearTimer(previous);
      }
      if (this.#timeout && !this.#destroyed) {
        // Activation timer ids are not reused. An already selected callback
        // from a cleared/replaced timer must not consume the new timer's slot.
        const timer = setTimer(() => {
          if (this.#timer === timer) this.#owned(this.#onTimeout);
        }, this.#timeout);
        this.#timer = timer;
      }
    }
    #onTimeout() {
      this.#timer = undefined; if (!this.#destroyed) this.#emit('timeout');
    }
    setTimeout(milliseconds, callback) {
      if (this.#destroyed) return this;
      if (!Number.isInteger(milliseconds) || milliseconds < 0 || milliseconds > 2147483647 ||
          callback !== undefined && typeof callback !== 'function') throw error('ERR_INVALID_ARG_VALUE', 'setTimeout');
      if (milliseconds && snapshotActive()) throw error('ERR_LSF_SNAPSHOT_EFFECT', 'setTimeout');
      this.#timeout = milliseconds;
      // Socket idle notification applies before and during connect as well.
      // Do not publish a supplied callback if timer admission refuses.
      this.#touch();
      if (callback) {
        if (milliseconds) this.once('timeout', callback);
        else this.removeListener('timeout', callback);
      }
      return this;
    }
    pause() { this.#flowing = false; return this; }
    resume() {
      // A callback retained by an enqueue-then-throw implementation remains
      // on its original queue but must not act after this call was refused.
      let admitted = false;
      try { queue(() => { if (admitted) this.#owned(this.#onResume); }); }
      catch (cause) {
        if (this.#dataAdmission) {
          this.#dataAdmission.admissionFailed = true;
          this.#dataAdmission.admissionFault = cause;
        }
        throw cause;
      }
      if (this.#dataAdmission) {
        this.#dataAdmission.admissionFailed = false;
        this.#dataAdmission.admissionFault = undefined;
      }
      this.#flowing = true; admitted = true;
      return this;
    }
    #onResume() {
      if (this.#destroyed || !this.#flowing) return;
      if (this.#buffered !== undefined) { const bytes = this.#buffered; this.#buffered = undefined; this.#emit('data', bytes); }
      this.#progress();
    }
    #pumpReads() {
      if (this.#readBusy || !this.#connected || this.#eof || this.#destroyed) return;
      // Keep at most one completed window while paused. Even if resume has
      // already been requested, its queued delivery must precede another read.
      if (this.#buffered !== undefined) return;
      if (!this.#flowing && !(this.#ending && this.#finished)) return;
      this.#readBusy = true;
      let failed = false, cause;
      try { transport.read(this.#token, windowBytes, undefined, this.#onRead, this); }
      catch (value) { failed = true; cause = value; }
      if (failed) { this.#readBusy = false; this.destroy(error('EIO', 'read', cause, 0, this.#writeAttempted)); }
    }
    #onRead(record) {
      if (record.borrowFailed || record.logicalFailed) {
        this.#readBusy = false;
        if (!this.#destroyed) this.destroy(error('EIO', 'read',
          record.borrowFailed ? record.borrowFault : record.logicalFault, 0, this.#writeAttempted));
        return;
      }
      const chunk = record.value;
      if (chunk === undefined) {
        this.#readBusy = false;
        if (this.#destroyed) return;
        this.#eof = true; this.#emit('end');
        if (!this.#halfOpen && !this.#ending && !this.#destroyed) this.end();
        this.#maybeClose(); return;
      }
      this.#chunk = chunk;
      if (this.#destroyed) {
        transport.disposeChunk(this.#token, chunk); this.#chunk = undefined; this.#readBusy = false; return;
      }
      let failed = false, cause;
      // The completed read tail plus copy plus sibling write stay within three.
      try { transport.chunkBytes(this.#token, chunk, this.#onCopy, this); }
      catch (value) { failed = true; cause = value; }
      if (failed) {
        try { transport.disposeChunk(this.#token, chunk); this.#chunk = undefined; }
        catch (value) { cause = value; }
        this.#readBusy = false; this.destroy(error('EIO', 'read', cause, 0, this.#writeAttempted));
      }
    }
    #onCopy(record) {
      let failed = record.borrowFailed || record.logicalFailed;
      let cause = record.borrowFailed ? record.borrowFault : record.logicalFault, copy;
      if (!failed) {
        try { copy = Buffer.from(record.value); } // Actual ACK, then owned copy.
        catch (value) { failed = true; cause = value; }
      }
      if (!record.borrowFailed) {
        try { transport.disposeChunk(this.#token, this.#chunk); this.#chunk = undefined; }
        catch (value) { failed = true; cause = value; }
      }
      this.#readBusy = false;
      if (failed) {
        if (!this.#destroyed) this.destroy(error('EIO', 'read', cause, 0, this.#writeAttempted));
        return;
      }
      if (this.#destroyed) return;
      if (copy.length === 0) { this.destroy(error('ERR_LSF_ZERO_READ', 'read')); return; }
      this.#bytesRead += copy.length; this.#touch();
      if (this.#flowing) this.#emit('data', copy); else this.#buffered = copy;
      // The after-tail hook, not a worker await/loop, starts the next read.
    }
    write(data, encoding, callback) {
      if (typeof encoding === 'function') { callback = encoding; encoding = undefined; }
      if (callback !== undefined && typeof callback !== 'function') throw error('ERR_INVALID_ARG_TYPE', 'write');
      if (!this.#token || this.#destroyed || this.#ending) {
        const cause = error(this.#ending ? 'ERR_STREAM_WRITE_AFTER_END' : 'ERR_SOCKET_CLOSED', 'write');
        queue(() => { if (callback) callback(cause); this.destroy(cause); }); return false;
      }
      if (queuedRecords >= maxQueuedRecords) throw error('ERR_LSF_RESOURCE_EXHAUSTED', 'write');
      const bytes = copyBytes(data, encoding);
      if (bytes.length > maxQueuedBytes - queuedBytes) throw error('ERR_LSF_RESOURCE_EXHAUSTED', 'write');
      const record = {bytes, callback, offset: 0, maximum: 0, needsReady: false};
      if (this.#endWriteGate) this.#endWriteGate.started = true;
      // Reserve before a possibly uncertain list mutation. A thrown insertion
      // retains the original record/bytes and fences subsequent socket work.
      ++queuedRecords; queuedBytes += bytes.length; this.#queued += bytes.length;
      try { this.#writes.push(record); }
      catch (cause) { if (this.#token) transport.poison(this.#token, cause); throw cause; }
      const accepted = this.#queued < this.#highWaterMark;
      if (!accepted) this.#needDrain = true;
      this.#progress(); return accepted;
    }
    #removeWrite(item) {
      if (this.#writes[0] !== item) throw error('ERR_LSF_WRITE_RECORD', 'write');
      this.#writes.shift(); queuedBytes -= item.bytes.length; this.#queued -= item.bytes.length;
    }
    #finishWrite(item, failed, cause) {
      if (failed && !cause) {
        const native = cause;
        cause = error('EIO', 'write', native, item.offset, true); cause.cause = native;
      }
      this.#removeWrite(item);
      if (failed || item.bytes.length === 0) {
        if (item.callback) this.#queuedUser(item.callback, failed ? [cause] : [], true);
        else --queuedRecords;
      } else {
        --queuedRecords;
        // Node emits drain before the callback that emptied a backpressured
        // write buffer. The current native result and borrow ACK still own this
        // entire callback tail, including reentrant writes or destruction.
        if (this.#queued === 0 && this.#needDrain && !this.#ending) {
          // Empty writes already accepted behind this write have completed
          // too. Retain their callback jobs before a drain listener can destroy
          // the socket; they must not be flushed as failed pending writes.
          while (this.#writes.length && this.#writes[0].bytes.length === 0)
            this.#finishWrite(this.#writes[0], false);
          this.#needDrain = false; this.#emit('drain');
        }
        if (item.callback) this.#user(item.callback, []);
      }
      if (failed) this.destroy(cause);
    }
    #pumpWrites() {
      if (this.#writeBusy || !this.#connected || this.#destroyed) return;
      // Only the finite queued zero-byte records can complete synchronously.
      // Their callbacks retain their record/tail until the existing job returns.
      while (this.#writes.length && this.#writes[0].bytes.length === 0) {
        this.#finishWrite(this.#writes[0], false);
        if (this.#destroyed) return;
      }
      if (!this.#writes.length && this.#needDrain) {
        // Ended streams do not emit a late drain for prior backpressure.
        this.#needDrain = false;
        if (!this.#ending) this.#emit('drain');
        if (this.#destroyed) return;
        // A drain listener may enqueue/end. Its tail has now returned.
        while (this.#writes.length && this.#writes[0].bytes.length === 0)
          this.#finishWrite(this.#writes[0], false);
      }
      if (!this.#writes.length) {
        if (this.#ending && !this.#finished) {
          this.#writeBusy = true; let failed = false, cause;
          try { transport.shutdown(this.#token, this.#onShutdown, this); }
          catch (value) { failed = true; cause = value; }
          if (failed) { this.#writeBusy = false; this.destroy(error('EIO', 'shutdown', cause)); }
        }
        return;
      }
      const item = this.#writes[0]; this.#writeBusy = true;
      let failed = false, cause;
      try {
        if (item.needsReady) transport.ready(this.#token, this.#onReady, this);
        else {
          const portion = item.bytes.subarray(item.offset, Math.min(item.offset + windowBytes, item.bytes.length));
          item.maximum = portion.length; this.#writeAttempted = true;
          transport.write(this.#token, portion, undefined, this.#onWrite, this);
        }
      } catch (value) { failed = true; cause = value; }
      if (failed) { this.#writeBusy = false; this.#finishWrite(item, true, cause); }
    }
    #onWrite(record) {
      const item = this.#writes[0]; this.#writeBusy = false;
      if (!item) throw error('ERR_LSF_WRITE_RECORD', 'write');
      let failed = record.logicalFailed, cause;
      if (record.logicalFailed) {
        const native = record.logicalFault;
        if (native?.payload && (!Number.isInteger(native.payload.acceptedPrefixBytes) ||
            native.payload.acceptedPrefixBytes < 0 || native.payload.acceptedPrefixBytes > item.maximum)) {
          cause = error('ERR_LSF_INVALID_WRITE_ERROR', 'write', undefined, item.offset, true); cause.cause = native;
        } else {
          cause = error('EIO', 'write', native, item.offset, true);
          this.#bytesWritten += cause.acceptedPrefixBytes - item.offset;
        }
      } else if (!record.borrowFailed) {
        const count = record.value;
        if (!Number.isInteger(count) || count < 0 || count > item.maximum) {
          failed = true; cause = error('ERR_LSF_INVALID_WRITE_COUNT', 'write', undefined, item.offset, true);
        } else if (count === 0) item.needsReady = true;
        else { item.offset += count; this.#bytesWritten += count; this.#touch(); }
      }
      if (record.borrowFailed) {
        // Explicit failure survives even reject(undefined). finishWrite wraps
        // only falsey values; nonfalsey native ACK fault identity stays original.
        failed = true; cause = record.borrowFault;
      }
      if (this.#destroyed) return; // Destroy owns pending callback completion.
      if (failed) { this.#finishWrite(item, true, cause); return; }
      if (item.offset === item.bytes.length) this.#finishWrite(item, false);
    }
    #onReady(record) {
      this.#writeBusy = false;
      if (this.#destroyed) return;
      const item = this.#writes[0];
      if (!item) throw error('ERR_LSF_WRITE_RECORD', 'write');
      if (record.borrowFailed || record.logicalFailed) {
        this.#finishWrite(item, true, record.borrowFailed ? record.borrowFault : record.logicalFault); return;
      }
      if (!record.value || record.value.writable !== true) {
        this.#finishWrite(item, true, error('ERR_LSF_NOT_WRITABLE', 'write')); return;
      }
      item.needsReady = false;
    }
    #onShutdown(record) {
      this.#writeBusy = false;
      if (record.borrowFailed || record.logicalFailed) {
        if (!this.#destroyed) this.destroy(error('EIO', 'shutdown',
          record.borrowFailed ? record.borrowFault : record.logicalFault));
        return;
      }
      if (this.#destroyed) return;
      this.#finished = true; this.#deliverEndCallbacks(null);
      this.#emit('finish'); this.#maybeClose();
    }
    end(data, encoding, callback) {
      if (typeof data === 'function') { callback = data; data = undefined; encoding = undefined; }
      else if (typeof encoding === 'function') { callback = encoding; encoding = undefined; }
      if (data === null) data = undefined;
      if (!this.#token || this.#destroyed) throw error('ERR_SOCKET_CLOSED', 'end');
      if (callback !== undefined && typeof callback !== 'function') throw error('ERR_INVALID_ARG_VALUE', 'listener');
      if (this.#ending && data !== undefined) {
        const failure = this.#invalidEndError ?? error('ERR_STREAM_WRITE_AFTER_END', 'write');
        if (callback) this.#retainEndCallback(callback, true);
        this.#invalidEndError = failure;
        if (!this.#invalidEndQueued) {
          let admitted = false;
          const fail = () => { if (admitted) this.destroy(this.#invalidEndError); }, args = [];
          this.#invalidEndQueued = true;
          // Keep the original socket alive until this error job returns.
          // There is no network write or replay for an already-ended socket.
          this.#queuedUser(fail, args, false);
          admitted = true; this.#invalidEndAdmitted = true;
        }
        return this;
      }
      if (this.#finished && data === undefined) {
        if (callback) {
          if (queuedRecords >= maxQueuedRecords) throw error('ERR_LSF_RESOURCE_EXHAUSTED', 'end');
          const failure = error('ERR_STREAM_ALREADY_FINISHED', 'end'), args = [failure];
          let admitted = false;
          const notify = value => {
            if (admitted) { Reflect.apply(callback, undefined, [value]); --queuedRecords; }
          };
          ++queuedRecords;
          this.#queuedUser(notify, args, false);
          admitted = true;
        }
        return this;
      }
      // A data-bearing end needs one record for the write as well as its
      // callback; refuse before publishing either when only one slot remains.
      if (callback && data !== undefined && queuedRecords >= maxQueuedRecords - 1)
        throw error('ERR_LSF_RESOURCE_EXHAUSTED', 'end');
      if (callback && data !== undefined) {
        const writer = this.write, gate = {started: false};
        const record = this.#retainEndCallback(callback, false);
        let held = false, failed = false, failure;
        try {
          // Keep existing work from progressing until the new end callback is
          // either accepted or a definite pre-write refusal is rolled back.
          transport.enterTail(this.#token); held = true;
          const previous = this.#endWriteGate; this.#endWriteGate = gate;
          try { Reflect.apply(writer, this, [data, encoding]); }
          finally { this.#endWriteGate = previous; }
          this.#ending = true; transport.acceptTerminal(this.#token);
        } catch (cause) {
          failed = true; failure = cause;
          if (!held || !gate.started && (writer === originalSocketWrite || typeof writer !== 'function')) {
            // The built-in write failed before it began publishing a record.
            // Only this exact callback's reservation can be rolled back.
            let rolledBack = false;
            try { rolledBack = this.#rollbackEndCallback(record); }
            catch { /* A partial rollback cannot certify release. */ }
            if (!rolledBack) {
              try { transport.poison(this.#token, cause); } catch { /* Preserve the original failure. */ }
            }
          } else {
            // An overridden writer or a started insertion cannot prove that no
            // write was accepted. Retain the callback and its original owner.
            try { transport.poison(this.#token, cause); } catch { /* Preserve the original failure. */ }
          }
        } finally {
          if (held) {
            try { transport.leaveTail(this.#token); }
            catch (cause) {
              if (!failed) { failed = true; failure = cause; }
              else { try { transport.poison(this.#token, cause); } catch { /* Preserve the original failure. */ } }
            }
          }
        }
        if (failed) throw failure;
        return this;
      }
      if (callback) this.#retainEndCallback(callback, false);
      if (data !== undefined) this.write(data, encoding);
      this.#ending = true; transport.acceptTerminal(this.#token); this.#progress(); return this;
    }
    #maybeClose() {
      // An admitted write-after-end error already owns the next terminal turn;
      // EOF must not turn it into a successful close before that job runs.
      if (this.#eof && this.#finished && !this.#destroyed && !this.#invalidEndQueued) this.destroy();
    }
    #afterTail() { this.#progress(true); }
    #progress(afterTail = false) {
      if (this.#progressing || this.#notificationDone ||
          !afterTail && this.#token && !transport.canProgress(this.#token)) return;
      this.#progressing = true;
      try {
        if (this.#destroyed) {
          if (this.#stopReady && !this.#closeStarted && !this.#cleanupFailed) {
            this.#closeStarted = true; let failed = false, cause;
            try { transport.close(this.#token, this.#onClose, this); }
            catch (value) { failed = true; cause = value; }
            if (failed) this.#cleanupFailure(cause);
          }
          if (this.#nativeClosed || this.#cleanupFailed) this.#notifyClose();
          return;
        }
        this.#pumpWrites(); this.#pumpReads();
      } finally { this.#progressing = false; }
    }
    #flushWrites() {
      const pending = this.#writes.splice(0);
      for (const item of pending) {
        queuedBytes -= item.bytes.length; this.#queued -= item.bytes.length;
        if (item.callback) this.#queuedUser(item.callback,
          [this.#error || error('ERR_STREAM_DESTROYED', 'write')], true);
        else --queuedRecords;
      }
      this.#buffered = undefined;
    }
    #cleanupFailure(cause) {
      this.#cleanupFailed = true;
      this.#error ||= error('ERR_LSF_CLEANUP_FAILED', 'close', cause, 0, this.#writeAttempted);
    }
    #onStopped(result) {
      if (result.failed) this.#cleanupFailure(result.fault);
      else this.#stopReady = true;
      this.#flushWrites();
      this.#queueFailedEndCallbacks();
      // Its queued callbacks/tails precede consuming close. The transport's
      // fixed after-tail hook resumes, without a worker Promise or queued pump.
    }
    #onClose(record) {
      if (record.borrowFailed || record.logicalFailed) this.#cleanupFailure(
        record.borrowFailed ? record.borrowFault : record.logicalFault);
      else { this.#nativeClosed = true; this.#closed = true; }
    }
    #notifyClose() {
      if (this.#notificationQueued) return;
      this.#notificationQueued = true;
      queue(() => {
        // A stop throw may arrive after this job was queued. It cannot certify
        // that earlier cleanup actually completed; retain the notification.
        if (this.#stopUncertain) return;
        try {
          if (this.#error) this.#emit('error', this.#error);
          this.#deliverInvalidEndCallbacks();
          this.#emit('close', this.#error !== undefined);
        } catch (cause) { if (this.#token) transport.poison(this.#token, cause); throw cause; }
        finally {
          if (this.#token) transport.finishNotification(this.#token);
          this.#notificationDone = true;
        }
      });
    }
    destroy(cause) {
      if (this.#destroyed) return this;
      this.#destroyed = true; this.#connected = false; this.#connecting = false;
      this.#error = this.#invalidEndAdmitted ? this.#invalidEndError : cause;
      if (this.#timer !== undefined) {
        const previous = this.#timer; this.#timer = undefined; clearTimer(previous);
      }
      if (!this.#token) { this.#closed = true; this.#notifyClose(); return this; }
      transport.acceptTerminal(this.#token);
      transport.holdNotification(this.#token);
      let failed = false, failure;
      try { transport.stop(this.#token, this.#onStopped, this); }
      catch (value) { failed = true; failure = value; }
      if (failed) {
        // A synchronous throw does not prove whether stop or cancellation was
        // accepted. Keep every original write and callback owned; do not report
        // close or retry cleanup on the strength of an uncertain observation.
        // The existing root check exposes this exact fault and keeps the slot.
        this.#stopUncertain = true;
        try { transport.poison(this.#token, failure); }
        catch { throw failure; }
      }
      return this;
    }
    get connecting() { return this.#connecting; }
    get pending() { return !this.#connected; }
    get destroyed() { return this.#destroyed; }
    get closed() { return this.#destroyed; }
    get readable() { return !this.#destroyed && !this.#eof; }
    get writable() { return !this.#destroyed && !this.#ending; }
    get readableEnded() { return this.#eof; }
    get writableEnded() { return this.#ending; }
    get writableFinished() { return this.#finished; }
    get writableLength() { return this.#queued; }
    get writableHighWaterMark() { return this.#highWaterMark; }
    get bytesRead() { return this.#bytesRead; }
    get bytesWritten() { return this.#bytesWritten; }
    get timeout() { return this.#timeout; }
    get remotePort() { return this.#connected ? this.#remotePort : undefined; }
    get readyState() { return this.#connecting ? 'opening' : this.readable ?
      (this.writable ? 'open' : 'readOnly') : (this.writable ? 'writeOnly' : 'closed'); }
    address() { throw unsupported('address'); }
    setEncoding() { throw unsupported('setEncoding'); }
    setNoDelay() { throw unsupported('setNoDelay'); }
    setKeepAlive() { throw unsupported('setKeepAlive'); }
    ref() { throw unsupported('ref'); }
    unref() { throw unsupported('unref'); }
    pipe() { throw unsupported('pipe'); }
  }
  const originalSocketWrite = Socket.prototype.write;
  function createConnection(...args) { return new Socket().connect(...args); }
  return Object.freeze({Socket, createConnection, connect: createConnection,
    createServer() { throw unsupported('createServer'); }});
}
