import {test} from 'node:test';
import assert from 'node:assert/strict';
import {publicGreeting} from '../../examples/browser-boundary/client/application.ts';

function browser(testContext, implementation) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'location');
  Object.defineProperty(globalThis, 'location', {configurable: true, value: {origin: 'https://public.example.test'}});
  testContext.after(() => {
    if (original) Object.defineProperty(globalThis, 'location', original);
    else delete globalThis.location;
  });
  testContext.mock.method(globalThis, 'fetch', implementation);
}

test('the browser companion calls only the fixed same-origin application without credentials or redirects', async context => {
  let calls = 0;
  browser(context, async (endpoint, options) => {
    calls += 1;
    assert.equal(endpoint.href, 'https://public.example.test/api/greeting');
    assert.equal(options.method, 'POST');
    assert.equal(options.body, '{"name":"Browser"}');
    assert.deepEqual(options.headers, {'content-type': 'application/json'});
    assert.equal(options.mode, 'same-origin');
    assert.equal(options.credentials, 'omit');
    assert.equal(options.redirect, 'error');
    assert.equal(options.cache, 'no-store');
    return Response.json({greeting: 'Hello Browser'});
  });
  assert.equal(await publicGreeting(new AbortController().signal), 'Hello Browser');
  assert.equal(calls, 1);
});

test('malformed, oversized and unintended public replies fail without replay', async context => {
  let calls = 0;
  let next;
  browser(context, async () => { calls += 1; return next(); });
  const fixtures = [
    () => new Response('x', {status: 403}),
    () => new Response('{"greeting":"wrong MIME"}', {headers: {'content-type': 'text/html'}}),
    () => Response.json({greeting: 'x'.repeat(257)}),
    () => Response.json({greeting: 'hello', administration: true}),
    () => new Response('{', {headers: {'content-type': 'application/json'}}),
    () => new Response(new Uint8Array([255]), {headers: {'content-type': 'application/json'}}),
    () => new Response('{}', {headers: {'content-type': 'application/json', 'content-length': '999'}}),
    () => new Response('{}', {headers: {'content-type': 'application/json', 'content-encoding': 'gzip'}}),
  ];
  for (const fixture of fixtures) {
    next = fixture;
    await assert.rejects(publicGreeting(new AbortController().signal));
  }
  assert.equal(calls, fixtures.length);
});

test('local abort closes the fetch wait and never sends an RPC cancel or retries', async context => {
  let calls = 0;
  browser(context, async (_endpoint, options) => {
    calls += 1;
    await new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted')), {once: true}));
  });
  const controller = new AbortController();
  const pending = publicGreeting(controller.signal);
  controller.abort();
  await assert.rejects(pending);
  await assert.rejects(publicGreeting(controller.signal), /application-aborted/);
  assert.equal(calls, 1);
});

test('a consumed document query token is removed before the actual application fetch', async context => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, 'history');
  let cleaned;
  browser(context, async () => {
    assert.equal(globalThis.location.href, 'https://public.example.test/index.html?retained=one#section');
    return Response.json({greeting: 'Hello Browser'});
  });
  globalThis.location.href = 'https://public.example.test/index.html?synthetic-token=one&retained=one&synthetic-token=two#section';
  Object.defineProperty(globalThis, 'history', {configurable: true, value: {
    replaceState(_state, _unused, path) {
      cleaned = path;
      globalThis.location.href = new URL(path, globalThis.location.origin).href;
    },
  }});
  context.after(() => {
    if (previous) Object.defineProperty(globalThis, 'history', previous);
    else delete globalThis.history;
    delete globalThis.boundaryTokenRemoved;
  });
  assert.equal(await publicGreeting(new AbortController().signal), 'Hello Browser');
  assert.equal(cleaned, '/index.html?retained=one#section');
  assert.equal(globalThis.boundaryTokenRemoved, true);
});
