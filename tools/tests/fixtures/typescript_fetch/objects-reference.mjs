import assert from 'node:assert/strict';
import {Request as CandidateRequest, Response as CandidateResponse, responseFromNative, isNativeResponse} from './http-objects.mjs';
import {NativeBodyReader} from './http-body.mjs';

for (const options of [{}, {method: 'post', body: 'text'}, {method: 'patch', body: new Uint8Array([1, 2])},
  {method: 'DELETE', headers: {'X-Test': 'value'}, credentials: 'omit', cache: 'no-store', redirect: 'manual'},
  {method: null}, {integrity: null}, {signal: null}]) {
  const input = 'https://example.invalid/a?q=Ã©#fragment';
  const actual = new CandidateRequest(input, options);
  const expected = new Request(input, options);
  for (const key of ['url', 'method', 'mode', 'cache', 'credentials', 'redirect', 'referrer',
    'referrerPolicy', 'integrity', 'keepalive', 'destination', 'duplex', 'bodyUsed']) {
    assert.equal(actual[key], expected[key], key);
  }
  assert.deepEqual([...actual.headers], [...expected.headers]);
  assert.equal(actual.signal.aborted, expected.signal.aborted);
  assert.equal(Object.prototype.toString.call(actual), '[object Request]');
  assert.deepEqual(await actual.bytes(), await expected.bytes());
  assert.equal(actual.bodyUsed, expected.bodyUsed);
}
for (const options of [{method: 'CONNECT'}, {method: 'bad method'}, {method: 'GET', body: 'x'},
  {method: 'PUT', mode: 'no-cors'}, {mode: 'navigate'}, {cache: 'only-if-cached'},
  {credentials: 'wrong'}, {redirect: 'wrong'}, {signal: {}}, {headers: null}, {duplex: 'full'}]) {
  assert.throws(() => new CandidateRequest('https://example.invalid', options), TypeError);
  assert.throws(() => new Request('https://example.invalid', options), TypeError);
}
for (const input of ['https://name:password@example.invalid', 'relative/path']) {
  assert.throws(() => new CandidateRequest(input), TypeError);
  assert.throws(() => new Request(input), TypeError);
}
const original = new CandidateRequest('https://example.invalid', {method: 'POST', body: 'copy'});
const copied = original.clone();
assert.equal(original.bodyUsed, false);
assert.equal(await original.text(), 'copy');
assert.equal(await copied.text(), 'copy');
assert.throws(() => original.clone(), TypeError);
const before = new CandidateRequest('https://example.invalid', {method: 'POST', body: 'transfer'});
assert.throws(() => new CandidateRequest(before, {credentials: 'wrong'}), TypeError);
assert.equal(before.bodyUsed, false);
const moved = new CandidateRequest(before);
assert.equal(before.bodyUsed, true);
assert.equal(before.body.locked, true);
assert.equal(await moved.text(), 'transfer');
assert.throws(() => new CandidateRequest(before), TypeError);
const controller = new AbortController();
const signalRequest = new CandidateRequest('https://example.invalid', {signal: controller.signal});
const signalClone = signalRequest.clone();
const reason = {original: 'signal'};
controller.abort(reason);
assert.equal(signalRequest.signal.reason, reason);
assert.equal(signalClone.signal.reason, reason);

for (const status of [200, 201.9, 299, 400, 503, 65536 + 202]) {
  const actual = new CandidateResponse('text', {status, statusText: 'OK'});
  const expected = new Response('text', {status, statusText: 'OK'});
  for (const key of ['status', 'statusText', 'ok', 'type', 'url', 'redirected', 'bodyUsed']) {
    assert.equal(actual[key], expected[key], key);
  }
  assert.deepEqual([...actual.headers], [...expected.headers]);
  const clone = actual.clone();
  assert.equal(await actual.text(), await expected.text());
  assert.equal(await clone.text(), 'text');
  assert.throws(() => actual.clone(), TypeError);
}
// Web IDL's unsigned-short modulo is positive, including negative inputs.
assert.equal(new CandidateResponse(null, {status: -65334}).status, 202);
for (const status of [100, 199, 600, null, false, NaN, Infinity]) {
  assert.throws(() => new CandidateResponse(null, {status}), RangeError);
  assert.throws(() => new Response(null, {status}), RangeError);
}
for (const options of [{statusText: '\u0001'}, {statusText: Symbol()}, {status: 204}]) {
  assert.throws(() => new CandidateResponse('x', options), TypeError);
  assert.throws(() => new Response('x', options), TypeError);
}
assert.throws(() => new CandidateResponse(null, {status: 200n}), TypeError);
for (const status of [204, 205, 304]) assert.equal(new CandidateResponse(null, {status}).body, null);
const error = CandidateResponse.error();
assert.equal(error.status, 0);
assert.equal(error.type, 'error');
assert.equal(error.ok, false);
assert.equal(error.body, null);
assert.throws(() => error.headers.set('x', 'y'), TypeError);
assert.throws(() => error.clone().headers.set('x', 'y'), TypeError);
const redirect = CandidateResponse.redirect('https://example.invalid/Ã©', 307);
assert.equal(redirect.status, 307);
assert.equal(redirect.headers.get('location'), Response.redirect('https://example.invalid/Ã©', 307).headers.get('location'));
assert.throws(() => CandidateResponse.redirect('https://example.invalid', 200), RangeError);
assert.throws(() => redirect.clone().headers.append('x', 'y'), TypeError);
const json = CandidateResponse.json({result: 42}, {status: 202});
assert.equal(json.headers.get('content-type'), 'application/json');
assert.equal(json.status, 202);
assert.deepEqual(await json.json(), {result: 42});
assert.throws(() => CandidateResponse.json(undefined), TypeError);

let closes = 0;
const native = () => new NativeBodyReader({
  read() { return {result: Promise.resolve(undefined), retired: Promise.resolve(), cancel() {}}; },
  materialize() { throw new Error('EOF-has-no-chunk'); }, dropChunk() {}, dropBody() { closes++; },
});
const response = responseFromNative({status: 503, headers: [], url: 'https://example.invalid/a'}, native());
assert.equal(isNativeResponse(response),true); // Pure header projection needs no async cleanup frame.
assert.equal(isNativeResponse({}),false);
assert.equal(response.status, 503); // HTTP failure status remains a Response.
assert.equal(response.ok, false);
assert.equal(response.url, 'https://example.invalid/a');
assert.equal(closes, 0); // Header success does not eagerly consume a body.
assert.throws(() => response.headers.append('x', 'y'), TypeError);
assert.throws(() => response.clone(), /not-supported/);
assert.equal(await response.text(), '');
assert.equal(closes, 1);
const empty = await responseFromNative({status: 204, headers: [], url: 'https://example.invalid'}, native());
assert.equal(empty.body, null);
assert.equal(closes, 2); // Close the real body before exposing a bodyless status.
await assert.rejects(responseFromNative({status: 200, headers: [{name: 'bad name', value: 'x'}],
  url: 'https://example.invalid'}, native()), TypeError);
assert.equal(closes, 3); // Malformed metadata still owns its body cleanup.
