import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import path from 'node:path';

export const ipAddressVersion = '10.7.2';
export const ipAddressIntegrity = 'sha512-7H/2gFSIitxc0hG3nOI1glS8QLo/EHBFFLk8vEUjXY/xu0AdL8jZ9U1IzO2PUm0d2D/ofQcAifb0g6OBkt8U7w==';
export const undiciVersion = '6.28.1';
export const undiciIntegrity = 'sha512-zWpdTVD54H48CIybL0rWQ3ukpb9d23wM7eH5RtfdmeP70cWHNjtfo7P4vZX+5CoDcO53J4Pu5uXp7lNfjc6DRA==';
export const braceExpansionVersion = '5.0.12';
export const braceExpansionIntegrity = 'sha512-YovQ3rzhaLMIrDjNDMkNS01tea93qhEhG5xy8f6+R0l+dw3Ki+5sCoIoI942iuLZTHWogWktgwVDhU09iNEimQ==';
const ipAddress = Object.freeze({name: 'ip-address', version: ipAddressVersion, integrity: ipAddressIntegrity, previousVersions: ['10.5.0', '10.5.1']});
const undici = Object.freeze({name: 'undici', version: undiciVersion, integrity: undiciIntegrity, previousVersions: ['6.28.0']});
const braceExpansion = Object.freeze({name: 'brace-expansion', version: braceExpansionVersion, integrity: braceExpansionIntegrity, previousVersions: ['5.0.9']});
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

function inputs(websiteRoot, selected) {
  const {name, version, integrity} = selected;
  const sourceLocation = `node_modules/${name}`;
  const bundleLocation = `node_modules/npm/node_modules/${name}`;
  const root = directory(fs.realpathSync(websiteRoot), 'toolchain');
  const manifest = read(path.join(root, 'package.json'));
  const lock = read(path.join(root, 'package-lock.json'));
  assert.equal(manifest.dependencies[name], version);
  assert.equal(lock.packages[''].dependencies[name], version);
  for (const location of [sourceLocation, bundleLocation]) {
    const entry = lock.packages[location];
    assert.equal(entry.version, version, `Unpatched lock entry: ${location}`);
    assert.equal(entry.integrity, integrity);
    assert.equal(entry.resolved, `https://registry.npmjs.org/${name}/-/${name}-${version}.tgz`);
    assert.ok(!entry.inBundle, 'The replacement is separately integrity-pinned, not supplied by npm');
  }
  const source = directory(root, sourceLocation);
  const files = inventory(source);
  const actual = read(path.join(source, 'package.json'));
  assert.equal(actual.name, name);
  assert.equal(actual.version, version);
  return {root, source, files, bundleLocation};
}

// npm ci extracts bundled dependencies even when overrides or edited lock entries
// request another version. Install the reviewed replacement before running npm.
function replaceBundledDependency(websiteRoot, selected) {
  const {root, source, files, bundleLocation} = inputs(websiteRoot, selected);
  const target = directory(root, bundleLocation);
  const old = read(path.join(target, 'package.json'));
  assert.equal(old.name, selected.name);
  assert.ok([...selected.previousVersions, selected.version].includes(old.version), 'Unexpected npm bundle; review it before replacing it');
  const parent = path.dirname(target);
  const staged = fs.mkdtempSync(path.join(parent, `.${selected.name}-patched-`));
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

export function replaceBundledIpAddress(websiteRoot) {
  replaceBundledDependency(websiteRoot, ipAddress);
}

export function replaceBundledUndici(websiteRoot) {
  replaceBundledDependency(websiteRoot, undici);
}

export function replaceBundledBraceExpansion(websiteRoot) {
  replaceBundledDependency(websiteRoot, braceExpansion);
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
  const {root, files, bundleLocation} = inputs(websiteRoot, ipAddress);
  const target = directory(root, bundleLocation);
  assert.deepEqual(inventory(target), files, 'npm must contain the complete reviewed replacement, not the original bundle');
  const npmRequire = createRequire(path.join(root, 'node_modules/npm/package.json'));
  const socksRequire = createRequire(npmRequire.resolve('socks'));
  assert.equal(fs.realpathSync(socksRequire.resolve('ip-address')), fs.realpathSync(path.join(target, 'dist/ip-address.js')),
    'The real npm SOCKS dependency must load the patched bundled copy');
  const {Address4, Address6} = socksRequire('ip-address');
  const cases = assertNat64Classification(Address6);
  // GHSA-j6r3-76f7-8jcv: a subnet of the other family never contains the address.
  assert.equal(new Address4('127.0.0.1').isInSubnet(new Address6('::/0')), false);
  assert.equal(new Address6('::1').isInSubnet(new Address4('0.0.0.0/0')), false);
  // GHSA-h3mg-xc3c-68pw: reject length before running the address parser.
  assert.throws(() => new Address4('1'.repeat(4096)), {name: 'AddressError', message: /at most 15 characters/});
  assert.throws(() => new Address6(':'.repeat(4096)), {name: 'AddressError', message: /at most 45 characters/});
  return {advisory: 'GHSA-2vr4-cq9g-pvrc', ipAddress: ipAddressVersion, classificationCases: cases};
}

export function verifyBundledUndici(websiteRoot) {
  const {root, files, bundleLocation} = inputs(websiteRoot, undici);
  const target = directory(root, bundleLocation);
  assert.deepEqual(inventory(target), files, 'npm must contain the complete reviewed Undici replacement');
  const npmRequire = createRequire(path.join(root, 'node_modules/npm/package.json'));
  assert.equal(fs.realpathSync(npmRequire.resolve('undici')), fs.realpathSync(path.join(target, 'index.js')),
    'npm must resolve the patched bundled Undici, not another installed copy');
  assert.equal(npmRequire('undici/package.json').version, undiciVersion);
  assert.equal(typeof npmRequire('undici').fetch, 'function');
  return {undiciAdvisory: 'GHSA-3wwx-pv8p-q78v', undici: undiciVersion};
}

export function verifyBundledBraceExpansion(websiteRoot) {
  const {root, files, bundleLocation} = inputs(websiteRoot, braceExpansion);
  const target = directory(root, bundleLocation);
  assert.deepEqual(inventory(target), files, 'npm must contain the complete reviewed brace-expansion replacement');
  const npmRequire = createRequire(path.join(root, 'node_modules/npm/package.json'));
  const minimatchRequire = createRequire(npmRequire.resolve('minimatch'));
  assert.equal(fs.realpathSync(minimatchRequire.resolve('brace-expansion')), fs.realpathSync(path.join(target, 'dist/commonjs/index.js')),
    'The real npm minimatch dependency must load the patched bundled copy');
  const {expand} = minimatchRequire('brace-expansion');
  assert.deepEqual(expand('file-{a,b}-{1..2}.txt'), ['file-a-1.txt', 'file-a-2.txt', 'file-b-1.txt', 'file-b-2.txt']);
  assert.deepEqual(expand('{{{{a,b}}}}', {maxDepth: 2}), ['{{{{a,b}}}}']);
  assert.deepEqual(expand('{a}}},z}', {maxRewrites: 1}), ['{a}}},z}']);
  return {braceExpansion: braceExpansionVersion};
}
