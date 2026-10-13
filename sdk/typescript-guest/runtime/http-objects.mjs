import {Headers} from './http-headers.mjs';
import {BodyState, NativeBodyReader, bodyMethods, extractBody} from './http-body.mjs';

const token = /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/;
const requests = new WeakMap();
const responses = new WeakMap();
const bodylessStatuses = new Set([204, 205, 304]);
const RequestURL = URL;
const Controller = AbortController;

function string(value) {
  if (typeof value === 'symbol') throw new TypeError('HTTP-string-cannot-be-a-Symbol');
  return String(value);
}

function unsignedShort(value) {
  const number = +value;
  if (!Number.isFinite(number) || number === 0) return 0;
  return (Math.trunc(number) % 65536 + 65536) % 65536;
}

function branded(table, value) {
  const state = table.get(value);
  if (!state) throw new TypeError('invalid-HTTP-object-receiver');
  return state;
}

function enumeration(value, allowed, fallback) {
  if (value === undefined) return fallback;
  value = string(value);
  if (!allowed.includes(value)) throw new TypeError('invalid-request-option');
  return value;
}

function method(value) {
  const text = string(value);
  if (!token.test(text) || /^(CONNECT|TRACE|TRACK)$/i.test(text)) throw new TypeError('invalid-request-method');
  return /^(DELETE|GET|HEAD|OPTIONS|POST|PUT)$/i.test(text) ? text.toUpperCase() : text;
}

function followingSignal(signal) {
  const controller = new Controller();
  if (signal !== undefined && signal !== null) {
    if (typeof signal.addEventListener !== 'function' || typeof signal.aborted !== 'boolean') {
      throw new TypeError('AbortSignal-required');
    }
    if (signal.aborted) controller.abort(signal.reason);
    else signal.addEventListener('abort', () => controller.abort(signal.reason), {once: true});
  }
  return controller.signal;
}

function referrer(value) {
  if (value === '' || value === 'about:client') return value;
  return new RequestURL(string(value)).href;
}

export class Request {
  constructor(input, init = undefined) {
    if (arguments.length === 0) throw new TypeError('request-input-required');
    if (init !== undefined && init !== null && typeof init !== 'object' && typeof init !== 'function') {
      throw new TypeError('request-initializer-required');
    }
    init ??= {};
    const original = requests.get(input);
    const url = new RequestURL(original ? original.url : string(input));
    if (url.username || url.password) throw new TypeError('request-URL-credentials-forbidden');
    const selectedMethod = method(init.method === undefined ? original?.method ?? 'GET' : init.method);
    const headers = new Headers(init.headers === undefined ? original?.headers : init.headers);
    const extracted = init.body === undefined || init.body === null ? null : extractBody(init.body);
    const originalBody = extracted === null ? original?.body : null;
    if ((selectedMethod === 'GET' || selectedMethod === 'HEAD') &&
        (extracted ? extracted.source !== null : originalBody?.hasBody)) {
      throw new TypeError('GET-or-HEAD-request-cannot-have-a-body');
    }
    const mode = enumeration(init.mode, ['navigate', 'same-origin', 'no-cors', 'cors'], original?.mode ?? 'cors');
    if (mode === 'navigate') throw new TypeError('request-navigate-mode-forbidden');
    if (mode === 'no-cors' && !['GET', 'HEAD', 'POST'].includes(selectedMethod)) {
      throw new TypeError('no-cors-request-method-forbidden');
    }
    const cache = enumeration(init.cache, ['default', 'no-store', 'reload', 'no-cache', 'force-cache', 'only-if-cached'], original?.cache ?? 'default');
    if (cache === 'only-if-cached' && mode !== 'same-origin') throw new TypeError('only-if-cached-requires-same-origin');
    enumeration(init.duplex, ['half'], 'half');
    const options = {
      credentials: enumeration(init.credentials, ['omit', 'same-origin', 'include'], original?.credentials ?? 'same-origin'),
      redirect: enumeration(init.redirect, ['follow', 'error', 'manual'], original?.redirect ?? 'follow'),
      referrer: init.referrer === undefined ? original?.referrer ?? 'about:client' : referrer(string(init.referrer)),
      referrerPolicy: enumeration(init.referrerPolicy, ['', 'no-referrer', 'no-referrer-when-downgrade', 'origin',
        'origin-when-cross-origin', 'same-origin', 'strict-origin', 'strict-origin-when-cross-origin', 'unsafe-url'], original?.referrerPolicy ?? ''),
      integrity: string(init.integrity === undefined ? original?.integrity ?? '' : init.integrity),
      keepalive: init.keepalive === undefined ? original?.keepalive ?? false : Boolean(init.keepalive),
      destination: '', duplex: 'half',
    };
    const signal = followingSignal(init.signal === undefined ? original?.signal : init.signal);
    const body = extracted ? new BodyState(extracted.source) : originalBody?.move() ?? new BodyState(null);
    if (extracted?.mediaType && !headers.has('content-type')) headers.set('content-type', extracted.mediaType);
    requests.set(this, {
      url: url.href, method: selectedMethod, headers, body, signal, mode, cache,
      ...options,
    });
  }

  clone() {
    const source = branded(requests, this);
    const result = Object.create(Request.prototype);
    requests.set(result, {...source, headers: new Headers(source.headers), body: source.body.clone(), signal: followingSignal(source.signal)});
    return result;
  }

  get [Symbol.toStringTag]() { return 'Request'; }
}

for (const key of ['url', 'method', 'headers', 'signal', 'mode', 'cache', 'credentials', 'redirect',
  'referrer', 'referrerPolicy', 'integrity', 'keepalive', 'destination', 'duplex']) {
  Object.defineProperty(Request.prototype, key, {get() { return branded(requests, this)[key]; }, enumerable: true, configurable: true});
}
bodyMethods(Request.prototype, value => branded(requests, value).body, value => branded(requests, value).headers);

function response(status, statusText, headers, body, additional = {}) {
  const result = Object.create(Response.prototype);
  responses.set(result, {status, statusText, headers, body, url: '', redirected: false, type: 'default', ...additional});
  return result;
}

export class Response {
  constructor(input = null, init = undefined) {
    if (init !== undefined && init !== null && typeof init !== 'object' && typeof init !== 'function') {
      throw new TypeError('response-initializer-required');
    }
    init ??= {};
    const status = init.status === undefined ? 200 : unsignedShort(init.status);
    if (status < 200 || status > 599) throw new RangeError('invalid-response-status');
    const statusText = init.statusText === undefined ? '' : string(init.statusText);
    if (/[^\t\x20-\x7e\x80-\xff]/.test(statusText)) throw new TypeError('invalid-response-status-text');
    const headers = new Headers(init.headers);
    const extracted = extractBody(input);
    if (bodylessStatuses.has(status) && extracted.source !== null) throw new TypeError('response-status-forbids-body');
    if (extracted.mediaType && !headers.has('content-type')) headers.set('content-type', extracted.mediaType);
    responses.set(this, {status, statusText, headers, body: new BodyState(extracted.source), url: '', redirected: false, type: 'default'});
  }

  get ok() { const status = branded(responses, this).status; return status >= 200 && status <= 299; }

  clone() {
    const source = branded(responses, this);
    return response(source.status, source.statusText, Headers.clone(source.headers), source.body.clone(),
      {url: source.url, redirected: source.redirected, type: source.type});
  }

  static error() { return response(0, '', Headers.fromTyped([]), new BodyState(null), {type: 'error'}); }

  static redirect(input, status = 302) {
    status = unsignedShort(status);
    if (![301, 302, 303, 307, 308].includes(status)) throw new RangeError('invalid-redirect-status');
    const location = new RequestURL(string(input)).href;
    return response(status, '', Headers.fromTyped([{name: 'location', value: location}]), new BodyState(null));
  }

  static json(value, init = undefined) {
    if (init !== undefined && init !== null && typeof init !== 'object' && typeof init !== 'function') {
      throw new TypeError('response-initializer-required');
    }
    const serialized = JSON.stringify(value);
    if (serialized === undefined) throw new TypeError('JSON-value-is-not-serializable');
    const headers = new Headers(init?.headers);
    if (!headers.has('content-type')) headers.set('content-type', 'application/json');
    return new Response(serialized, {...init, headers});
  }

  get [Symbol.toStringTag]() { return 'Response'; }
}

for (const key of ['status', 'statusText', 'headers', 'url', 'redirected', 'type']) {
  Object.defineProperty(Response.prototype, key, {get() { return branded(responses, this)[key]; }, enumerable: true, configurable: true});
}
bodyMethods(Response.prototype, value => branded(responses, value).body, value => branded(responses, value).headers);

// Called by the SDK adapter after genuine header success, never by an ambient
// Node transport. The native body is closed separately for bodyless statuses.
export async function responseFromNative(metadata, nativeBody) {
  if (!(nativeBody instanceof NativeBodyReader)) throw new TypeError('native-body-owner-required');
  try {
    if (!Number.isInteger(metadata.status) || metadata.status < 200 || metadata.status > 599) {
      throw new TypeError('invalid-native-response-status');
    }
    const headers = Headers.fromTyped(metadata.headers);
    const url = new RequestURL(metadata.url).href;
    const source = bodylessStatuses.has(metadata.status) ? null : nativeBody;
    if (source === null) await nativeBody.cancel();
    return response(metadata.status, '', headers, new BodyState(source), {type: 'basic', url});
  } catch (error) {
    try { await nativeBody.cancel(error); } catch {}
    throw error;
  }
}

export function requestBodyState(value) { return branded(requests, value).body; }
export function abortResponseBody(value, reason) { return branded(responses, value).body.abort(reason); }
