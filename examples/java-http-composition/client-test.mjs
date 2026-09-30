import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {JavaHttpClient: JavaDomainHttpClient} = await import(pathToFileURL(process.argv[3]).href);

const client = new JavaDomainHttpClient(process.argv[2]);
const status = await client.status();
assert.equal(status.status, 200);
const wide = status.value[0][0];
assert.equal(wide.sequence, '18446744073709551615');
assert.equal(wide.a, 'GrÃ¼ÃŸe ðŸ˜€');
const echo = await client.echo(wide);
assert.equal(echo.status, 200);
assert.deepEqual(echo.value, [wide]);
const nested = {value: wide, optional: {some: wide}, labels: ['Gr??e ??']};
assert.deepEqual((await client.nested(nested)).value, [nested]);
assert.deepEqual((await client.text('GrÃ¼ÃŸe ðŸ˜€\0')).value, ['GrÃ¼ÃŸe ðŸ˜€\0']);
assert.deepEqual((await client.items(['a', 'ðŸ˜€'])).value, [['a', 'ðŸ˜€']]);
await assert.rejects(() => client.text('x'.repeat(256 * 1024 + 1)), TypeError);
await assert.rejects(() => client.echo({...wide, sequence: 18446744073709551615}), TypeError);
await assert.rejects(() => client.echo({...wide, sequence: '18446744073709551616'}), TypeError);
assert.equal(client.privateAdmin, undefined);
assert.equal((await client.fail()).status, 422);
assert.equal((await client.throwError()).status, 500);
assert.equal((await client.status()).status, 200);
console.log(JSON.stringify({ schemaVersion: 'latent.java-http.generated-client.v1',
  status: 'passed', requests: 8, clientOverLimitRejected: true,
  nodeVersion: process.version, fullWidthPreserved: true, freshAfterRejection: true }));
