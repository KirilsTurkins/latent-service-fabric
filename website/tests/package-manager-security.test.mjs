import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';

const root = fileURLToPath(new URL('../', import.meta.url));
const npmRequire = createRequire(path.join(root, 'toolchain/node_modules/npm/package.json'));
const socksRequire = createRequire(npmRequire.resolve('socks'));
const minimatchRequire = createRequire(npmRequire.resolve('minimatch'));
const fetchRequire = createRequire(npmRequire.resolve('make-fetch-happen'));
const {Address4, Address6} = socksRequire('ip-address');

function child(args) {
  const result = spawnSync(process.execPath, args, {encoding: 'utf8', timeout: 5000, maxBuffer: 64 * 1024});
  assert.ifError(result.error);
  assert.equal(result.signal, null);
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
}

test('npm consumes the exact prepared ip-address, Undici, brace-expansion and HTTP cache bundles', () => {
  const source = JSON.parse(fs.readFileSync(path.join(root, 'toolchain/source.json')));
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'toolchain/package-lock.json')));
  assert.equal(source.profile, 'npm-11.19.1-lsf-bundle-v2');
  assert.deepEqual(Object.fromEntries(source.patches.map(pin => [pin.name, pin.version])), {
    'ip-address': '10.7.2', undici: '6.28.1', 'brace-expansion': '5.0.12', 'http-cache-semantics': '4.3.0',
  });
  for (const pin of source.patches) {
    const location = `node_modules/npm/node_modules/${pin.name}`;
    const installed = JSON.parse(fs.readFileSync(path.join(root, 'toolchain', location, 'package.json')));
    assert.equal(installed.name, pin.name);
    assert.equal(installed.version, pin.version);
    assert.equal(lock.packages[location].version, pin.version);
    assert.equal(lock.packages[location].inBundle, true);
  }
  assert.equal(fs.realpathSync(socksRequire.resolve('ip-address')), fs.realpathSync(npmRequire.resolve('ip-address')));
  assert.equal(fs.realpathSync(minimatchRequire.resolve('brace-expansion')), fs.realpathSync(npmRequire.resolve('brace-expansion')));
  assert.equal(fs.realpathSync(fetchRequire.resolve('http-cache-semantics')), fs.realpathSync(npmRequire.resolve('http-cache-semantics')));
  assert.equal(npmRequire('balanced-match/package.json').version, '4.0.4');
});

test('npm cache honors no-store and must-revalidate with max-stale', {timeout: 5000}, async () => {
  const fetch = npmRequire('make-fetch-happen');
  const counts = new Map();
  const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'lsf-npm-cache-policy-'));
  const server = http.createServer((request, response) => {
    const count = (counts.get(request.url) ?? 0) + 1;
    counts.set(request.url, count);
    response.setHeader('cache-control', request.url === '/public'
      ? 'public, max-age=3600' : request.url === '/must-revalidate'
        ? 'max-age=0, must-revalidate' : 'no-store');
    response.end(String(count));
  });
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const origin = `http://127.0.0.1:${server.address().port}`;
    for (const route of ['/no-store', '/must-revalidate', '/public']) {
      const options = {cachePath: cache, retry: {retries: 0}, timeout: 1000};
      const first = await fetch(origin + route, options);
      assert.equal(first.status, 200);
      assert.equal(await first.text(), '1');
      const second = await fetch(origin + route, {...options,
        headers: {'cache-control': 'max-stale=999999'}});
      assert.equal(second.status, 200);
      assert.equal(await second.text(), route === '/public' ? '1' : '2', route);
      assert.equal(counts.get(route), route === '/public' ? 1 : 2, route);
    }
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(cache, {recursive: true, force: true});
  }
});

test('local-use NAT64 remains private without guessing its embedded IPv4 prefix', () => {
  for (const host of ['64:ff9b:1::', '64:ff9b:1:ffff:ffff:ffff:ffff:ffff',
    '64:ff9b:1:7f00:0:100::', '64:ff9b:1::7f00:1', '64:ff9b:1:a00:0:100::',
    '64:ff9b:1:a9fe:a9:fe00::', '64:ff9b:1:c0a8:1:100::', '64:ff9b:1::808:808',
    '64:ff9b:1:aa00:7f:0:100:0', '64:ff9b:1:abcd:7f:0:100:0',
    '0064:FF9B:0001:0000:0000:0000:7F00:0001']) {
    const address = new Address6(host);
    assert.equal(address.isPrivate(), true, host);
    assert.equal(address.isLoopback(), false, host);
    assert.equal(address.isLinkLocal(), false, host);
  }
  for (const host of ['64:ff9b:0:ffff:ffff:ffff:ffff:ffff', '64:ff9b:2::',
    '2606:4700:4700::1111', '64:ff9b::808:808']) {
    assert.equal(new Address6(host).isPrivate(), false, host);
  }
  assert.equal(new Address6('fd00::1').isPrivate(), true);
  assert.equal(new Address6('::ffff:127.0.0.1').isLoopback(), true);
  assert.equal(new Address6('64:ff9b::7f00:1').isLoopback(), true);
  assert.equal(new Address6('64:ff9b::a00:1').isPrivate(), true);
  assert.equal(new Address6('64:ff9b::a9fe:a9fe').isLinkLocal(), true);
});

test('subnet membership rejects cross-family inputs and bounds address parsing', () => {
  const v4 = new Address4('127.0.0.1');
  const v6 = new Address6('::1');
  assert.equal(v4.isInSubnet(v6), false);
  assert.equal(v6.isInSubnet(v4), false);
  assert.equal(v4.isInSubnet(new Address4('127.0.0.0/8')), true);
  assert.equal(v6.isInSubnet(new Address6('::1/128')), true);
  assert.throws(() => new Address4('1'.repeat(4096)), /at most 15 characters/);
  assert.throws(() => new Address6('1'.repeat(4096)), /at most 45 characters/);
});

test('npm brace expansion bounds chained parsing, deep nesting and repeated rewrites', () => {
  const output = child(['-e', `
    const assert = require('node:assert/strict');
    const path = require('node:path');
    const {createRequire} = require('node:module');
    const npmRequire = createRequire(path.join(process.argv[1], 'toolchain/node_modules/npm/package.json'));
    const minimatchRequire = createRequire(npmRequire.resolve('minimatch'));
    const {expand} = minimatchRequire('brace-expansion');
    const chained = '{' + '{a},'.repeat(8000) + 'z}';
    assert.equal(expand(chained, {max: 1, maxLength: 16384}).length, 1);
    const nested = '{'.repeat(4000) + 'a,b' + '}'.repeat(4000);
    assert.deepEqual(expand(nested), [nested]);
    const rewritten = '{a}' + '}'.repeat(64000) + ',z}';
    assert.deepEqual(expand(rewritten), [rewritten]);
    assert.deepEqual(expand('file-{a,b}.txt'), ['file-a.txt', 'file-b.txt']);
    console.log('bounded brace expansion and normal control passed');
  `, root]);
  assert.match(output, /bounded brace expansion and normal control passed/);
});

test('npm Undici survives oversized malformed decompression', () => {
  assert.match(child([path.join(root, 'scripts/test-undici-decompression.mjs')]),
    /bounded decompression and normal control passed/);
});
