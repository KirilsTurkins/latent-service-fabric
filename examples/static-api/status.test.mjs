import assert from 'node:assert/strict';
import {test} from 'node:test';
import {handle} from './capsule/status.ts';

const request = (extra = {}) => ({profile: 'buffered-v1', method: 'get', path: '/api/status',
  query: undefined, headers: [], bodyBase64: '', ...extra});

test('public response exposes only fixed availability and HEAD length', () => {
  const peer = () => ({tag: 'ok', val: {status: 200, body: 'private data', headers: [{name: 'set-cookie', value: 'secret'}]}});
  const response = handle(request(), peer);
  assert.equal(Buffer.from(response.bodyBase64, 'base64').toString(), '{"status":"available"}');
  assert.deepEqual(response.headers.map(header => header.name), ['cache-control']);
  const head = handle(request({method: 'head'}), peer);
  assert.equal(head.bodyBase64, '');
  assert.equal(head.representationLength, BigInt(Buffer.from(response.bodyBase64, 'base64').length));
});

test('unknown API paths, methods and destination selectors never dispatch', () => {
  const forbidden = () => {throw new Error('unexpected upstream call');};
  for (const path of ['/api', '/api/unknown', '/api/status/other']) assert.equal(handle(request({path}), forbidden).status, 404);
  for (const method of ['post', 'put', 'patch', 'delete', 'options']) assert.equal(handle(request({method}), forbidden).status, 405);
  for (const query of ['', 'url=https://another.invalid/', 'customer=other']) assert.equal(handle(request({query}), forbidden).status, 400);
  for (const name of ['authorization', 'proxy-authorization', 'forwarded', 'x-forwarded-host',
    'x-lsf-principal', 'x-tenant', 'x-customer', 'x-upstream-url', 'X-Target']) {
    assert.equal(handle(request({headers: [{name, value: new Uint8Array()}]}), forbidden).status, 403);
  }
});

test('denial, redirects, deadline, exhaustion and uncertain effects have no replay', () => {
  const cases = [
    [{tag: 'ok', val: {status: 302}}, 502], [{tag: 'ok', val: {status: 500}}, 502],
    ...['permission-denied', 'tls-failed', 'connection-failed', 'unavailable', 'uncertain']
      .map(tag => [{tag: 'err', val: {tag}}, 502]),
    [{tag: 'err', val: {tag: 'deadline-exceeded'}}, 504],
    [{tag: 'err', val: {tag: 'cancelled'}}, 504], [{tag: 'err', val: {tag: 'budget-exhausted'}}, 503],
  ];
  for (const [result, status] of cases) {
    let calls = 0;
    const response = handle(request(), () => {calls++; return result;});
    assert.equal(response.status, status);
    assert.equal(calls, 1);
    assert.equal(response.bodyBase64, Buffer.from(Buffer.from(response.bodyBase64, 'base64')).toString('base64'));
  }
});
