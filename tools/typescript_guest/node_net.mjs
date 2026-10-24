// Finite ordinary TCP Socket API. The compiler supplies this factory's backend;
// applications select normal imports, never a transport/caller id/resource.
export function createNodeNetModule(transport, Buffer, snapshotActive, target = globalThis) {
  const queue = target.queueMicrotask.bind(target);
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
  const unsupported = name => error('ERR_LSF_UNSUPPORTED_OPERATION', name);
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
    #token; #listeners = new Map(); #writes = [];
    #readBusy = false; #writeBusy = false; #connectBusy = false; #chunk;
    #progressing = false; #stopReady = false; #closeStarted = false; #nativeClosed = false;
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
          if (row.once) this.removeListener(name, row.listener);
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
    on(name, listener) { return this.#add(name, listener, false); }
    addListener(name, listener) { return this.on(name, listener); }
    once(name, listener) { return this.#add(name, listener, true); }
    #add(name, listener, once) {
      if (!['connect', 'ready', 'data', 'drain', 'end', 'finish', 'error', 'close', 'timeout'].includes(name) ||
          typeof listener !== 'function') throw error('ERR_INVALID_ARG_VALUE', 'listener');
      const rows = this.#listeners.get(name) || [];
      rows.push({listener, once}); this.#listeners.set(name, rows);
      if (name === 'data') this.resume();
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
    connect(...args) {
      if (snapshotActive()) throw error('ERR_LSF_SNAPSHOT_EFFECT', 'connect');
      if (this.#token || this.#connecting || this.#connected || this.#destroyed)
        throw error('ERR_SOCKET_CLOSED', 'connect');
      const [request, listener] = destination(args);
      if (listener) this.once('connect', listener);
      this.#token = transport.reserve(this.#afterTail, this); // BEFORE CAP connect.
      this.#connecting = true; this.#connectBusy = true; this.#remotePort = request.port;
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
      if (this.#timer !== undefined) { clearTimer(this.#timer); this.#timer = undefined; }
      if (this.#timeout && !this.#destroyed)
        this.#timer = setTimer(() => this.#owned(this.#onTimeout), this.#timeout);
    }
    #onTimeout() {
      this.#timer = undefined; if (!this.#destroyed) this.#emit('timeout');
    }
    setTimeout(milliseconds, callback) {
      if (!Number.isInteger(milliseconds) || milliseconds < 0 || milliseconds > 2147483647 ||
          callback !== undefined && typeof callback !== 'function') throw error('ERR_INVALID_ARG_VALUE', 'setTimeout');
      if (callback) this.once('timeout', callback);
      this.#timeout = milliseconds;
      if (this.#connected) this.#touch();
      return this;
    }
    pause() { this.#flowing = false; return this; }
    resume() {
      this.#flowing = true;
      queue(() => this.#owned(this.#onResume));
      return this;
    }
    #onResume() {
      if (this.#destroyed || !this.#flowing) return;
      if (this.#buffered !== undefined) { const bytes = this.#buffered; this.#buffered = undefined; this.#emit('data', bytes); }
      this.#progress();
    }
    #pumpReads() {
      if (this.#readBusy || !this.#connected || !this.#flowing || this.#eof || this.#destroyed) return;
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
      this.#writes.push({bytes, callback, offset: 0, maximum: 0, needsReady: false}); ++queuedRecords; queuedBytes += bytes.length; this.#queued += bytes.length;
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
        this.#needDrain = false; this.#emit('drain');
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
      this.#finished = true; this.#emit('finish'); this.#maybeClose();
    }
    end(data, encoding, callback) {
      if (typeof data === 'function') { callback = data; data = undefined; encoding = undefined; }
      else if (typeof encoding === 'function') { callback = encoding; encoding = undefined; }
      if (!this.#token || this.#destroyed) throw error('ERR_SOCKET_CLOSED', 'end');
      if (callback !== undefined) this.once('finish', callback);
      if (data !== undefined) this.write(data, encoding);
      this.#ending = true; this.#progress(); return this;
    }
    #maybeClose() { if (this.#eof && this.#finished && !this.#destroyed) this.destroy(); }
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
        try {
          if (this.#error) this.#emit('error', this.#error);
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
      this.#destroyed = true; this.#connected = false; this.#connecting = false; this.#error = cause;
      if (this.#timer !== undefined) { clearTimer(this.#timer); this.#timer = undefined; }
      if (!this.#token) { this.#closed = true; this.#notifyClose(); return this; }
      transport.holdNotification(this.#token);
      let failed = false, failure;
      try { transport.stop(this.#token, this.#onStopped, this); }
      catch (value) { failed = true; failure = value; }
      if (failed) { this.#cleanupFailure(failure); this.#flushWrites(); this.#progress(); }
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
  function createConnection(...args) { return new Socket().connect(...args); }
  return Object.freeze({Socket, createConnection, connect: createConnection,
    createServer() { throw unsupported('createServer'); }});
}
