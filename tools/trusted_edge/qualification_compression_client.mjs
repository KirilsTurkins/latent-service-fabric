import assert from 'node:assert/strict';
import https from 'node:https';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {gunzipSync} from 'node:zlib';

const ca = await readFile('/etc/lsf/tls/server.pem');
const inputs = JSON.parse(await readFile('/etc/lsf/compression.json', 'utf8'));
const mode = process.argv[2] ?? 'normal';
let calls = 0; const deadline = Date.now() + 45000;
const digest = bytes => 'sha256:' + createHash('sha256').update(bytes).digest('hex');
function request(path, encoding = 'gzip', headers = {}, method = 'GET') {
  assert.ok(++calls <= 64 && Date.now() < deadline);
  const begin = performance.now();
  return new Promise((resolve, reject) => {
    const req = https.request({host: '127.0.0.1', port: 18443, servername: 'frontend.example.test', ca,
      agent: false, method, path, headers: {Host: 'frontend.example.test:18443', 'Accept-Encoding': encoding, ...headers}}, res => {
      const chunks = []; let size = 0;
      res.on('data', block => {size += block.length; assert.ok(size <= 8 * 1024 * 1024 + 65536); chunks.push(block);});
      res.on('error', reject); res.on('end', () => resolve({code: res.statusCode, headers: res.headers,
        body: Buffer.concat(chunks), elapsedMillis: Math.round((performance.now() - begin) * 1000) / 1000}));
    });
    const timer = setTimeout(() => req.destroy(new Error('client-deadline')), 5000);
    req.on('close', () => clearTimeout(timer)); req.on('error', reject); req.end();
  });
}
function policy(result) {
  assert.match(result.headers.vary, /Accept-Encoding/i);
  assert.equal(result.headers['strict-transport-security'], 'max-age=31536000');
  assert.equal(result.headers['x-content-type-options'], 'nosniff');
  assert.match(result.headers['content-security-policy'], /script-src 'self'/);
}
const records = [];
if (mode === 'split-head') {
  assert.equal((await request(inputs[0].path, 'gzip', {}, 'HEAD')).code, 502);
  assert.equal((await request(inputs[0].path, 'gzip')).code, 200);
} else if (mode === 'revoked') {
  const savedTag = process.argv[3]; assert.match(savedTag, /^"edge-gzip-sha256-[a-f0-9]{64}"$/);
  for (const method of ['GET', 'HEAD']) {
    const result = await request(inputs[0].path, 'gzip', {'If-None-Match': savedTag}, method);
    assert.equal(result.code, 403); assert.notEqual(result.headers['content-encoding'], 'gzip');
    assert.equal(result.headers['cache-control'], 'no-store');
  }
  const damaged = await request('/beta/unread.js', 'gzip');
  assert.equal(damaged.code, 502); assert.notEqual(damaged.headers['content-encoding'], 'gzip');
  const other = await request(inputs[1].path, 'gzip');
  assert.equal(other.code, 200); assert.equal(digest(gunzipSync(other.body)), inputs[1].digest);
} else {
  for (const input of inputs) {
    const identity = await request(input.path, 'identity'), encoded = await request(input.path);
    assert.equal(identity.code, 200); assert.equal(encoded.code, 200); policy(identity); policy(encoded);
    assert.equal(digest(identity.body), input.digest); assert.equal(identity.body.length, input.size);
    assert.equal(digest(gunzipSync(encoded.body)), input.digest);
    assert.equal(encoded.headers['content-encoding'], 'gzip'); assert.equal(identity.headers['content-encoding'], undefined);
    assert.notEqual(identity.headers.etag, encoded.headers.etag);
    assert.ok(encoded.body.length < identity.body.length);
    const head = await request(input.path, 'gzip', {}, 'HEAD');
    assert.equal(head.code, 200); assert.equal(head.body.length, 0); assert.equal(head.headers.etag, encoded.headers.etag);
    assert.equal(Number(head.headers['content-length']), encoded.body.length);
    for (const method of ['GET', 'HEAD']) {
      const conditional = await request(input.path, 'gzip', {'If-None-Match': encoded.headers.etag}, method);
      assert.equal(conditional.code, 304); assert.equal(conditional.body.length, 0); policy(conditional);
      assert.equal(conditional.headers.etag, encoded.headers.etag); assert.equal(conditional.headers['content-encoding'], 'gzip');
      assert.equal((await request(input.path, 'gzip', {'If-None-Match': identity.headers.etag}, method)).code, 200);
      assert.equal((await request(input.path, 'gzip', {'If-Match': identity.headers.etag}, method)).code, 412);
      assert.equal((await request(input.path, 'gzip', {'If-Match': encoded.headers.etag}, method)).code, 200);
    }
    const timings = {identity: [identity.elapsedMillis], gzip: [encoded.elapsedMillis]};
    for (let i = 0; i < 2; i++) for (const encoding of ['identity', 'gzip']) {
      const sample = await request(input.path, encoding); assert.equal(sample.code, 200);
      timings[encoding].push(sample.elapsedMillis);
      assert.equal(sample.headers.etag, encoding === 'gzip' ? encoded.headers.etag : identity.headers.etag);
    }
    records.push({path: input.path, sourceDigest: input.digest, identityBytes: identity.body.length,
      gzipBytes: encoded.body.length, etag: encoded.headers.etag, requestMillis: timings});
  }
  assert.notEqual(records[0].etag, records[1].etag);
  for (const [value, code, encoding] of [['gzip;q=0.2,identity;q=0.1', 200, 'gzip'],
    ['*;q=0', 406, undefined], ['br,identity;q=0', 406, undefined], ['gzip;q=0', 200, undefined],
    ['gzip;q=1.5', 400, undefined], ['gzip,gzip', 400, undefined]]) {
    const result = await request(inputs[0].path, value); assert.equal(result.code, code);
    assert.equal(result.headers['content-encoding'], encoding);
  }
  for (const path of ['/alpha/missing.js', '/beta/missing.js']) assert.equal((await request(path)).code, 404);
  // Received encoded bytes have their own checksum and strong validator.
  const sample = await request(inputs[0].path), corrupted = Buffer.from(sample.body);
  corrupted[corrupted.length - 8] ^= 1; assert.throws(() => gunzipSync(corrupted));
  assert.notEqual(digest(corrupted), digest(sample.body));
}
console.log(JSON.stringify({schemaVersion: 'latent.edge-compression-client.v1', passed: true, mode,
  records, calls, actualNativeNode: true, actualTls: true, cloudQualified: false}));
