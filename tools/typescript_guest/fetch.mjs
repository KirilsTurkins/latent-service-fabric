// Compiler-owned candidate over exact typed streaming HTTP imports. No socket,
// executor, credential or grant is supplied by the application to this module.
export function installFetch(http, snapshotActive, target = globalThis) {
  const maxBody = 1024 * 1024, maxHeaders = 64, maxHeaderBytes = 32768;
  const encoder = new target.TextEncoder(), decoder = new target.TextDecoder();
  const SearchParams = target.URLSearchParams;
  const serializeParams = typeof SearchParams === 'function' ? SearchParams.prototype.toString : null;
  const unsupported = member => new TypeError('lsf-fetch-buffered-v1:unsupported:' + member);
  const records = new WeakMap();
  const immutableHeaders = new WeakSet();
  const errorResponses = new WeakSet();
  let outstanding = 0;
  function readonly(owner, values) {
    for (const [key, value] of Object.entries(values)) {
      Object.defineProperty(owner, key, {value, enumerable: true, configurable: true, writable: false});
    }
  }
  function bytes(value) {
    if (value == null) return null;
    let result;
    if (typeof value === 'string') {
      if (value.length > maxBody) throw new RangeError('fetch-body-limit');
      result = encoder.encode(value);
    } else if (value instanceof ArrayBuffer) result = new Uint8Array(value);
    else if (ArrayBuffer.isView(value)) result = new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
    else throw unsupported('body-type');
    if (result.byteLength > maxBody) throw new RangeError('fetch-body-limit');
    return result.slice();
  }
  function extractBody(value) {
    let type = null;
    if (serializeParams !== null && value instanceof SearchParams) {
      // Serialize the native list, never a user-supplied stringifier/iterator.
      value = Reflect.apply(serializeParams, value, []);
      type = 'application/x-www-form-urlencoded;charset=UTF-8';
    } else if (typeof value === 'string') type = 'text/plain;charset=UTF-8';
    return {content: bytes(value), type};
  }
  function name(value) {
    const result = String(value).toLowerCase();
    if (!/^[!#$%&'*+.^_`|~0-9a-z-]+$/.test(result) || result.length > 64) throw new TypeError('invalid-header-name');
    return result;
  }
  function headerValue(value) {
    const result = String(value).replace(/^[\t ]+|[\t ]+$/g, '');
    if (/[^\t\x20-\x7e\x80-\xff]/.test(result)) throw new TypeError('invalid-header-value');
    return result;
  }
  class Headers {
    #entries = new Map();
    constructor(init = undefined) {
      if (init === undefined) return;
      if (init === null || typeof init !== 'object' && typeof init !== 'function') throw new TypeError('invalid-header-init');
      const iterator = init[Symbol.iterator];
      if (iterator != null) {
        if (typeof iterator !== 'function') throw new TypeError('invalid-header-sequence');
        let count = 0;
        for (const entry of {[Symbol.iterator]() {return Reflect.apply(iterator, init, []);}}) {
          if (++count > maxHeaders || entry === null || typeof entry !== 'object' && typeof entry !== 'function') {
            throw new TypeError('invalid-header-sequence');
          }
          const pairIterator = entry[Symbol.iterator];
          if (typeof pairIterator !== 'function') throw new TypeError('invalid-header-sequence');
          const pair = [];
          for (const value of {[Symbol.iterator]() {return Reflect.apply(pairIterator, entry, []);}}) {
            if (pair.length === 2) throw new TypeError('invalid-header-sequence');
            pair.push(value);
          }
          if (pair.length !== 2) throw new TypeError('invalid-header-sequence');
          this.append(pair[0], pair[1]);
        }
      } else {
        for (const key of Object.keys(init)) this.append(key, init[key]);
      }
    }
    #store(key, value) {
      if (immutableHeaders.has(this)) throw new TypeError('immutable-response-headers');
      let size = key.length + value.length;
      for (const [other, content] of this.#entries) if (other !== key) size += other.length + content.length;
      if (size > maxHeaderBytes || !this.#entries.has(key) && this.#entries.size >= maxHeaders) throw new RangeError('fetch-header-limit');
      this.#entries.set(key, value);
    }
    append(key, value) {
      key = name(key); value = headerValue(value);
      this.#store(key, this.#entries.has(key) ? this.#entries.get(key) + ', ' + value : value);
    }
    set(key, value) { this.#store(name(key), headerValue(value)); }
    get(key) { return this.#entries.get(name(key)) ?? null; }
    has(key) { return this.#entries.has(name(key)); }
    delete(key) {
      if (immutableHeaders.has(this)) throw new TypeError('immutable-response-headers');
      this.#entries.delete(name(key));
    }
    *entries() { yield* [...this.#entries].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0); }
    *keys() { for (const [key] of this.entries()) yield key; }
    *values() { for (const [, value] of this.entries()) yield value; }
    [Symbol.iterator]() { return this.entries(); }
    forEach(callback, thisArg) { for (const [key, value] of this.entries()) callback.call(thisArg, value, key, this); }
    getSetCookie() { throw unsupported('Headers.getSetCookie'); }
  }
  function bodyRecord(owner, content) { records.set(owner, {content, used: false, stream: null, controller: null}); }
  function unread(record) {
    if (record.used || record.stream?.locked) throw new TypeError('body-already-used');
  }
  function bodyStream(record) {
    if (record.stream !== null) return record.stream;
    if (typeof target.ReadableStream !== 'function') throw unsupported('streaming-body');
    let offset = record.used ? record.content.byteLength : 0;
    const stream = new target.ReadableStream({
      start(controller) {
        record.controller = controller;
        if (record.used) controller.close();
      },
      pull(controller) {
        record.used = true;
        if (offset < record.content.byteLength) {
          const end = Math.min(offset + 65536, record.content.byteLength);
          controller.enqueue(record.content.slice(offset, end));
          offset = end;
        }
        if (offset === record.content.byteLength) controller.close();
      },
      cancel() { record.used = true; offset = record.content.byteLength; },
    }, {highWaterMark: 0});
    const getReader = stream.getReader.bind(stream), cancel = stream.cancel.bind(stream);
    Object.defineProperties(stream, {
      getReader: {value(options) {
        const reader = getReader(options), read = reader.read.bind(reader);
        Object.defineProperty(reader, 'read', {value(...args) { record.used = true; return read(...args); }});
        return reader;
      }},
      cancel: {value(reason) {
        if (!stream.locked) record.used = true;
        return cancel(reason);
      }},
      tee: {value() { throw unsupported('Body.tee'); }},
      pipeTo: {value() { throw unsupported('Body.pipeTo'); }},
      pipeThrough: {value() { throw unsupported('Body.pipeThrough'); }},
      values: {value() { throw unsupported('Body.values'); }},
      [Symbol.asyncIterator]: {value() { throw unsupported('Body.values'); }},
    });
    record.stream = stream;
    return stream;
  }
  class Body {
    get bodyUsed() { return records.get(this).used; }
    get body() {
      const record = records.get(this);
      return record.content === null ? null : bodyStream(record);
    }
    async arrayBuffer() {
      const record = records.get(this);
      unread(record);
      if (record.content !== null && typeof target.ReadableStream === 'function') bodyStream(record);
      if (record.stream !== null) {
        const reader = record.stream.getReader(), chunks = [];
        let length = 0;
        for (;;) {
          const {done, value} = await reader.read();
          if (done) break;
          length += value.byteLength;
          if (length > maxBody) throw new RangeError('fetch-body-limit');
          chunks.push(value);
        }
        const result = new Uint8Array(length);
        let offset = 0;
        for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
        return result.buffer;
      }
      if (record.content !== null) {
        record.used = true;
      }
      return (record.content ?? new Uint8Array()).slice().buffer;
    }
    async text() { return decoder.decode(await this.arrayBuffer()); }
    async json() { return JSON.parse(await this.text()); }
    async blob() { throw unsupported('Body.blob'); }
    async formData() { throw unsupported('Body.formData'); }
  }
  function canonicalUrl(value) {
    if (typeof target.URL !== 'function') throw unsupported('runtime-URL');
    const url = new target.URL(String(value));
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new TypeError('invalid-fetch-url');
    url.hash = '';
    if (url.href.length > 2048) throw new RangeError('fetch-url-limit');
    return url.href;
  }
  function method(value) {
    const original = String(value), normalized = original.toUpperCase();
    if (!['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'].includes(normalized)) throw unsupported('method:' + original);
    return normalized;
  }
  class Request extends Body {
    constructor(input, init = {}) {
      super();
      if (init == null) init = {};
      const previous = input instanceof Request ? input : null;
      this.url = canonicalUrl(previous ? previous.url : input);
      this.method = method(init.method ?? previous?.method ?? 'GET');
      this.headers = new Headers(init.headers ?? previous?.headers);
      this.redirect = init.redirect ?? previous?.redirect ?? 'follow';
      this.credentials = init.credentials ?? previous?.credentials ?? 'same-origin';
      this.mode = init.mode ?? previous?.mode ?? 'cors';
      if (!['follow', 'manual', 'error'].includes(this.redirect)) throw new TypeError('invalid-redirect-mode');
      if (!['omit', 'same-origin'].includes(this.credentials)) throw unsupported('credentials');
      if (this.mode !== 'cors') throw unsupported('mode');
      if (init.cache !== undefined && init.cache !== 'default') throw unsupported('cache');
      for (const key of ['integrity', 'referrer', 'referrerPolicy']) if (init[key]) throw unsupported(key);
      if (init.keepalive) throw unsupported('keepalive');
      if (init.duplex !== undefined) throw unsupported('duplex');
      const sourceSignal = init.signal === undefined ? previous?.signal : init.signal;
      if (sourceSignal != null && !(sourceSignal instanceof target.AbortSignal)) throw new TypeError('invalid-AbortSignal');
      // Use the maintained native dependent-signal algorithms, including weak
      // dependency ownership. Request and clone never expose the input signal.
      this.signal = target.AbortSignal.any(sourceSignal == null ? [] : [sourceSignal]);
      let content, inheritBody = false;
      if (init.body != null) {
        const extracted = extractBody(init.body);
        content = extracted.content;
        if (extracted.type !== null && !this.headers.has('content-type')) this.headers.set('content-type', extracted.type);
      } else if (previous) {
        unread(records.get(previous));
        content = bytes(records.get(previous).content);
        inheritBody = content !== null;
      } else content = null;
      if (['GET', 'HEAD'].includes(this.method) && content !== null) throw new TypeError('body-for-get-or-head');
      bodyRecord(this, content);
      readonly(this, {url: this.url, method: this.method, headers: this.headers, signal: this.signal,
        redirect: this.redirect, credentials: this.credentials, mode: this.mode});
      if (inheritBody) records.get(previous).used = true;
    }
    clone() {
      unread(records.get(this));
      const result = new Request(this.url, {method: this.method, headers: this.headers, signal: this.signal,
        redirect: this.redirect, credentials: this.credentials, mode: this.mode, body: records.get(this).content});
      return result;
    }
  }
  class Response extends Body {
    constructor(body = null, init = {}) {
      super();
      const status = init.status === undefined ? 200 : Number(init.status);
      if (!Number.isInteger(status) || status < 200 || status > 599) throw new RangeError('invalid-response-status');
      const {content, type} = extractBody(body);
      if ([204, 205, 304].includes(status) && content !== null) throw new TypeError('body-for-null-body-status');
      this.status = status;
      this.statusText = init.statusText === undefined ? '' : headerValue(init.statusText);
      this.headers = new Headers(init.headers);
      if (type !== null && !this.headers.has('content-type')) this.headers.set('content-type', type);
      this.url = '';
      this.redirected = false;
      this.type = 'default';
      bodyRecord(this, content);
      readonly(this, {status: this.status, statusText: this.statusText, headers: this.headers,
        url: this.url, redirected: this.redirected, type: this.type});
    }
    get ok() { return this.status >= 200 && this.status <= 299; }
    clone() {
      unread(records.get(this));
      if (errorResponses.has(this)) return Response.error();
      const statusText = Object.getOwnPropertyDescriptor(this, 'statusText');
      const result = new Response(records.get(this).content, {status: this.status,
        statusText: statusText.get ? '' : statusText.value, headers: this.headers});
      readonly(result, {url: this.url, redirected: this.redirected, type: this.type});
      if (statusText.get) Object.defineProperty(result, 'statusText', statusText);
      if (immutableHeaders.has(this.headers)) immutableHeaders.add(result.headers);
      return result;
    }
    static json(value, init = {}) {
      const body = JSON.stringify(value);
      if (body === undefined) throw new TypeError('value-not-json-serializable');
      const headers = new Headers(init.headers);
      if (!headers.has('content-type')) headers.set('content-type', 'application/json');
      return new Response(body, {...init, headers});
    }
    static error() {
      const result = new Response();
      readonly(result, {status: 0, type: 'error'});
      immutableHeaders.add(result.headers);
      errorResponses.add(result);
      return result;
    }
    static redirect(url, status = 302) {
      if (typeof target.URL !== 'function') throw unsupported('runtime-URL');
      if (typeof url === 'symbol') throw new TypeError('invalid-redirect-url');
      const input = String(url), numeric = +status;
      const code = Number.isFinite(numeric) ? ((Math.trunc(numeric) % 65536) + 65536) % 65536 : 0;
      const parsed = new target.URL(input);
      if (!['http:', 'https:'].includes(parsed.protocol)) throw unsupported('Response.redirect-url');
      if (parsed.href.length > 2048) throw new RangeError('fetch-url-limit');
      if (![301, 302, 303, 307, 308].includes(code)) throw new RangeError('invalid-redirect-status');
      const result = new Response(null, {status: code, headers: {location: parsed.href}});
      immutableHeaders.add(result.headers);
      return result;
    }
  }
  const forbidden = new Set(['host', 'content-length', 'content-encoding', 'accept-encoding', 'authorization',
    'cookie', 'set-cookie', 'expect', 'x-api-key', 'x-auth-token', 'x-amz-security-token', 'connection',
    'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'proxy-connection', 'te', 'trailer',
    'transfer-encoding', 'upgrade']);
  function metadata(request) {
    const headers = [], content = records.get(request).content;
    for (const [key, value] of request.headers) {
      if (forbidden.has(key)) throw unsupported('reserved-header:' + key);
      if (key !== 'content-type' && key !== 'idempotency-key') headers.push({name: key, value});
    }
    return {method: request.method.toLowerCase(), url: request.url, headers,
      bodyLength: BigInt(content?.byteLength ?? 0), bodyMediaType: request.headers.get('content-type') ?? undefined,
      idempotencyKey: request.headers.get('idempotency-key') ?? undefined, timeoutMillis: undefined};
  }
  function drop(owner) {
    const destroy = owner[Symbol.dispose ?? Symbol.for('dispose')];
    if (typeof destroy !== 'function') throw new TypeError('generated-resource-destructor-missing');
    destroy.call(owner);
  }
  function failure(error) {
    const tag = error?.payload?.tag ?? error?.tag;
    if (error instanceof Error && typeof tag !== 'string') return error;
    const result = new TypeError('fetch-transport-failure:' + (typeof tag === 'string' ? tag : 'unknown'));
    Object.defineProperty(result, 'cause', {value: error});
    Object.defineProperty(result, 'uncertain', {value: tag === 'uncertain'});
    return result;
  }
  async function perform(request, cancelled) {
    for (let hop = 0; hop <= 5; hop++) {
      let upload, body, response;
      try {
        upload = await http.open(metadata(request));
        if (cancelled()) throw request.signal.reason;
        const content = records.get(request).content;
        if (content !== null) {
          for (let offset = 0; offset < content.byteLength; offset += 65536) {
            await http.write(upload, content.subarray(offset, offset + 65536));
            if (cancelled()) throw request.signal.reason;
          }
        }
        const consumed = upload; upload = undefined;
        const received = await http.finish(consumed);
        body = received.body;
        const parts = [];
        let total = 0;
        while (true) {
          if (cancelled()) throw request.signal.reason;
          const chunk = await http.read(body, 65536);
          if (chunk === undefined) break;
          try {
            const part = await http.chunkBytes(chunk);
            if (!ArrayBuffer.isView(part) || part.BYTES_PER_ELEMENT !== 1 || !part.byteLength || part.byteLength > 65536) throw new TypeError('invalid-http-chunk');
            total += part.byteLength;
            if (total > maxBody) throw new RangeError('fetch-body-limit');
            // A canonical chunk may own the materialized view's storage. Retain
            // only our independently owned bytes before invoking its destructor.
            const owned = new Uint8Array(part.byteLength);
            owned.set(part);
            parts.push(owned);
          } finally { drop(chunk); }
        }
        const contentBytes = new Uint8Array(total);
        let offset = 0;
        for (const part of parts) { contentBytes.set(part, offset); offset += part.byteLength; }
        const headers = new Headers(received.headers.map(({name, value}) => [name, value]));
        if (received.bodyMediaType && !headers.has('content-type')) headers.set('content-type', received.bodyMediaType);
        const result = new Response(request.method === 'HEAD' || [204, 205, 304].includes(received.status) ? null : contentBytes,
          {status: received.status, headers});
        readonly(result, {url: request.url, type: 'basic'});
        // The typed contract has no reason phrase. It must not fabricate one.
        Object.defineProperty(result, 'statusText', {get() { throw unsupported('response-status-text'); }, configurable: true});
        immutableHeaders.add(result.headers);
        response = result;
      } finally {
        // These are actual canonical destructors, after every outstanding borrow
        // settled. Promise rejection or abort acknowledgement releases no owner.
        try { if (body !== undefined) drop(body); }
        finally { if (upload !== undefined) drop(upload); }
      }
      if (cancelled()) throw request.signal.reason;
      const location = response.headers.get('location');
      if (![301, 302, 303, 307, 308].includes(response.status) || location === null) {
        readonly(response, {redirected: hop !== 0});
        return response;
      }
      // Manual fetch uses an opaque-redirect response unavailable in this
      // contract. Reject explicitly instead of fabricating status/type/body.
      if (request.redirect !== 'follow') throw unsupported('redirect-response:' + request.redirect);
      if (!['GET', 'HEAD'].includes(request.method)) throw unsupported('mutation-redirect');
      if (hop === 5) throw new TypeError('fetch-redirect-limit');
      const previous = new target.URL(request.url), next = new target.URL(location, previous);
      const headers = previous.origin === next.origin ? request.headers : new Headers();
      request = new Request(next.href, {method: request.method, headers, signal: request.signal,
        credentials: request.credentials, redirect: request.redirect});
    }
  }
  function fetch(input, init) {
    if (snapshotActive()) throw new TypeError('snapshot-time-network-observation-unsupported');
    return new Promise((resolve, reject) => {
      const request = new Request(input, init);
      metadata(request); // Validate before admitting or contacting a provider.
      if (request.signal.aborted) { reject(request.signal.reason); return; }
      if (outstanding >= 16) throw new RangeError('fetch-outstanding-operation-limit');
      if (records.get(request).content !== null) records.get(request).used = true;
      outstanding++;
      let cancelled = false;
      const abort = () => { cancelled = true; reject(request.signal.reason); };
      request.signal.addEventListener('abort', abort, {once: true});
      // Keep accepted work registered and charged even if the public Promise
      // rejects first. Stop at the next actual import completion; never replay.
      const completed = () => {
        request.signal.removeEventListener('abort', abort);
        outstanding--;
      };
      perform(request, () => cancelled).then(response => {
        completed();
        resolve(response);
      }, error => {
        completed();
        reject(failure(error));
      });
    });
  }
  Object.assign(target, {Headers, Request, Response, fetch});
}
