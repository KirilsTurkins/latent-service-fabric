// SDK-owned body sources. None of these constructors authorizes an operation.
export const maximumBodyBytes = 16 * 1024 * 1024;
export const maximumChunkBytes = 16 * 1024;
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const Stream = globalThis.ReadableStream;
const BlobType = globalThis.Blob;

function boundedBytes(value) {
  if (!(value instanceof Uint8Array) || value.byteLength > maximumBodyBytes) {
    throw new TypeError('body-profile-byte-limit-or-type');
  }
  return value;
}

function encode(value) {
  // Check UTF-8 capacity before allocating its byte array, including lone surrogates.
  let bytes = 0;
  for (const point of value) {
    const code = point.codePointAt(0);
    bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
    if (bytes > maximumBodyBytes) throw new TypeError('body-profile-byte-limit');
  }
  return encoder.encode(value);
}

export function extractBody(value) {
  if (value === undefined || value === null) return {source: null, mediaType: null};
  if (value instanceof ArrayBuffer) {
    return {source: boundedBytes(new Uint8Array(value)).slice(), mediaType: null};
  }
  if (ArrayBuffer.isView(value)) {
    if (!(value.buffer instanceof ArrayBuffer)) throw new TypeError('shared-body-buffer-not-supported');
    return {source: boundedBytes(new Uint8Array(value.buffer, value.byteOffset, value.byteLength)).slice(), mediaType: null};
  }
  if (typeof URLSearchParams === 'function' && value instanceof URLSearchParams) {
    return {source: encode(value.toString()), mediaType: 'application/x-www-form-urlencoded;charset=UTF-8'};
  }
  if (typeof BlobType === 'function' && value instanceof BlobType) {
    if (value.size > maximumBodyBytes) throw new TypeError('body-profile-byte-limit');
    return {source: value, mediaType: value.type || null};
  }
  if (typeof Stream === 'function' && value instanceof Stream) {
    throw new TypeError('request-stream-body-not-supported-by-this-source-profile');
  }
  if (typeof FormData === 'function' && value instanceof FormData) {
    throw new TypeError('form-data-body-encoding-not-supported');
  }
  if (typeof value === 'symbol') throw new TypeError('body-cannot-be-a-Symbol');
  return {source: encode(String(value)), mediaType: 'text/plain;charset=UTF-8'};
}

// Each operation is supplied by the compiler-owned canonical adapter. `retired`
// must acknowledge its real subtask drop and buffer/root retirement, even when
// `result` has already rejected. A JS rejection alone permits no resource drop.
export class NativeBodyReader {
  #operations;
  #current = null;
  #pulling = null;
  #cancellation = null;
  #cancelled = false;
  #reason;
  #closed = false;
  #cleanupFailure;
  #cleanupFailed = false;
  #failedChunk;
  #dropAttempted = false;
  #bodyDropFailure;

  #retainCleanup(error) {
    if (!this.#cleanupFailed) {
      this.#cleanupFailed = true;
      this.#cleanupFailure = error;
    }
  }

  constructor(operations) {
    for (const name of ['read', 'materialize', 'dropChunk', 'dropBody']) {
      if (typeof operations?.[name] !== 'function') throw new TypeError('native-body-operation-required');
    }
    this.#operations = operations;
  }

  async #run(start) {
    const operation = start();
    this.#current = operation;
    if (!operation || typeof operation.result?.then !== 'function' ||
        typeof operation.retired?.then !== 'function' || typeof operation.cancel !== 'function') {
      throw new TypeError('canonical-operation-and-retirement-required');
    }
    let value;
    let failed = false;
    let failure;
    try { value = await operation.result; }
    catch (error) { failed = true; failure = error; }
    try { await operation.retired; }
    catch (error) {
      this.#retainCleanup(error);
      // Keep the current owner: retirement was not acknowledged.
      throw failed ? failure : error;
    }
    this.#current = null;
    if (failed) throw failure;
    return value;
  }

  async #dropBody() {
    if (this.#closed) return;
    if (this.#current) throw new TypeError('native-body-operation-still-owned');
    if (this.#dropAttempted) throw this.#bodyDropFailure;
    this.#dropAttempted = true;
    try { await this.#operations.dropBody(); }
    catch (error) { this.#bodyDropFailure = error; throw error; }
    this.#closed = true;
  }

  async #pull() {
    let chunk;
    let output;
    let failed = false;
    let failure;
    try {
      chunk = await this.#run(() => this.#operations.read(maximumChunkBytes));
      if (this.#cancelled) throw this.#reason;
      if (chunk === undefined) {
        await this.#dropBody();
      } else {
        const bytes = await this.#run(() => this.#operations.materialize(chunk));
        if (this.#cancelled) throw this.#reason;
        if (!(bytes instanceof Uint8Array) || bytes.byteLength > maximumChunkBytes) {
          throw new TypeError('native-body-chunk-profile-limit-or-type');
        }
        output = bytes.slice(); // The returned bytes outlive the charged native chunk.
      }
    } catch (error) {
      failed = true;
      failure = error;
    } finally {
      if (chunk !== undefined && !this.#current) {
        try { await this.#operations.dropChunk(chunk); }
        catch (error) {
          this.#failedChunk = chunk;
          this.#retainCleanup(error);
          if (!failed) { failed = true; failure = error; }
        }
      }
    }
    if (failed) {
      if (!this.#current) {
        try { await this.#dropBody(); }
        catch (error) { this.#retainCleanup(error); }
      }
      throw failure;
    }
    return output;
  }

  pull() {
    if (this.#cancelled) return Promise.reject(this.#reason);
    if (this.#closed) return Promise.resolve(undefined);
    if (this.#failedChunk !== undefined) return Promise.reject(this.#cleanupFailure);
    if (this.#pulling) return Promise.reject(new TypeError('native-body-read-already-pending'));
    const pending = this.#pull();
    this.#pulling = pending;
    const clear = () => { if (this.#pulling === pending) this.#pulling = null; };
    return pending.then(value => { clear(); return value; }, error => { clear(); throw error; });
  }

  cancel(reason) {
    if (this.#cancellation) return this.#cancellation;
    this.#cancelled = true;
    this.#reason = reason;
    this.#cancellation = (async () => {
      let failed = false;
      let failure;
      try { this.#current?.cancel(reason); }
      catch (error) { failed = true; failure = error; }
      if (this.#pulling) {
        try { await this.#pulling; }
        catch (error) {
          if (this.#current && !failed) { failed = true; failure = error; }
        }
      }
      try { await this.#dropBody(); }
      catch (error) {
        this.#retainCleanup(error);
        if (!failed) { failed = true; failure = error; }
      }
      if (failed) throw failure;
    })();
    return this.#cancellation;
  }

  get cleanupFailure() { return this.#cleanupFailure; }
}

export class BodyState {
  #source;
  #stream = null;
  #controller;
  #disturbed = false;

  constructor(source) { this.#source = source; }

  get stream() {
    if (this.#source === null) return null;
    if (this.#stream) return this.#stream;
    if (typeof Stream !== 'function') throw new TypeError('ReadableStream-is-unavailable');
    let delivered = false;
    this.#stream = new Stream({
      start: controller => { this.#controller = controller; },
      pull: async controller => {
        this.#disturbed = true;
        if (this.#source instanceof NativeBodyReader) {
          const bytes = await this.#source.pull();
          if (bytes === undefined) controller.close();
          else controller.enqueue(bytes);
        } else if (!delivered) {
          delivered = true;
          const bytes = this.#source instanceof Uint8Array ? this.#source.slice() :
            boundedBytes(new Uint8Array(await this.#source.arrayBuffer()));
          controller.enqueue(bytes);
          controller.close();
        }
      },
      cancel: reason => {
        this.#disturbed = true;
        return this.#source instanceof NativeBodyReader ? this.#source.cancel(reason) : undefined;
      },
    }, {highWaterMark: 0});
    return this.#stream;
  }

  get used() { return this.#disturbed; }
  get hasBody() { return this.#source !== null; }
  get unusable() { return this.#disturbed || Boolean(this.#stream?.locked); }

  clone() {
    if (this.unusable) throw new TypeError('body-is-used-or-locked');
    if (this.#source instanceof NativeBodyReader) throw new TypeError('native-body-clone-not-supported');
    return new BodyState(this.#source instanceof Uint8Array ? this.#source.slice() : this.#source);
  }

  move() {
    const transferred = this.clone();
    if (this.#source !== null) {
      // These finite sources were transferred synchronously. The inaccessible
      // old stream is locked and closed; no native I/O is retired here.
      this.stream.getReader();
      this.#disturbed = true;
      this.#controller.close();
    }
    return transferred;
  }

  async consume() {
    if (this.unusable) throw new TypeError('body-is-used-or-locked');
    if (this.#source === null) return new Uint8Array();
    this.#disturbed = true;
    const reader = this.stream.getReader();
    const chunks = [];
    let total = 0;
    try {
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        if (!(value instanceof Uint8Array) || value.byteLength > maximumBodyBytes - total) {
          const error = new TypeError('body-profile-byte-limit-or-type');
          try { await reader.cancel(error); } catch {}
          throw error;
        }
        total += value.byteLength;
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const result = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
    return result;
  }
}

export function bodyMethods(target, state, headers) {
  Object.defineProperties(target, {
    body: {get() { return state(this).stream; }, enumerable: true, configurable: true},
    bodyUsed: {get() { return state(this).used; }, enumerable: true, configurable: true},
  });
  target.bytes = async function () { return state(this).consume(); };
  target.arrayBuffer = async function () { return (await state(this).consume()).buffer; };
  target.text = async function () { return decoder.decode(await state(this).consume()); };
  target.json = async function () { return JSON.parse(decoder.decode(await state(this).consume())); };
  target.blob = async function () {
    if (typeof BlobType !== 'function') throw new TypeError('Blob-is-unavailable');
    return new BlobType([await state(this).consume()], {type: headers(this).get('content-type') || ''});
  };
  target.formData = async function () { throw new TypeError('form-data-body-decoding-not-supported'); };
}
