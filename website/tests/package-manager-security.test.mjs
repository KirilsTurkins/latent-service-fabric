import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {assertNat64Classification, ipAddressIntegrity, ipAddressVersion, replaceBundledIpAddress, verifyBundledIpAddress} from '../lib/package-manager-security.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lsf-npm-security-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const source = path.join(root, 'toolchain/node_modules/ip-address');
  const target = path.join(root, 'toolchain/node_modules/npm/node_modules/ip-address');
  for (const directory of [source, target]) fs.mkdirSync(path.join(directory, 'dist'), {recursive: true});
  const entry = {version: ipAddressVersion, resolved: `https://registry.npmjs.org/ip-address/-/ip-address-${ipAddressVersion}.tgz`, integrity: ipAddressIntegrity};
  const dependencies = {'ip-address': ipAddressVersion};
  fs.writeFileSync(path.join(root, 'toolchain/package.json'), JSON.stringify({dependencies}));
  fs.writeFileSync(path.join(root, 'toolchain/package-lock.json'), JSON.stringify({packages: {
    '': {dependencies}, 'node_modules/ip-address': entry, 'node_modules/npm/node_modules/ip-address': entry,
  }}));
  fs.writeFileSync(path.join(source, 'package.json'), JSON.stringify({name: 'ip-address', version: ipAddressVersion}));
  fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify({name: 'ip-address', version: '10.5.0'}));
  fs.writeFileSync(path.join(source, 'dist/ip-address.js'), '// Synthetic replacement, not an upstream implementation.\n');
  fs.writeFileSync(path.join(target, 'dist/ip-address.js'), '// Synthetic original bundle.\n');
  return {root, source, target};
}

test('bundle replacement copies all bytes, removes obsolete files and is idempotent', t => {
  const {root, source, target} = fixture(t);
  fs.writeFileSync(path.join(target, 'obsolete.js'), 'old');
  const sibling = path.join(path.dirname(target), 'unrelated.txt');
  fs.writeFileSync(sibling, 'preserve');
  fs.writeFileSync(path.join(root, 'toolchain/node_modules/.package-lock.json'), '{}');
  replaceBundledIpAddress(root);
  replaceBundledIpAddress(root);
  assert.deepEqual(fs.readFileSync(path.join(target, 'dist/ip-address.js')), fs.readFileSync(path.join(source, 'dist/ip-address.js')));
  assert.equal(fs.existsSync(path.join(target, 'obsolete.js')), false);
  assert.equal(fs.existsSync(path.join(root, 'toolchain/node_modules/.package-lock.json')), false);
  assert.equal(fs.readFileSync(sibling, 'utf8'), 'preserve');
});

test('missing pinned replacement fails without deleting the original', t => {
  const {root, source, target} = fixture(t);
  fs.rmSync(source, {recursive: true});
  assert.throws(() => replaceBundledIpAddress(root));
  assert.equal(JSON.parse(fs.readFileSync(path.join(target, 'package.json'))).version, '10.5.0');
});

test('an unexpected bundled version requires review', t => {
  const {root, target} = fixture(t);
  fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify({name: 'ip-address', version: '10.4.0'}));
  assert.throws(() => replaceBundledIpAddress(root), /Unexpected npm bundle/);
});

test('a stale vulnerable lock entry fails closed', t => {
  const {root} = fixture(t);
  const file = path.join(root, 'toolchain/package-lock.json');
  const lock = JSON.parse(fs.readFileSync(file));
  lock.packages['node_modules/npm/node_modules/ip-address'].version = '10.5.0';
  fs.writeFileSync(file, JSON.stringify(lock));
  assert.throws(() => replaceBundledIpAddress(root), /Unpatched lock entry/);
});

test('a changed integrity pin fails closed', t => {
  const {root} = fixture(t);
  const file = path.join(root, 'toolchain/package-lock.json');
  const lock = JSON.parse(fs.readFileSync(file));
  lock.packages['node_modules/ip-address'].integrity = 'sha512-unreviewed';
  fs.writeFileSync(file, JSON.stringify(lock));
  assert.throws(() => replaceBundledIpAddress(root));
});

test('replacement cannot follow a bundled directory symlink', t => {
  const {root, source, target} = fixture(t);
  fs.rmSync(target, {recursive: true});
  fs.symlinkSync(source, target, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => replaceBundledIpAddress(root), /Unsafe package directory/);
  assert.ok(fs.existsSync(path.join(source, 'package.json')));
});

test('replacement rejects symlinks inside the pinned package', t => {
  const {root, source} = fixture(t);
  fs.symlinkSync(path.join(source, 'dist'), path.join(source, 'linked'), process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => replaceBundledIpAddress(root), /Package symlink/);
});

test('the classifier regression rejects the vulnerable all-false behavior', () => {
  class Unclassified { isPrivate() { return false; } }
  assert.throws(() => assertNat64Classification(Unclassified), /GHSA-2vr4-cq9g-pvrc/);
});

test('installed npm passes the NAT64 advisory and control regressions', () => {
  const result = verifyBundledIpAddress(fileURLToPath(new URL('../', import.meta.url)));
  assert.equal(result.ipAddress, ipAddressVersion);
  assert.equal(result.classificationCases, 20);
});
