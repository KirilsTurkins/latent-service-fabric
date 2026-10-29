// Chromium's network-service observations, not Fetch's provisional header view.
// CORS failures may have no Playwright Response; a revalidated response may be
// exposed as 200 even though the network status is 304. ExtraInfo is authoritative.
import assert from 'node:assert/strict';
import {setTimeout as delay} from 'node:timers/promises';

export function policyHeaders(headers) {
  return Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value])
    .filter(([key]) => key.startsWith('access-control-') ||
      ['cache-control', 'vary', 'etag', 'cross-origin-resource-policy', 'x-content-type-options'].includes(key)));
}

export async function recordNetwork(session, {origins, observations, scope, fail, maximum = 256}) {
  const entries = new Map();
  const entry = id => {
    if (!entries.has(id)) {
      assert.ok(entries.size < maximum * 2, 'network-request-id-bound');
      entries.set(id, {});
    }
    return entries.get(id);
  };
  const listen = (event, action) => session.on('Network.' + event, message => {
    try { action(message, entry(message.requestId)); } catch (error) { fail(error); }
  });
  const publish = state => {
    if (state.row) Object.assign(state.row, state.request, state.response);
  };
  listen('requestWillBeSent', ({request}, state) => {
    const url = new URL(request.url);
    if (!origins.includes(url.origin)) return;
    assert.ok(!state.row, 'native-asset-redirect-not-permitted');
    assert.ok(observations.length < maximum, 'network-observation-bound');
    state.row = {transport: 'chromium-network-service', ...scope(), method: request.method, path: url.pathname};
    observations.push(state.row);
    publish(state);
  });
  listen('requestWillBeSentExtraInfo', ({headers}, state) => {
    const fields = Object.fromEntries(Object.entries(headers).map(([key, value]) => [key.toLowerCase(), value]));
    // Do not retain Cookie/Authorization values, raw headers or arbitrary URLs.
    state.request = {requestHeadersObserved: true, origin: fields.origin ?? null,
      site: fields['sec-fetch-site'] ?? null, mode: fields['sec-fetch-mode'] ?? null,
      destination: fields['sec-fetch-dest'] ?? null, cookiePresent: Boolean(fields.cookie)};
    publish(state);
  });
  listen('responseReceivedExtraInfo', ({statusCode, headers}, state) => {
    state.response = {status: statusCode, headers: policyHeaders(headers), responseHeadersObserved: true};
    publish(state);
  });
  listen('loadingFailed', (_, state) => { if (state.row) state.row.failed = true; });
  await session.send('Network.enable');
  return {
    async flush() {
      // Drain protocol events already queued before advancing the case label.
      await session.send('Runtime.evaluate', {expression: '0', returnByValue: true});
    },
    async waitFor(predicate, message) {
      const deadline = performance.now() + 5000;
      while (!observations.some(predicate)) {
        assert.ok(performance.now() < deadline, message);
        await delay(10);
      }
    },
  };
}
