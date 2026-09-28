import assert from 'node:assert/strict';
import https from 'node:https';
import http from 'node:http';
import tls from 'node:tls';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';

const ca = await readFile('/etc/lsf/tls/server.pem');
const authority = 'frontend.example.test:18443';
let calls = 0;
const deadline = Date.now() + 45000;
function request(path, headers = {}, method = 'GET', options = {}) {
  assert.ok(++calls <= 48 && Date.now() < deadline);
  return new Promise((resolve, reject) => {
    const req = https.request({host: '127.0.0.1', port: 18443, servername: 'frontend.example.test', ca,
      rejectUnauthorized: true, agent: false, method, path, headers: {Host: authority, ...headers}, ...options}, res => {
      const chunks = []; let size = 0;
      res.on('data', block => { size += block.length; if (size > 8 * 1024 * 1024) req.destroy(new Error('body-bound')); else chunks.push(block); });
      res.on('error', reject);
      res.on('end', () => resolve({code: res.statusCode, headers: res.headers, body: Buffer.concat(chunks)}));
    });
    const timer = setTimeout(() => req.destroy(new Error('client-deadline')), 5000);
    req.on('close', () => clearTimeout(timer)); req.on('error', reject); req.end();
  });
}
function policy(value) {
  assert.equal(value.headers['strict-transport-security'], 'max-age=31536000');
  assert.equal(value.headers['x-content-type-options'], 'nosniff');
  assert.match(value.headers['content-security-policy'], /base-uri 'none'/);
  assert.equal(value.headers['cross-origin-resource-policy'], 'same-origin');
}

let initial;
for (let attempt = 0; attempt < 30; attempt++) {
  try { initial = await request('/'); break; }
  catch { await new Promise(resolve => setTimeout(resolve, 100)); }
}
assert.equal(initial?.code, 200); policy(initial);
const records = [];
for (const path of ['/', '/docs/guide/']) {
  const get = await request(path); const head = await request(path, {}, 'HEAD');
  assert.equal(get.code, 200); assert.equal(head.code, 200); assert.equal(head.body.length, 0);
  assert.equal(get.headers.etag, head.headers.etag); policy(get); policy(head);
  const unchanged = await request(path, {'If-None-Match': get.headers.etag});
  assert.equal(unchanged.code, 304); assert.equal(unchanged.body.length, 0); policy(unchanged);
  records.push({path, sha256: createHash('sha256').update(get.body).digest('hex'), etag: get.headers.etag});
}
const redirect = await request('/docs/guide');
assert.equal(redirect.code, 308); assert.equal(redirect.headers.location, '/docs/guide/'); policy(redirect);
assert.equal((await request('/', {Origin: 'https://' + authority, 'Sec-Fetch-Site': 'same-origin',
  'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'})).code, 200);
for (const headers of [{Origin: 'http://' + authority}, {Origin: 'https://foreign.example.test'},
  {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}]) {
  const response = await request('/', headers); assert.equal(response.code, 403); policy(response);
}
for (const headers of [{Host: 'foreign.example.test'}, {Forwarded: 'host=foreign.example.test;proto=http'},
  {'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': authority}, {'X-Lsf-Tenant': 'other'},
  {'X-Latent-Principal': 'administrator'}, {'X-Lsf-Deadline-Ms': '999999'}]) {
  const response = await request('/', headers); assert.equal(response.code, 400); policy(response);
}
assert.equal((await request('/__lsf/ready')).code, 400);
await assert.rejects(request('/', {}, 'GET', {servername: 'wrong.example.test'}));
await assert.rejects(request('/', {}, 'GET', {ca: undefined}));
// The direct untrusted loopback peer cannot bypass the edge. No forwarded value
// can change its socket identity; the connection may close before HTTP parsing.
await new Promise((resolve, reject) => {
  const req = http.get({host: '127.0.0.1', port: 18080, agent: false, path: '/',
    headers: {Host: authority, Forwarded: 'for=127.0.0.2;proto=https'}}, res => {
    res.resume(); res.on('end', () => res.statusCode === 200 ? reject(new Error('untrusted-peer-admitted')) : resolve());
  });
  req.setTimeout(1500, () => req.destroy()); req.on('error', resolve);
});
// Real TLS disconnects while incomplete headers and a response are in flight.
for (const bytes of ['GET / HTTP/1.1\r\nHost: ', 'GET / HTTP/1.1\r\nHost: ' + authority + '\r\nConnection: close\r\n\r\n']) {
  await new Promise((resolve, reject) => {
    const socket = tls.connect({host: '127.0.0.1', port: 18443, servername: 'frontend.example.test', ca}, () => {
      socket.write(bytes, () => socket.destroy());
    });
    socket.once('error', reject); socket.once('close', resolve);
  });
}
const probe = await new Promise((resolve, reject) => {
  const req = http.get({host: '127.0.0.1', port: 18181, agent: false, path: '/ready'}, res => {
    let body = ''; res.on('data', block => {body += block; assert.ok(body.length < 256);});
    res.on('end', () => resolve({code: res.statusCode, value: JSON.parse(body)}));
  });
  req.setTimeout(2000, () => req.destroy()); req.on('error', reject);
});
assert.equal(probe.code, 200); assert.equal(probe.value.status, 'ok');
console.log(JSON.stringify({schemaVersion: 'latent.local-edge-client.v1', passed: true, records, actualTlsVerified: true,
  wrongNameAndUntrustedCertificateDenied: true, untrustedPeerDenied: true, spoofedAuthorityDenied: true,
  originAndFetchMetadataPreserved: true, disconnects: 2, probePrivate: true, calls, cloudQualified: false}));
