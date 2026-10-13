// These controlled canonical callbacks exercise SDK source ordering only.
import assert from 'node:assert/strict';
import {installFetchGlobals} from './http-fetch.mjs';
const dispose = Symbol.dispose || Symbol.for('dispose');
const ready = value => ({result: Promise.resolve(value), retired: Promise.resolve(), cancel() {}});
async function turns(count = 16) { for (let i = 0; i < count; i++) await Promise.resolve(); }

function fixture({status = 404, chunks = [new Uint8Array([65, 66])], read, write} = {}) {
  const events = [];
  const resources = new Set();
  function resource(name, bytes) {
    const value = {name, bytes, [dispose]() {
      assert(resources.delete(value), 'exact resource must still be owned');
      events.push('drop-' + name);
    }};
    resources.add(value);
    return value;
  }
  let request;
  const http = {
    open(value) { request = value; events.push('open'); return ready(resource('upload')); },
    write(upload, bytes) {
      assert(resources.has(upload));
      events.push(['write', bytes.byteLength]);
      return write ? write(upload, bytes) : ready();
    },
    finish(upload) {
      assert(resources.delete(upload)); // Actual generated own lowering consumes it.
      events.push('finish');
      return ready({status, headers: [{name: 'x-reply', value: 'yes'}], body: resource('body')});
    },
    read(body, maximum) {
      assert(resources.has(body)); assert.equal(maximum, 16384);
      events.push('read');
      if (read) return read(body);
      const bytes = chunks.shift();
      return ready(bytes === undefined ? undefined : resource('chunk', bytes));
    },
    chunkBytes(chunk) { assert(resources.has(chunk)); events.push('materialize'); return ready(chunk.bytes); },
  };
  const target = {};
  const fetch = installFetchGlobals({http, invoke(callable, receiver, args) {
    return Reflect.apply(callable, receiver, args);
  }}, target);
  return {fetch, target, events, resources, request: () => request};
}

const normal = fixture();
assert.equal(normal.target.fetch, normal.fetch);
assert.equal(normal.target.Headers.name, 'Headers');
const response = await normal.fetch('https://example.invalid/path#fragment', {headers: {
  Authorization: 'Bearer denied', Cookie: 'session=denied', 'X-Item': ['a', 'b'],
}});
assert.equal(response.status, 404); assert.equal(response.ok, false);
assert.equal(response.url, 'https://example.invalid/path');
assert.deepEqual(normal.request().headers, [
  {name: 'authorization', value: 'Bearer denied'},
  {name: 'cookie', value: 'session=denied'}, {name: 'x-item', value: 'a,b'},
]); // The provider must see and decide denied credentials.
assert.deepEqual(normal.events, ['open', 'finish']);
assert.equal(await response.text(), 'AB');
assert.deepEqual(normal.events, ['open', 'finish', 'read', 'materialize', 'drop-chunk', 'read', 'drop-body']);
assert.equal(normal.resources.size, 0);
await assert.rejects(response.text(), TypeError);
assert.throws(() => response.headers.set('x-new', 'no'), TypeError);

const posted = fixture({status: 204});
const noBody = await posted.fetch('https://example.invalid/', {method: 'POST',
  body: new Uint8Array(16385), headers: {'Content-Type': 'application/octet-stream', 'Idempotency-Key': 'stable'}});
assert.equal(posted.request().bodyLength, 16385n);
assert.equal(posted.request().bodyMediaType, 'application/octet-stream');
assert.equal(posted.request().idempotencyKey, 'stable');
assert.deepEqual(posted.request().headers, []);
assert.deepEqual(posted.events, ['open', ['write', 16384], ['write', 1], 'finish', 'drop-body']);
assert.equal(noBody.body, null); assert.equal(posted.resources.size, 0);

const reason = {abort: 'original'};
const result = Promise.withResolvers();
const retirement = Promise.withResolvers();
let cancelled = 0;
const pending = fixture({read() { return {result: result.promise, retired: retirement.promise,
  cancel() { cancelled++; result.reject(reason); }}; }});
const controller = new AbortController();
const pendingResponse = await pending.fetch('https://example.invalid/', {signal: controller.signal});
const streamReader = pendingResponse.body.getReader();
const reading = streamReader.read();
const rejection = assert.rejects(reading, value => value === reason);
await turns();
assert.equal(pending.events.at(-1), 'read');
controller.abort(reason);
await rejection;
await turns();
assert.equal(cancelled, 1);
assert.equal(pending.resources.size, 1);
assert.equal(pending.events.includes('drop-body'), false);
retirement.resolve();
await turns(32);
assert.equal(pending.resources.size, 0);
assert.equal(pending.events.at(-1), 'drop-body');

const primary = {network: 'failed'};
const cleanup = {native: 'ack-refused'};
const broken = fixture({write() { return {result: Promise.reject(primary), retired: Promise.reject(cleanup), cancel() {}}; }});
await assert.rejects(broken.fetch('https://example.invalid/', {method: 'POST', body: 'x'}),
  error => error instanceof TypeError && error.cause === primary);
assert.equal(broken.resources.size, 1);
assert.equal(broken.events.includes('drop-upload'), false);
await assert.rejects(broken.fetch('https://example.invalid/'),
  error => error.cause === cleanup && /cleanup-not-complete/.test(error.message));

for (const init of [{redirect: 'follow'}, {redirect: 'error'}]) {
  const redirect = fixture({status: 302});
  await assert.rejects(redirect.fetch('https://example.invalid/', init), TypeError);
  assert.equal(redirect.resources.size, 0);
}
const refused = fixture();
for (const [url, init] of [['file:///tmp/a', undefined], ['https://example.invalid/', {keepalive: true}],
  ['https://example.invalid/', {headers: {'X-Item': '\u00e9'}}],
  ...[{credentials: 'omit'}, {credentials: 'include'}, {mode: 'no-cors'}, {mode: 'same-origin'},
    {referrer: 'https://referrer.invalid/'}, {referrerPolicy: 'origin'}].map(init => ['https://example.invalid/', init])]) {
  await assert.rejects(refused.fetch(url, init), TypeError);
}
assert.deepEqual(refused.events, []);
