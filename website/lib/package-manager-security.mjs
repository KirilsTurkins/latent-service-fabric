import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';

export const ipAddressVersion = '10.5.1';
export const ipAddressIntegrity = 'sha512-EXujUp9jyOI/chPgtqk6uy7fDq8AeCB/WlfEuPg9LN0fN9lzKAKfuDYi60SMhHwgUiEhZvVYsbGZN+RUU1INiA==';
const sourceLocation = 'node_modules/ip-address';
const bundleLocation = 'node_modules/npm/node_modules/ip-address';
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'));

function directory(root, relative) {
  let current = root;
  assert.ok(fs.lstatSync(current).isDirectory(), `Not a directory: ${current}`);
  for (const part of relative.split('/')) {
    current = path.join(current, part);
    const stat = fs.lstatSync(current);
    assert.ok(stat.isDirectory() && !stat.isSymbolicLink(), `Unsafe package directory: ${current}`);
  }
  return current;
}

function inventory(root) {
  const files = [];
  let bytes = 0;
  let entries = 0;
  function walk(relative = '', depth = 0) {
    assert.ok(depth <= 32, 'Package directory depth exceeds its bound');
    for (const name of fs.readdirSync(path.join(root, relative)).sort()) {
      assert.ok(++entries <= 2000, 'Package entry count exceeds its bound');
      const child = path.join(relative, name);
      const file = path.join(root, child);
      const stat = fs.lstatSync(file);
      assert.ok(!stat.isSymbolicLink(), `Package symlink is not allowed: ${child}`);
      if (stat.isDirectory()) { walk(child, depth + 1); continue; }
      assert.ok(stat.isFile(), `Non-regular package file: ${child}`);
      bytes += stat.size;
      assert.ok(files.length < 1000 && bytes <= 8 * 1024 * 1024, 'Package inventory exceeds its bound');
      files.push([child, createHash('sha256').update(fs.readFileSync(file)).digest('hex')]);
    }
  }
  walk();
  assert.ok(files.length > 0, 'Empty patched package');
  return files;
}

function inputs(websiteRoot) {
  const root = directory(fs.realpathSync(websiteRoot), 'toolchain');
  const manifest = read(path.join(root, 'package.json'));
  const lock = read(path.join(root, 'package-lock.json'));
  assert.equal(manifest.dependencies['ip-address'], ipAddressVersion);
  assert.equal(lock.packages[''].dependencies['ip-address'], ipAddressVersion);
  for (const location of [sourceLocation, bundleLocation]) {
    const entry = lock.packages[location];
    assert.equal(entry.version, ipAddressVersion, `Unpatched lock entry: ${location}`);
    assert.equal(entry.integrity, ipAddressIntegrity);
    assert.equal(entry.resolved, `https://registry.npmjs.org/ip-address/-/ip-address-${ipAddressVersion}.tgz`);
    assert.ok(!entry.inBundle, 'The replacement is separately integrity-pinned, not supplied by npm');
  }
  const source = directory(root, sourceLocation);
  const files = inventory(source);
  const actual = read(path.join(source, 'package.json'));
  assert.equal(actual.name, 'ip-address');
  assert.equal(actual.version, ipAddressVersion);
  return {root, source, files};
}

// npm ci extracts bundled dependencies even when overrides or edited lock entries
// request another version. Install the reviewed replacement before running npm.
export function replaceBundledIpAddress(websiteRoot) {
  const {root, source, files} = inputs(websiteRoot);
  const target = directory(root, bundleLocation);
  const old = read(path.join(target, 'package.json'));
  assert.equal(old.name, 'ip-address');
  assert.ok(['10.5.0', ipAddressVersion].includes(old.version), 'Unexpected npm bundle; review it before replacing it');
  const parent = path.dirname(target);
  const staged = fs.mkdtempSync(path.join(parent, '.ip-address-patched-'));
  try {
    fs.cpSync(source, staged, {recursive: true, errorOnExist: true, force: false});
    assert.deepEqual(inventory(staged), files);
    fs.rmSync(target, {recursive: true});
    fs.renameSync(staged, target);
  } finally {
    fs.rmSync(staged, {recursive: true, force: true});
  }
  // Do not let npm reuse an inventory of the original bundled package.
  for (const relative of ['node_modules/.package-lock.json', 'node_modules/npm/node_modules/.package-lock.json']) {
    fs.rmSync(path.join(root, relative), {force: true});
  }
  assert.deepEqual(inventory(target), files);
}

export function assertNat64Classification(Address6) {
  // The entire /48 is private. Its embedded IPv4 value cannot be inferred
  // without the operator's prefix length. These are classifiers, not an SSRF guard.
  const local = [
    '64:ff9b:1::', '64:ff9b:1:ffff:ffff:ffff:ffff:ffff',
    '64:ff9b:1:7f00:0:100::', '64:ff9b:1::7f00:1',
    '64:ff9b:1:a00:0:100::', '64:ff9b:1:a9fe:a9:fe00::',
    '64:ff9b:1:c0a8:1:100::', '64:ff9b:1::808:808',
    '64:ff9b:1:aa00:7f:0:100:0', '64:ff9b:1:abcd:7f:0:100:0',
    '0064:FF9B:0001:0000:0000:0000:7F00:0001',
  ];
  for (const host of local) {
    const address = new Address6(host);
    assert.equal(address.isPrivate(), true, `GHSA-2vr4-cq9g-pvrc: ${host}`);
    assert.equal(address.isLoopback(), false, `Do not guess the NAT64 prefix: ${host}`);
    assert.equal(address.isLinkLocal(), false, `Do not guess the NAT64 prefix: ${host}`);
  }
  for (const host of ['64:ff9b:0:ffff:ffff:ffff:ffff:ffff', '64:ff9b:2::', '2606:4700:4700::1111', '64:ff9b::808:808']) {
    assert.equal(new Address6(host).isPrivate(), false, `Unexpected classification outside local-use NAT64: ${host}`);
  }
  assert.equal(new Address6('fd00::1').isPrivate(), true);
  assert.equal(new Address6('::ffff:127.0.0.1').isLoopback(), true);
  assert.equal(new Address6('64:ff9b::7f00:1').isLoopback(), true);
  assert.equal(new Address6('64:ff9b::a00:1').isPrivate(), true);
  assert.equal(new Address6('64:ff9b::a9fe:a9fe').isLinkLocal(), true);
  return local.length + 9;
}

export function verifyBundledIpAddress(websiteRoot) {
  const {root, files} = inputs(websiteRoot);
  const target = directory(root, bundleLocation);
  assert.deepEqual(inventory(target), files, 'npm must contain the complete reviewed replacement, not the original bundle');
  const npmRequire = createRequire(path.join(root, 'node_modules/npm/package.json'));
  const socksRequire = createRequire(npmRequire.resolve('socks'));
  assert.equal(fs.realpathSync(socksRequire.resolve('ip-address')), fs.realpathSync(path.join(target, 'dist/ip-address.js')),
    'The real npm SOCKS dependency must load the patched bundled copy');
  const cases = assertNat64Classification(socksRequire('ip-address').Address6);
  return {advisory: 'GHSA-2vr4-cq9g-pvrc', ipAddress: ipAddressVersion, classificationCases: cases};
}
