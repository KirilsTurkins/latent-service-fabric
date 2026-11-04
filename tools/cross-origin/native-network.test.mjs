import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import test from 'node:test';
import {recordNetwork} from './native-network.mjs';

async function fixture(maximum) {
  const session = new EventEmitter(), observations = [], errors = [];
  session.send = async () => ({});
  const recorder = await recordNetwork(session, {origins: ['https://assets.example'], observations,
    scope: () => ({stage: 'allowed', case: 'test'}), fail: error => errors.push(error), maximum});
  const emit = (name, fields, requestId = '1') => session.emit('Network.' + name, {requestId, ...fields});
  return {emit, observations, errors, recorder, session};
}

test('raw null Origin and CORS denial survive out-of-order ExtraInfo', async () => {
  const {emit, observations, errors} = await fixture();
  emit('responseReceivedExtraInfo', {statusCode: 403, headers: {'Cache-Control': 'no-store'}});
  emit('requestWillBeSentExtraInfo', {headers: {Origin: 'null', 'Sec-Fetch-Mode': 'cors'}});
  emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'GET'}});
  emit('loadingFailed', {});
  assert.equal(observations.length, 1);
  assert.equal(observations[0].origin, 'null');
  assert.equal(observations[0].status, 403);
  assert.equal(observations[0].failed, true);
  assert.equal(observations[0].headers['cache-control'], 'no-store');
  assert.deepEqual(errors, []);
});

test('wire 304 is not replaced by the browser merged-cache 200', async () => {
  const {emit, observations} = await fixture();
  emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'GET', headers: {Origin: 'provisional'}}});
  emit('requestWillBeSentExtraInfo', {headers: {origin: 'https://caller.example'}});
  emit('responseReceivedExtraInfo', {statusCode: 304, headers: {ETag: '"same"'}});
  emit('responseReceived', {response: {status: 200, headers: {}}});
  assert.equal(observations[0].status, 304);
  assert.equal(observations[0].origin, 'https://caller.example');
});

test('a never-dispatched request does not invent wire headers or status', async () => {
  const {emit, observations} = await fixture();
  emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'PUT', headers: {Origin: 'null'}}});
  emit('loadingFailed', {});
  assert.equal(observations[0].requestHeadersObserved, undefined);
  assert.equal(observations[0].origin, undefined);
  assert.equal(observations[0].status, undefined);
});

test('request and response diagnostics discard credentials and unrelated headers', async () => {
  const {emit, observations} = await fixture();
  emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js?private-query', method: 'GET'}});
  emit('requestWillBeSentExtraInfo', {headers: {Origin: 'https://caller.example', Cookie: 'secret', Authorization: 'Bearer secret'}});
  emit('responseReceivedExtraInfo', {statusCode: 200, headers: {'Set-Cookie': 'secret', 'X-Private': 'secret', 'Access-Control-Allow-Origin': 'https://caller.example'}});
  assert.equal(observations[0].cookiePresent, true);
  assert.doesNotMatch(JSON.stringify(observations), /secret|private-query/);
});

test('finite observations and unmatched event ids fail closed', async () => {
  const {emit, observations, errors} = await fixture(1);
  for (const id of ['1', '2', '3']) emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'GET'}}, id);
  assert.equal(observations.length, 1);
  assert.equal(errors.length, 2);
});

test('other origins cannot supply evidence and redirects are rejected', async () => {
  const {emit, observations, errors} = await fixture();
  emit('requestWillBeSent', {request: {url: 'https://caller.example/', method: 'GET'}}, 'caller');
  const request = {url: 'https://assets.example/app.js', method: 'GET'};
  emit('requestWillBeSent', {request});
  emit('requestWillBeSent', {request});
  assert.equal(observations.length, 1);
  assert.equal(errors.length, 1);
});


test('all six ExtraInfo orderings preserve the same complete denied response', async () => {
  const messages = [
    ['requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'GET'}}],
    ['requestWillBeSentExtraInfo', {headers: {Origin: 'null', 'Sec-Fetch-Mode': 'cors'}}],
    ['responseReceivedExtraInfo', {statusCode: 403, headers: {'Cache-Control': 'no-store'}}],
  ];
  for (const order of [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]]) {
    const {emit, observations, errors, recorder} = await fixture();
    for (const index of order) emit(...messages[index]);
    assert.equal(observations[0].origin, 'null');
    assert.equal(observations[0].status, 403);
    assert.equal(observations[0].requestHeadersObserved, true);
    assert.equal(observations[0].responseHeadersObserved, true);
    assert.deepEqual(errors, []); recorder.close();
  }
});

test('ambiguous raw header spellings and non-scalar policy values cannot become evidence', async () => {
  for (const headers of [{Origin: 'null', origin: 'https://wrong.example'}, {Origin: ['null']}, {Origin: 1}]) {
    const {emit, observations, errors, recorder} = await fixture();
    emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'GET'}});
    emit('requestWillBeSentExtraInfo', {headers});
    assert.equal(observations[0].requestHeadersObserved, undefined);
    assert.match(errors[0].message, /ambiguous-wire-header/); recorder.close();
  }
});

test('duplicate ExtraInfo cannot overwrite an already captured denial', async () => {
  const {emit, observations, errors, recorder} = await fixture();
  emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'GET'}});
  emit('requestWillBeSentExtraInfo', {headers: {Origin: 'null'}});
  emit('responseReceivedExtraInfo', {statusCode: 403, headers: {'Cache-Control': 'no-store'}});
  emit('requestWillBeSentExtraInfo', {headers: {Origin: 'https://wrong.example'}});
  emit('responseReceivedExtraInfo', {statusCode: 200, headers: {'Access-Control-Allow-Origin': '*'}});
  assert.equal(observations[0].origin, 'null'); assert.equal(observations[0].status, 403);
  assert.equal(errors.length, 2); recorder.close();
});

test('a redirect into the observed origin cannot reuse earlier request evidence', async () => {
  const {emit, observations, errors, recorder} = await fixture();
  emit('requestWillBeSentExtraInfo', {headers: {Origin: 'https://wrong.example'}});
  emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'GET'}, redirectResponse: {status: 302}});
  assert.equal(observations.length, 0);
  assert.match(errors[0].message, /redirect-not-permitted/); recorder.close();
});

test('invalid response status and oversized selected metadata fail before publication', async () => {
  const inputs = [
    ['responseReceivedExtraInfo', {statusCode: 999, headers: {}}],
    ['responseReceivedExtraInfo', {statusCode: 403, headers: {Vary: 'x'.repeat(8193)}}],
    ['requestWillBeSentExtraInfo', {headers: {Origin: 'x'.repeat(8193)}}],
    ['requestWillBeSentExtraInfo', {headers: Object.fromEntries(Array.from({length: 129}, (_, i) => ['header' + i, 'x']))}],
  ];
  for (const [event, fields] of inputs) {
    const {emit, observations, errors, recorder} = await fixture();
    emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'GET'}});
    emit(event, fields);
    assert.equal(observations[0].status, undefined);
    assert.equal(observations[0].origin, undefined);
    assert.equal(errors.length, 1); recorder.close();
  }
});

test('identity and event count are bounded even when no native request is dispatched', async () => {
  const {emit, observations, errors, recorder, session} = await fixture(1);
  emit('loadingFailed', {}, 'x'.repeat(129));
  assert.match(errors[0].message, /request-id-size-bound/);
  for (let i = 0; i < 17; i++) emit('loadingFailed', {}, 'only-one-id');
  assert.match(errors.at(-1).message, /event-count-bound/);
  assert.deepEqual(session.eventNames(), []);
  assert.deepEqual(observations, []);
  await assert.rejects(recorder.flush(), /recorder-closed/);
});

test('invalid observation bounds cannot install listeners', async () => {
  for (const maximum of [0, -1, 1.5, 257, Infinity, NaN]) {
    const session = new EventEmitter(); session.send = async () => ({});
    await assert.rejects(recordNetwork(session, {origins: [], observations: [], scope: () => ({}),
      fail: assert.fail, maximum}), /observation-limit-bound/);
    assert.deepEqual(session.eventNames(), []);
  }
});

test('failed setup and explicit close release listeners without taking the caller session', async () => {
  const session = new EventEmitter(); session.send = async () => { throw new Error('setup-failed'); };
  await assert.rejects(recordNetwork(session, {origins: [], observations: [], scope: () => ({}),
    fail: assert.fail}), /setup-failed/);
  assert.deepEqual(session.eventNames(), []);
  const active = await fixture();
  active.recorder.close(); active.recorder.close();
  assert.deepEqual(active.session.eventNames(), []);
  active.emit('requestWillBeSent', {request: {url: 'https://assets.example/app.js', method: 'GET'}});
  assert.deepEqual(active.observations, []);
  await assert.rejects(active.recorder.waitFor(() => true, 'unused'), /recorder-closed/);
});
