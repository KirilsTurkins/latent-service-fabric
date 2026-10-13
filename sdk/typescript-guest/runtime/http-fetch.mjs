import {Headers} from './http-headers.mjs';
import {NativeBodyReader, maximumChunkBytes} from './http-body.mjs';
import {Request, Response, responseFromNative, requestBodyState, abortResponseBody} from './http-objects.mjs';

const dispose = Symbol.dispose || Symbol.for('dispose');
const supportedMethods = new Map(['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'].map(name => [name, name.toLowerCase()]));
const redirects = new Set([301, 302, 303, 307, 308]);

function drop(value) {
  const destroy = value?.[dispose];
  if (typeof destroy !== 'function') throw new TypeError('canonical-resource-destructor-required');
  destroy.call(value);
}

function networkError(cause) { return new TypeError('native-HTTP-operation-failed', {cause}); }

export function installFetchGlobals(bridge, target = globalThis) {
  const http = bridge?.http;
  if (!http || typeof bridge.invoke !== 'function') throw new TypeError('SDK-native-HTTP-bridge-required');
  for (const name of ['open', 'write', 'finish', 'read', 'chunkBytes']) {
    if (typeof http[name] !== 'function') throw new TypeError('SDK-native-HTTP-operation-required');
  }

  function operation(name, arguments_) { return bridge.invoke(http[name], http, arguments_); }
  // One failed cleanup poisons this activation's SDK owner. Retain the exact
  // resources and acknowledgement failure instead of accepting more work.
  let failedCleanup;

  async function awaited(name, arguments_, signal, boundary) {
    boundary.retired = false;
    const accepted = operation(name, arguments_);
    let failed = false;
    let failure;
    let value;
    const abort = () => {
      try { accepted.cancel(signal.reason); }
      catch (error) { boundary.cleanupFailure = error; }
    };
    if (signal) {
      signal.addEventListener('abort', abort, {once: true});
      if (signal.aborted) abort();
    }
    try {
      try { value = await accepted.result; }
      catch (error) { failed = true; failure = error; }
      // Never discharge a borrow or infer physical completion from rejection.
      try { await accepted.retired; }
      catch (error) {
        boundary.cleanupFailure = error;
        throw failed ? signal?.aborted ? signal.reason : networkError(failure) : error;
      }
      boundary.retired = true;
      if (failed) throw signal?.aborted ? signal.reason : networkError(failure);
      return value;
    } finally { signal?.removeEventListener('abort', abort); }
  }

  async function fetch(input, init = undefined) {
    if (failedCleanup) throw new TypeError('native-HTTP-cleanup-not-complete', {cause: failedCleanup.error});
    const request = new Request(input, init);
    const signal = request.signal;
    if (signal.aborted) throw signal.reason;
    const url = new URL(request.url);
    if (!['http:', 'https:'].includes(url.protocol)) throw new TypeError('native-HTTP-URL-scheme-not-supported');
    url.hash = '';
    const method = supportedMethods.get(request.method);
    if (!method) throw new TypeError('native-HTTP-method-not-supported');
    if (request.keepalive || request.integrity || !['default', 'no-store'].includes(request.cache)) {
      throw new TypeError('native-HTTP-request-option-not-supported');
    }
    // The provider owns credentials and destination/header permission. Preserve
    // all other names, including denied credential headers, for that decision.
    const headers = [];
    for (const [name, value] of request.headers) {
      if (/[^\x00-\x7f]/.test(value)) throw new TypeError('native-HTTP-non-ASCII-header-mapping-not-supported');
      if (name !== 'content-type' && name !== 'idempotency-key') headers.push({name, value});
    }
    const body = requestBodyState(request);
    const bytes = body.hasBody ? await body.consume() : undefined;
    if (signal.aborted) throw signal.reason;
    let upload;
    let responseBody;
    const boundary = {retired: true, cleanupFailure: undefined};
    try {
      upload = await awaited('open', [{method, url: url.href, headers,
        bodyLength: bytes ? BigInt(bytes.byteLength) : 0n,
        bodyMediaType: request.headers.get('content-type') ?? undefined,
        idempotencyKey: request.headers.get('idempotency-key') ?? undefined,
        timeoutMillis: undefined}], signal, boundary);
      if (signal.aborted) throw signal.reason;
      if (bytes) {
        for (let offset = 0; offset < bytes.byteLength; offset += maximumChunkBytes) {
          await awaited('write', [upload, bytes.slice(offset, offset + maximumChunkBytes)], signal, boundary);
          if (signal.aborted) throw signal.reason;
        }
      }
      const finishing = upload;
      upload = undefined; // The canonical call consumes this exact upload.
      const metadata = await awaited('finish', [finishing], signal, boundary);
      responseBody = metadata.body;
      if (signal.aborted) throw signal.reason;
      if (redirects.has(metadata.status) && request.redirect !== 'manual') {
        throw new TypeError(request.redirect === 'error' ? 'HTTP-redirect-refused' : 'automatic-HTTP-redirect-not-supported');
      }
      const heldBody = responseBody;
      let bodyClosed = false;
      let abortBody;
      const native = new NativeBodyReader({
        read: maximum => operation('read', [heldBody, maximum]),
        materialize: chunk => operation('chunkBytes', [chunk]),
        dropChunk: drop,
        dropBody: () => {
          drop(heldBody);
          bodyClosed = true;
          if (abortBody) signal.removeEventListener('abort', abortBody);
        },
      });
      responseBody = undefined; // The native reader owns cleanup, including failures.
      const response = await responseFromNative({...metadata, url: url.href}, native);
      if (!bodyClosed) {
        abortBody = () => {
          abortResponseBody(response, signal.reason).catch(error => {
            failedCleanup ??= {error, native, body: heldBody};
          });
        };
        signal.addEventListener('abort', abortBody, {once: true});
        if (signal.aborted) abortBody();
      }
      return response;
    } catch (error) {
      if (boundary.retired) {
        if (responseBody !== undefined) {
          try { drop(responseBody); }
          catch (cleanup) { failedCleanup ??= {error: cleanup, body: responseBody}; }
        }
        if (upload !== undefined) {
          try { drop(upload); }
          catch (cleanup) { failedCleanup ??= {error: cleanup, upload}; }
        }
      } else {
        failedCleanup ??= {error: boundary.cleanupFailure, upload, body: responseBody};
      }
      throw error;
    }
  }

  Object.defineProperties(target, {
    Headers: {value: Headers, writable: true, configurable: true},
    Request: {value: Request, writable: true, configurable: true},
    Response: {value: Response, writable: true, configurable: true},
    fetch: {value: fetch, writable: true, configurable: true},
  });
  return fetch;
}
