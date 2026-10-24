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
    #token; #listeners = new Map(); #writes = []; #writeTask; #readTask; #connectTask; #destroyTask;
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
      for (const row of rows.slice()) {
        if (row.once) this.removeListener(name, row.listener);
        Reflect.apply(row.listener, this, args);
      }
      return true;
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
      this.#token = transport.reserve(); // Finite port reservation BEFORE CAP connect.
      this.#connecting = true; this.#remotePort = request.port;
      const operation = transport.connect(this.#token, request);
      this.#connectTask = (async () => {
        try { await operation.promise; await operation.borrowReleased; }
        catch (cause) { if (!this.#destroyed) this.destroy(error('ERR_LSF_CONNECT_FAILED', 'connect', cause)); return; }
        if (this.#destroyed) return;
        this.#connecting = false; this.#connected = true; this.#touch();
        // User callbacks execute outside native-error translation. A thrown
        // callback remains its original unhandled failure, never a fake I/O error.
        this.#emit('connect'); this.#emit('ready');
        this.#pumpWrites(); this.#pumpReads();
      })();
      return this;
    }
    #touch() {
      if (this.#timer !== undefined) { clearTimer(this.#timer); this.#timer = undefined; }
      if (this.#timeout && !this.#destroyed) this.#timer = setTimer(() => {
        this.#timer = undefined; if (!this.#destroyed) this.#emit('timeout');
      }, this.#timeout);
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
      queue(() => {
        if (this.#destroyed || !this.#flowing) return;
        if (this.#buffered !== undefined) { const bytes = this.#buffered; this.#buffered = undefined; this.#emit('data', bytes); }
        this.#pumpReads();
      });
      return this;
    }
    #pumpReads() {
      if (this.#readTask || !this.#connected || !this.#flowing || this.#eof || this.#destroyed) return;
      this.#readTask = (async () => {
        try {
          while (this.#flowing && !this.#destroyed && !this.#eof) {
            let chunk, copy, copied;
            try {
              const operation = transport.read(this.#token, windowBytes, undefined);
              try {
                chunk = await operation.promise; await operation.borrowReleased;
                if (chunk !== undefined && !this.#destroyed) {
                  copied = transport.chunkBytes(this.#token, chunk);
                  const raw = await copied.promise; await copied.borrowReleased;
                  copy = Buffer.from(raw); // Copy BEFORE owned chunk disposal.
                }
              } finally {
                await operation.borrowReleased;
                if (copied) await copied.borrowReleased;
                if (chunk !== undefined) transport.disposeChunk(this.#token, chunk);
              }
            } catch (cause) {
              if (!this.#destroyed) this.destroy(error('EIO', 'read', cause, 0, this.#writeAttempted));
              return;
            }
            if (this.#destroyed) break;
            if (chunk === undefined) {
              this.#eof = true; this.#emit('end');
              if (!this.#halfOpen && !this.#ending) this.end();
              break;
            }
            if (copy.length === 0) { this.destroy(error('ERR_LSF_ZERO_READ', 'read')); return; }
            this.#bytesRead += copy.length; this.#touch();
            if (this.#flowing) this.#emit('data', copy); else this.#buffered = copy;
          }
        } finally { this.#readTask = undefined; this.#maybeClose(); }
      })();
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
      this.#writes.push({bytes, callback}); ++queuedRecords; queuedBytes += bytes.length; this.#queued += bytes.length;
      const accepted = this.#queued < this.#highWaterMark;
      if (!accepted) this.#needDrain = true;
      this.#pumpWrites(); return accepted;
    }
    #pumpWrites() {
      if (this.#writeTask || !this.#connected || this.#destroyed || !this.#writes.length && !this.#ending) return;
      // The empty-write path may finish synchronously. Do not overwrite its
      // finally with an already-completed Promise and permanently latch the pump.
      this.#writeTask = true;
      const worker = (async () => {
        try {
          while (this.#writes.length && !this.#destroyed) {
            const item = this.#writes[0]; let offset = 0, failed;
            try {
              while (offset < item.bytes.length && !this.#destroyed) {
                const portion = item.bytes.subarray(offset, Math.min(offset + windowBytes, item.bytes.length));
                this.#writeAttempted = true;
                const operation = transport.write(this.#token, portion, undefined);
                let count;
                try { count = await operation.promise; }
                catch (cause) {
                  if (cause?.payload && (!Number.isInteger(cause.payload.acceptedPrefixBytes) ||
                      cause.payload.acceptedPrefixBytes < 0 || cause.payload.acceptedPrefixBytes > portion.length))
                    {
                      const failure = error('ERR_LSF_INVALID_WRITE_ERROR', 'write', undefined, offset, true);
                      failure.cause = cause; throw failure;
                    }
                  const failure = error('EIO', 'write', cause, offset, true);
                  this.#bytesWritten += failure.acceptedPrefixBytes - offset;
                  throw failure;
                }
                finally { await operation.borrowReleased; }
                if (!Number.isInteger(count) || count < 0 || count > portion.length)
                  throw error('ERR_LSF_INVALID_WRITE_COUNT', 'write', undefined, offset, true);
                if (count === 0) {
                  const ready = transport.ready(this.#token);
                  let hint;
                  try { hint = await ready.promise; } finally { await ready.borrowReleased; }
                  if (!hint || hint.writable !== true) throw error('ERR_LSF_NOT_WRITABLE', 'write');
                  continue; // The unaccepted suffix is a fresh charged call, never replayed bytes.
                }
                offset += count; this.#bytesWritten += count; this.#touch();
              }
            } catch (cause) { failed = cause; }
            if (this.#destroyed) break; // Destroy owns the one pending callback.
            this.#writes.shift(); --queuedRecords; queuedBytes -= item.bytes.length; this.#queued -= item.bytes.length;
            if (failed) {
              if (item.callback) queue(() => item.callback(failed));
              this.destroy(failed); return;
            }
            if (item.callback) {
              if (item.bytes.length === 0) queue(() => item.callback());
              else item.callback();
            }
          }
          if (!this.#destroyed && !this.#writes.length) {
            if (this.#needDrain) { this.#needDrain = false; this.#emit('drain'); }
            if (this.#ending && !this.#finished) {
              try {
                const operation = transport.shutdown(this.#token);
                try { await operation.promise; } finally { await operation.borrowReleased; }
              } catch (cause) { this.destroy(error('EIO', 'shutdown', cause)); return; }
              this.#finished = true; this.#emit('finish');
            }
          }
        } finally { this.#writeTask = undefined; this.#maybeClose(); }
      })();
      if (this.#writeTask !== undefined) this.#writeTask = worker;
    }
    end(data, encoding, callback) {
      if (typeof data === 'function') { callback = data; data = undefined; encoding = undefined; }
      else if (typeof encoding === 'function') { callback = encoding; encoding = undefined; }
      if (!this.#token || this.#destroyed) throw error('ERR_SOCKET_CLOSED', 'end');
      if (callback !== undefined) this.once('finish', callback);
      if (data !== undefined) this.write(data, encoding);
      this.#ending = true; this.#pumpWrites(); return this;
    }
    #maybeClose() { if (this.#eof && this.#finished && !this.#destroyed) this.destroy(); }
    destroy(cause) {
      if (this.#destroyed) return this;
      this.#destroyed = true; this.#connected = false; this.#connecting = false; this.#error = cause;
      if (this.#timer !== undefined) { clearTimer(this.#timer); this.#timer = undefined; }
      this.#destroyTask = (async () => {
        try {
          if (this.#token) {
            await transport.stop(this.#token);
            // These actual workers dispose any already-arrived chunk in finally.
            if (this.#connectTask) await this.#connectTask;
            if (this.#readTask) await this.#readTask;
            if (this.#writeTask) await this.#writeTask;
            await transport.close(this.#token);
          }
          this.#closed = true;
        } catch (failure) { this.#error ||= error('ERR_LSF_CLEANUP_FAILED', 'close', failure, 0, this.#writeAttempted); }
        finally {
          const pending = this.#writes.splice(0);
          for (const item of pending) {
            --queuedRecords; queuedBytes -= item.bytes.length; this.#queued -= item.bytes.length;
            if (item.callback) queue(() => item.callback(this.#error || error('ERR_STREAM_DESTROYED', 'write')));
          }
          this.#buffered = undefined;
          queue(() => {
            if (this.#error) this.#emit('error', this.#error);
            this.#emit('close', this.#error !== undefined);
          });
        }
      })();
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
