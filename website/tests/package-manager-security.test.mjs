import assert from 'node:assert/strict';
import fs from 'node:fs';
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
const websiteRequire = createRequire(path.join(root, 'package.json'));
const {Address4, Address6} = socksRequire('ip-address');

function child(args) {
  const result = spawnSync(process.execPath, args, {encoding: 'utf8', timeout: 5000, maxBuffer: 64 * 1024});
  assert.ifError(result.error);
  assert.equal(result.signal, null);
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
}

test('npm consumes the exact prepared ip-address, Undici and brace-expansion bundles', () => {
  const source = JSON.parse(fs.readFileSync(path.join(root, 'toolchain/source.json')));
  const lock = JSON.parse(fs.readFileSync(path.join(root, 'toolchain/package-lock.json')));
  assert.equal(source.profile, 'npm-11.19.1-lsf-bundle-v3');
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

test('npm HTTP cache cannot reuse private or proxy-revalidated responses through max-stale', () => {
  const request = {url: 'https://cache.invalid/example', method: 'GET', headers: {host: 'cache.invalid'}};
  const stale = {...request, headers: {...request.headers, 'cache-control': 'max-stale=999999'}};
  for (const CachePolicy of [fetchRequire('http-cache-semantics'), websiteRequire('http-cache-semantics')]) {
    for (const headers of [
      {'cache-control': 'private, max-age=0'}, {'cache-control': 'no-store'},
      {'cache-control': 'max-age=0, proxy-revalidate'}, {'cache-control': 'max-age=0, must-revalidate'},
      {'cache-control': 'no-cache'}, {'cache-control': 'max-age=0', 'set-cookie': 'test-only=one'},
    ]) {
      const policy = new CachePolicy(request, {status: 200, headers}, {shared: true});
      assert.equal(policy.satisfiesWithoutRevalidation(stale), false, JSON.stringify(headers));
      assert.equal(policy.evaluateRequest(stale).response, undefined);
      assert.equal(policy.evaluateRequest(stale).revalidation.synchronous, true);
      const restored = CachePolicy.fromObject(policy.toObject());
      assert.equal(restored.satisfiesWithoutRevalidation(stale), false);
    }
    const publicPolicy = new CachePolicy(request, {status: 200, headers: {'cache-control': 'public, max-age=3600'}}, {shared: true});
    assert.equal(publicPolicy.satisfiesWithoutRevalidation(request), true);
  }
});

test('maintained HTTP cache preserves private caches, public freshness and allowed stale responses', () => {
  const request = {url: 'https://cache.invalid/example', method: 'GET', headers: {host: 'cache.invalid'}};
  for (const CachePolicy of [fetchRequire('http-cache-semantics'), websiteRequire('http-cache-semantics')]) {
    const privatePolicy = new CachePolicy(request, {status: 200, headers: {'cache-control': 'private, max-age=3600'}}, {shared: false});
    assert.equal(privatePolicy.satisfiesWithoutRevalidation(request), true);
    const publicCookie = new CachePolicy(request, {status: 200, headers: {'cache-control': 'public, max-age=3600', 'set-cookie': 'test-only=one'}}, {shared: true});
    assert.equal(publicCookie.satisfiesWithoutRevalidation(request), true);
    const policy = new CachePolicy(request, {status: 200, headers: {'cache-control': 'public, max-age=1', etag: '"test-only"'}}, {shared: true});
    const savedNow = policy.now();
    policy.now = () => savedNow + 2000;
    assert.equal(policy.satisfiesWithoutRevalidation(request), false);
    const stale = {...request, headers: {...request.headers, 'cache-control': 'max-stale=10'}};
    assert.equal(policy.satisfiesWithoutRevalidation(stale), true);
    assert.equal(policy.satisfiesWithoutRevalidation({...request, headers: {...request.headers, 'cache-control': 'no-cache, max-stale=10'}}), false);
    assert.equal(policy.satisfiesWithoutRevalidation({...stale, url: 'https://cache.invalid/other'}), false);
    assert.equal(policy.revalidationHeaders(request)['if-none-match'], '"test-only"');
  }
});

test('maintained braces preserves ordinary expansion, compile and stringify behavior', () => {
  const braces = websiteRequire('braces');
  assert.equal(websiteRequire('braces/package.json').version, '3.0.3');
  for (const [pattern, values] of [
    ['file-{a,b}.txt', ['file-a.txt', 'file-b.txt']], ['{1..3}', ['1', '2', '3']],
    ['{a..c}', ['a', 'b', 'c']], ['{a,{b,c}}', ['a', 'b', 'c']],
    ['{01..03}', ['01', '02', '03']], ['literal', ['literal']],
  ]) {
    assert.deepEqual(braces.expand(pattern), values, pattern);
    const ast = braces.parse(pattern);
    assert.equal(braces.stringify(ast), pattern);
    assert.equal(braces.compile(ast), braces.compile(pattern));
  }
  assert.equal(braces.compile('file-{a,b}.txt'), 'file-(a|b).txt');
});

test('maintained braces bounds parser nesting and every prebuilt AST walker before recursion', () => {
  const output = child(['-e', `
    const assert = require('node:assert/strict');
    const {createRequire} = require('node:module');
    const path = require('node:path');
    const braces = createRequire(path.join(process.argv[1], 'package.json'))('braces');
    for (const [open, close] of [['{', '}'], ['(', ')']]) {
      const pattern = open.repeat(4000) + 'a,b' + close.repeat(4000);
      assert.ok(pattern.length < 65536);
      assert.throws(() => braces.parse(pattern), {name: 'RangeError', message: /maintained limit/});
      assert.throws(() => braces(pattern), {name: 'RangeError', message: /maintained limit/});
    }
    const ast = {type: 'root', nodes: []};
    let node = ast;
    for (let i = 0; i < 4000; i++) { const next = {type: 'brace', nodes: []}; node.nodes.push(next); node = next; }
    node.nodes.push({type: 'text', value: 'a'});
    const wide = {type: 'root', nodes: Array.from({length: 65536}, () => ({type: 'text', value: 'a'}))};
    const cycle = {type: 'root', nodes: []}; cycle.nodes.push(cycle);
    for (const walk of [braces.compile, braces.expand, braces.stringify]) {
      for (const input of [ast, wide, cycle]) {
        assert.throws(() => walk(input), {name: 'RangeError', message: /maintained limit/});
      }
    }
    assert.deepEqual(braces.expand('{a,b}'), ['a', 'b']);
    console.log('parser and all AST walkers remained bounded and usable');
  `, root]);
  assert.match(output, /parser and all AST walkers remained bounded and usable/);
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
