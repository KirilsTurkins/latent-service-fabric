import assert from 'node:assert/strict';
import {BodyState, bodyMethods, extractBody, maximumBodyBytes} from './http-body.mjs';
import {Headers} from './http-headers.mjs';

const states = new WeakMap();
const headers = new WeakMap();
class Candidate {
  constructor(input) {
    const extracted = extractBody(input);
    states.set(this, new BodyState(extracted.source));
    headers.set(this, new Headers(extracted.mediaType ? {'content-type': extracted.mediaType} : undefined));
  }
}
bodyMethods(Candidate.prototype, value => states.get(value), value => headers.get(value));
for (const input of [null, '', 'AÃ©ðŸ˜€\ud800', new Uint8Array([0, 1, 255]),
  new DataView(new Uint8Array([6, 7, 8]).buffer, 1), new URLSearchParams({a: 'Ã©', b: 'a b'}),
  new Blob(['blob text'], {type: 'text/plain'})]) {
  const actual = new Candidate(input);
  const expected = new Response(input);
  assert.equal(actual.bodyUsed, expected.bodyUsed);
  assert.equal(headers.get(actual).get('content-type'), expected.headers.get('content-type'));
  assert.deepEqual(await actual.bytes(), await expected.bytes());
  assert.equal(actual.bodyUsed, expected.bodyUsed);
  if (input !== null) {
    await assert.rejects(actual.text(), TypeError);
    await assert.rejects(expected.text(), TypeError);
  } else assert.equal(await actual.text(), await expected.text());
}
for (const input of ['invalid \ufffd text', '{"a":2}', new Blob(['x'], {type: 'application/octet-stream'})]) {
  for (const method of ['text', 'arrayBuffer', 'blob']) {
    const actual = await new Candidate(input)[method]();
    const expected = await new Response(input)[method]();
    if (method === 'blob') {
      assert.equal(actual.type, expected.type);
      assert.deepEqual(await actual.bytes(), await expected.bytes());
    } else assert.deepEqual(actual, expected);
  }
}
assert.deepEqual(await new Candidate('{"a":2}').json(), {a: 2});
await assert.rejects(new Candidate('broken').json(), SyntaxError);
const bytes = new Uint8Array([1, 2]);
const captured = new Candidate(bytes);
bytes[0] = 99;
assert.deepEqual(await captured.bytes(), new Uint8Array([1, 2]));
const locked = new Candidate('locked');
const reader = locked.body.getReader();
assert.equal(locked.bodyUsed, false);
await assert.rejects(locked.text(), TypeError);
assert.throws(() => states.get(locked).clone(), TypeError);
reader.releaseLock();
const clone = states.get(locked).clone();
assert.equal(new TextDecoder().decode(await clone.consume()), 'locked');
assert.equal(await locked.text(), 'locked');
const cancelled = new Candidate('cancelled');
await cancelled.body.cancel();
assert.equal(cancelled.bodyUsed, true);
await assert.rejects(cancelled.text(), TypeError);
assert.throws(() => extractBody(new Uint8Array(maximumBodyBytes + 1)), TypeError);
assert.throws(() => extractBody('Ã©'.repeat(maximumBodyBytes / 2 + 1)), TypeError);
assert.throws(() => extractBody(new ReadableStream()), /not-supported/);
