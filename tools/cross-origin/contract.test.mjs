import assert from 'node:assert/strict';
import test from 'node:test';
import {canonicalOrigin, configuration, decide} from './contract.mjs';

const row = {authority: 'assets.example', tenant: 'example', publication: 'publication:sha256:' + 'a'.repeat(64),
  origins: ['https://portal.example'], credentials: 'omit'};
const request = {authority: row.authority, tenant: row.tenant, publication: row.publication,
  eligible: true, method: 'GET', headers: {origin: row.origins[0], 'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'cross-site', 'sec-fetch-dest': 'empty'}};

test('canonical exact origins and finite closed configuration', () => {
  for (const invalid of ['null', 'https://portal.example/', 'https://PORTAL.example',
    'https://portal.example:443', 'https://u:p@portal.example', 'http://portal.example',
    'https://portal.example https://other.example', 'https://*.example', ' https://portal.example']) assert.equal(canonicalOrigin(invalid), false);
  assert.deepEqual(configuration([row]), [row]);
  for (const rows of [[row, row], Array(33).fill(row), [{...row, origins: Array(17).fill(row.origins[0])}],
    [{...row, origins: []}], [{...row, credentials: '*'}], [{...row, extension: true}]]) {
    assert.throws(() => configuration(rows));
  }
  const many = Array.from({length: 32}, (_, index) => ({...row,
    publication: 'publication:sha256:' + index.toString(16).padStart(64, '0'),
    origins: Array.from({length: 16}, (_, origin) => `https://${origin}.${('a'.repeat(60) + '.').repeat(3)}example`)}));
  assert.throws(() => configuration(many), /configuration byte ceiling/);
});

test('selection, lifecycle and method remain authority boundaries', () => {
  const rows = configuration([row]);
  assert.equal(decide(rows, request).status, 200);
  assert.equal(decide([], request).status, 403);
  for (const patch of [{tenant: 'other'}, {publication: 'publication:sha256:' + 'b'.repeat(64)},
    {authority: 'other.example'}, {eligible: false}, {document: true}, {application: true}, {method: 'POST'}]) {
    const decision = decide(rows, {...request, ...patch});
    assert.equal(decision.status, 403);
    assert.equal(decision.headers['access-control-allow-origin'], undefined);
  }
  for (const patch of [{origin: 'null'}, {origin: row.origins[0] + ', ' + row.origins[0]},
    {authorization: 'Bearer platform-token'}, {cookie: 'session=opaque'}, {'sec-fetch-mode': 'no-cors'},
    {'sec-fetch-dest': 'document'}, {'access-control-request-method': 'GET'}, {'content-length': '1'},
    {'transfer-encoding': 'chunked'}]) {
    assert.equal(decide(rows, {...request, headers: {...request.headers, ...patch}}).status, 403);
  }
});

test('preflight permits bounded conditional reads and never credentials or writes', () => {
  const rows = configuration([row]);
  const preflight = {...request, method: 'OPTIONS', headers: {...request.headers,
    'access-control-request-method': 'GET', 'access-control-request-headers': 'if-none-match'}};
  assert.equal(decide(rows, preflight).status, 204);
  for (const patch of [{'access-control-request-method': 'POST'},
    {'access-control-request-headers': 'authorization'}, {'access-control-request-headers': 'x-tenant'},
    {'access-control-request-headers': 'if-none-match, if-none-match'}, {cookie: 'session=opaque'}]) {
    assert.equal(decide(rows, {...preflight, headers: {...preflight.headers, ...patch}}).status, 403);
  }
});
