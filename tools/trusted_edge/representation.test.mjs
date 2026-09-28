import assert from 'node:assert/strict';
import test from 'node:test';
import {gunzipSync} from 'node:zlib';
import {encoding, tags, conditionalCode, conditions, transform, vary} from './representation.mjs';

test('bounded negotiation honors explicit qualities, wildcard and identity exclusions', () => {
  for (const [value, expected] of [[undefined, 'identity'], ['', 'identity'], ['gzip', 'gzip'],
    ['GZip ; q=1.000', 'gzip'], ['gzip;q=0.5', 'identity'], ['gzip;q=0.5,identity;q=0.2', 'gzip'],
    ['*', 'gzip'], ['*;q=0', null], ['br, identity;q=0', null], ['br, *;q=0.8,identity;q=0', 'gzip'],
    ['gzip;q=0,*', 'identity'], ['gzip;q=0,identity;q=0', null], ['gzip;q=0.001, identity;q=0', 'gzip'],
    ['*;q=0,identity;q=1', 'identity']]) assert.equal(encoding(value), expected, String(value));
  for (const value of ['gzip;q=.5', 'gzip;q=1.1', 'gzip;q=0.1234', 'gzip,', ',gzip', 'gzip,gzip',
    'gzip;level=6', 'gzip;q=-1', 'gzip;q=1;q=1', 'gzip\ngzip', 'x'.repeat(513),
    Array.from({length: 17}, (_, i) => 'encoding' + i).join(',')]) assert.throws(() => encoding(value), value);
});

test('conditional requests compare the selected strong representation with correct precedence', () => {
  const tag = '"gzip-value"';
  for (const [headers, code] of [[{}, 200], [{'if-match': '*'}, 200], [{'if-none-match': '*'}, 304],
    [{'if-match': tag}, 200], [{'if-match': 'W/' + tag}, 412], [{'if-none-match': 'W/' + tag}, 304],
    [{'if-none-match': '"identity-value"'}, 200], [{'if-match': '"identity-value"', 'if-none-match': '*'}, 412],
    [{'if-none-match': '"a,b", W/' + tag}, 304]]) assert.equal(conditionalCode(tag, conditions(headers)), code);
  for (const value of ['', '*, "x"', '"x",', '"x" "y"', 'w/"x"', '"x\nx"', '"' + 'a'.repeat(129) + '"',
    Array(17).fill('"x"').join(',')]) assert.throws(() => tags(value));
  for (const name of ['range', 'if-range', 'if-modified-since', 'if-unmodified-since']) {
    assert.throws(() => conditions({[name]: 'anything'}));
  }
  assert.equal(vary({vary: 'Origin'}).vary, 'Origin, Accept-Encoding');
  assert.equal(vary({vary: 'accept-encoding'}).vary, 'accept-encoding');
});

test('actual bounded gzip preserves input and gives encoded bytes and media separate validators', async () => {
  const bytes = Buffer.from('export const message = "bounded immutable source";\n'.repeat(4096));
  const original = Buffer.from(bytes), a = await transform(bytes, 'text/javascript');
  const b = await transform(bytes, 'text/javascript'), other = await transform(bytes, 'text/plain');
  assert.deepEqual(bytes, original); assert.deepEqual(gunzipSync(a.bytes), original);
  assert.ok(a.bytes.length < bytes.length); assert.equal(a.etag, b.etag); assert.notEqual(a.etag, other.etag);
  assert.match(a.etag, /^"edge-gzip-sha256-[0-9a-f]{64}"$/);
  const corrupt = Buffer.from(a.bytes); corrupt[corrupt.length - 8] ^= 1;
  assert.throws(() => gunzipSync(corrupt));
  await assert.rejects(transform(Buffer.alloc(8 * 1024 * 1024 + 1), 'text/javascript'));
});
