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
  return {emit, observations, errors, recorder};
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
