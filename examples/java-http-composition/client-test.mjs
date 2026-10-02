import assert from 'node:assert/strict';
import { JavaDomainHttpClient } from './client.mjs';

const client = new JavaDomainHttpClient(process.argv[2]);
const status = await client.status();
assert.equal(status.status, 200);
const wide = status.value[0][0];
assert.equal(wide.sequence, '18446744073709551615');
assert.equal(wide.a, 'Grüße 😀');
const echo = await client.echo(wide);
assert.equal(echo.status, 200);
assert.deepEqual(echo.value, [wide]);
assert.deepEqual((await client.text('Grüße 😀\0')).value, ['Grüße 😀\0']);
assert.deepEqual((await client.items(['a', '😀'])).value, [['a', '😀']]);
const oversized = await client.text('x'.repeat(256 * 1024 + 1));
assert.ok([400, 413, 503].includes(oversized.status));
assert.equal((await client.status()).status, 200);
console.log(JSON.stringify({ schemaVersion: 'latent.java-http.generated-client.v1',
  status: 'passed', requests: 7, oversizedStatus: oversized.status,
  nodeVersion: process.version, fullWidthPreserved: true, freshAfterRejection: true }));
