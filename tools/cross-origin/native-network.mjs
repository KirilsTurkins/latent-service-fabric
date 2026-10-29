// Chromium's network-service observations, not Fetch's provisional header view.
// CORS failures may have no Playwright Response; a revalidated response may be
// exposed as 200 even though the network status is 304. ExtraInfo is authoritative.
import assert from 'node:assert/strict';
import {setTimeout as delay} from 'node:timers/promises';

const requestFields = ['origin', 'sec-fetch-site', 'sec-fetch-mode', 'sec-fetch-dest'];
const responseFields = ['access-control-allow-origin', 'access-control-allow-credentials',
  'access-control-allow-methods', 'access-control-allow-headers', 'access-control-expose-headers',
  'access-control-max-age', 'cache-control', 'vary', 'etag',
  'cross-origin-resource-policy', 'x-content-type-options'];

function selectedHeaders(headers, names) {
  assert.ok(headers && typeof headers === 'object' && !Array.isArray(headers), 'network-header-object');
  const keys = Object.keys(headers), selected = {};
  assert.ok(keys.length <= 128, 'network-header-count-bound');
  let bytes = 0;
  for (const key of keys) {
    const name = key.toLowerCase();
    if (!names.includes(name)) continue;
    const value = headers[key];
    assert.ok(typeof value === 'string' && !Object.hasOwn(selected, name), 'network-ambiguous-wire-header');
    bytes += Buffer.byteLength(name) + Buffer.byteLength(value);
    assert.ok(bytes <= 8192, 'network-policy-header-byte-bound');
    selected[name] = value;
  }
  return selected;
}

export function policyHeaders(headers) {
  return selectedHeaders(headers, responseFields);
}

export async function recordNetwork(session, {origins, observations, scope, fail, maximum = 256}) {
  assert.ok(Number.isInteger(maximum) && maximum > 0 && maximum <= 256, 'network-observation-limit-bound');
  const entries = new Map(), listeners = [];
  let closed = false, events = 0;
  const close = () => {
    if (closed) return;
    closed = true;
    for (const [name, handler] of listeners) session.off(name, handler);
    entries.clear();
  };
  const entry = id => {
    assert.ok(typeof id === 'string' && id.length > 0 && id.length <= 128, 'network-request-id-size-bound');
    if (!entries.has(id)) {
      assert.ok(entries.size < maximum * 2, 'network-request-id-bound');
      entries.set(id, {});
    }
    return entries.get(id);
  };
  const listen = (event, action) => {
    const name = 'Network.' + event;
    const handler = message => {
      if (closed) return;
      try {
        if (++events > maximum * 16) {
          close();
          throw new Error('network-event-count-bound');
        }
        action(message, entry(message.requestId));
      } catch (error) { fail(error); }
    };
    listeners.push([name, handler]);
    session.on(name, handler);
  };
  const publish = state => {
    if (state.row) Object.assign(state.row, state.request, state.response);
  };
  listen('requestWillBeSent', ({request, redirectResponse}, state) => {
    const url = new URL(request.url);
    if (!origins.includes(url.origin)) return;
    assert.ok(!state.row && !redirectResponse, 'native-asset-redirect-not-permitted');
    assert.ok(url.pathname.length <= 4096 && typeof request.method === 'string'
      && request.method.length <= 16, 'network-request-metadata-bound');
    assert.ok(observations.length < maximum, 'network-observation-bound');
    state.row = {transport: 'chromium-network-service', ...scope(), method: request.method, path: url.pathname};
    observations.push(state.row);
    publish(state);
  });
  listen('requestWillBeSentExtraInfo', ({headers}, state) => {
    assert.ok(!state.request, 'network-duplicate-request-extra-info');
    const fields = selectedHeaders(headers, requestFields);
    // Do not retain Cookie/Authorization values, raw headers or arbitrary URLs.
    state.request = {requestHeadersObserved: true, origin: fields.origin ?? null,
      site: fields['sec-fetch-site'] ?? null, mode: fields['sec-fetch-mode'] ?? null,
      destination: fields['sec-fetch-dest'] ?? null, cookiePresent: Object.keys(headers).some(name => name.toLowerCase() === 'cookie' && Boolean(headers[name]))};
    publish(state);
  });
  listen('responseReceivedExtraInfo', ({statusCode, headers}, state) => {
    assert.ok(!state.response, 'network-duplicate-response-extra-info');
    assert.ok(Number.isInteger(statusCode) && statusCode >= 100 && statusCode <= 599, 'network-invalid-status');
    state.response = {status: statusCode, headers: policyHeaders(headers), responseHeadersObserved: true};
    publish(state);
  });
  listen('loadingFailed', (_, state) => { if (state.row) state.row.failed = true; });
  try {
    await session.send('Network.enable', {maxTotalBufferSize: 65536, maxResourceBufferSize: 16384, maxPostDataSize: 0});
  } catch (error) { close(); throw error; }
  return {
    // The caller owns the CDP session and browser; this releases only our listeners/state.
    close,
    async flush() {
      assert.ok(!closed, 'network-recorder-closed');
      // Drain protocol events already queued before advancing the case label.
      await session.send('Runtime.evaluate', {expression: '0', returnByValue: true});
    },
    async waitFor(predicate, message) {
      assert.ok(!closed, 'network-recorder-closed');
      const deadline = performance.now() + 5000;
      while (!observations.some(predicate)) {
        assert.ok(!closed, 'network-recorder-closed');
        assert.ok(performance.now() < deadline, message);
        await delay(10);
      }
    },
  };
}
