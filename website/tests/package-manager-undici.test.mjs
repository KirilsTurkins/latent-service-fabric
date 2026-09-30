import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {replaceBundledUndici, verifyBundledUndici, undiciVersion, undiciIntegrity} from '../lib/package-manager-security.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lsf-undici-security-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const source = path.join(root, 'toolchain/node_modules/undici');
  const target = path.join(root, 'toolchain/node_modules/npm/node_modules/undici');
  for (const directory of [source, target]) fs.mkdirSync(directory, {recursive: true});
  const entry = {version: undiciVersion, integrity: undiciIntegrity,
    resolved: `https://registry.npmjs.org/undici/-/undici-${undiciVersion}.tgz`};
  const dependencies = {undici: undiciVersion};
  fs.writeFileSync(path.join(root, 'toolchain/package.json'), JSON.stringify({dependencies}));
  const lockFile = path.join(root, 'toolchain/package-lock.json');
  const lock = {packages: {'': {dependencies}, 'node_modules/undici': {...entry},
    'node_modules/npm/node_modules/undici': {...entry}}};
  fs.writeFileSync(lockFile, JSON.stringify(lock));
  fs.writeFileSync(path.join(source, 'package.json'), JSON.stringify({name: 'undici', version: undiciVersion}));
  fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify({name: 'undici', version: '6.28.0'}));
  fs.writeFileSync(path.join(source, 'index.js'), '// Synthetic patched package.');
  fs.writeFileSync(path.join(target, 'index.js'), '// Synthetic original.');
  return {root, source, target, lock, lockFile};
}

test('Undici replacement is complete, idempotent and preserves siblings', t => {
  const {root, source, target} = fixture(t);
  fs.writeFileSync(path.join(target, 'obsolete.js'), 'stale');
  const sibling = path.join(path.dirname(target), 'ip-address');
  fs.mkdirSync(sibling);
  fs.writeFileSync(path.join(sibling, 'preserve.txt'), 'preserve');
  replaceBundledUndici(root);
  replaceBundledUndici(root);
  assert.deepEqual(fs.readFileSync(path.join(target, 'index.js')), fs.readFileSync(path.join(source, 'index.js')));
  assert.equal(fs.existsSync(path.join(target, 'obsolete.js')), false);
  assert.equal(fs.readFileSync(path.join(sibling, 'preserve.txt'), 'utf8'), 'preserve');
});

test('Undici replacement rejects stale locks and changed integrity before mutation', t => {
  const {root, target, lock, lockFile} = fixture(t);
  for (const location of ['node_modules/undici', 'node_modules/npm/node_modules/undici']) {
    for (const [field, value] of [['version', '6.28.0'], ['integrity', 'sha512-unreviewed']]) {
      const changed = structuredClone(lock);
      changed.packages[location][field] = value;
      fs.writeFileSync(lockFile, JSON.stringify(changed));
      assert.throws(() => replaceBundledUndici(root));
      assert.equal(JSON.parse(fs.readFileSync(path.join(target, 'package.json'))).version, '6.28.0');
    }
  }
});

test('Undici replacement rejects a missing source without removing the bundle', t => {
  const {root, source, target} = fixture(t);
  fs.rmSync(source, {recursive: true});
  assert.throws(() => replaceBundledUndici(root));
  assert.equal(JSON.parse(fs.readFileSync(path.join(target, 'package.json'))).version, '6.28.0');
});

test('Undici replacement rejects an unexpected bundled version', t => {
  const {root, target} = fixture(t);
  fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify({name: 'undici', version: '6.27.0'}));
  assert.throws(() => replaceBundledUndici(root), /Unexpected npm bundle/);
});

test('Undici replacement cannot follow a bundled directory symlink', t => {
  const {root, source, target} = fixture(t);
  fs.rmSync(target, {recursive: true});
  fs.symlinkSync(source, target, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => replaceBundledUndici(root), /Unsafe package directory/);
  assert.ok(fs.existsSync(path.join(source, 'index.js')));
});

test('installed npm resolves the complete patched Undici', () => {
  assert.equal(verifyBundledUndici(fileURLToPath(new URL('../', import.meta.url))).undici, undiciVersion);
});

test('the actual npm Undici survives oversized malformed decompression', () => {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL('../scripts/test-undici-decompression.mjs', import.meta.url))],
    {encoding: 'utf8', timeout: 5000, maxBuffer: 64 * 1024});
  assert.ifError(result.error);
  assert.equal(result.signal, null);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /bounded decompression and normal control passed/);
});
