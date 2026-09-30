import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {braceExpansionIntegrity, braceExpansionVersion, replaceBundledBraceExpansion, verifyBundledBraceExpansion} from '../lib/package-manager-security.mjs';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lsf-brace-security-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const source = path.join(root, 'toolchain/node_modules/brace-expansion');
  const target = path.join(root, 'toolchain/node_modules/npm/node_modules/brace-expansion');
  for (const directory of [source, target]) fs.mkdirSync(directory, {recursive: true});
  const entry = {version: braceExpansionVersion, integrity: braceExpansionIntegrity,
    resolved: `https://registry.npmjs.org/brace-expansion/-/brace-expansion-${braceExpansionVersion}.tgz`};
  const dependencies = {'brace-expansion': braceExpansionVersion};
  fs.writeFileSync(path.join(root, 'toolchain/package.json'), JSON.stringify({dependencies}));
  const lockFile = path.join(root, 'toolchain/package-lock.json');
  const lock = {packages: {'': {dependencies}, 'node_modules/brace-expansion': {...entry},
    'node_modules/npm/node_modules/brace-expansion': {...entry}}};
  fs.writeFileSync(lockFile, JSON.stringify(lock));
  fs.writeFileSync(path.join(source, 'package.json'), JSON.stringify({name: 'brace-expansion', version: braceExpansionVersion}));
  fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify({name: 'brace-expansion', version: '5.0.9'}));
  fs.writeFileSync(path.join(source, 'index.js'), '// Synthetic reviewed package.');
  fs.writeFileSync(path.join(target, 'index.js'), '// Synthetic original bundle.');
  return {root, source, target, lockFile, lock};
}

test('brace-expansion replacement copies all bytes, removes obsolete files and is idempotent', t => {
  const {root, source, target} = fixture(t);
  fs.writeFileSync(path.join(target, 'obsolete.js'), 'stale');
  const sibling = path.join(path.dirname(target), 'balanced-match');
  fs.mkdirSync(sibling);
  fs.writeFileSync(path.join(sibling, 'preserve.txt'), 'preserve');
  const hidden = path.join(root, 'toolchain/node_modules/npm/node_modules/.package-lock.json');
  fs.writeFileSync(hidden, '{}');
  replaceBundledBraceExpansion(root);
  replaceBundledBraceExpansion(root);
  assert.deepEqual(fs.readFileSync(path.join(target, 'index.js')), fs.readFileSync(path.join(source, 'index.js')));
  assert.equal(fs.existsSync(path.join(target, 'obsolete.js')), false);
  assert.equal(fs.existsSync(hidden), false);
  assert.equal(fs.readFileSync(path.join(sibling, 'preserve.txt'), 'utf8'), 'preserve');
});

test('brace-expansion rejects stale versions, integrity, URLs and bundled markers before mutation', t => {
  const {root, target, lockFile, lock} = fixture(t);
  for (const location of ['node_modules/brace-expansion', 'node_modules/npm/node_modules/brace-expansion']) {
    for (const [field, value] of [['version', '5.0.9'], ['integrity', 'sha512-unreviewed'],
      ['resolved', 'https://example.invalid/unreviewed.tgz'], ['inBundle', true]]) {
      const changed = structuredClone(lock);
      changed.packages[location][field] = value;
      fs.writeFileSync(lockFile, JSON.stringify(changed));
      assert.throws(() => replaceBundledBraceExpansion(root));
      assert.equal(JSON.parse(fs.readFileSync(path.join(target, 'package.json'))).version, '5.0.9');
    }
  }
});

test('brace-expansion rejects a missing source without deleting the bundle', t => {
  const {root, source, target} = fixture(t);
  fs.rmSync(source, {recursive: true});
  assert.throws(() => replaceBundledBraceExpansion(root));
  assert.equal(JSON.parse(fs.readFileSync(path.join(target, 'package.json'))).version, '5.0.9');
});

test('brace-expansion rejects an unexpected bundled version', t => {
  const {root, target} = fixture(t);
  fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify({name: 'brace-expansion', version: '5.0.8'}));
  assert.throws(() => replaceBundledBraceExpansion(root), /Unexpected npm bundle/);
});

test('brace-expansion cannot follow a bundled directory symlink', t => {
  const {root, source, target} = fixture(t);
  fs.rmSync(target, {recursive: true});
  fs.symlinkSync(source, target, process.platform === 'win32' ? 'junction' : 'dir');
  assert.throws(() => replaceBundledBraceExpansion(root), /Unsafe package directory/);
  assert.ok(fs.existsSync(path.join(source, 'package.json')));
});

test('npm minimatch resolves the complete patched brace-expansion with bounded APIs', () => {
  assert.equal(verifyBundledBraceExpansion(fileURLToPath(new URL('../', import.meta.url))).braceExpansion, braceExpansionVersion);
});

test('the actual npm brace-expansion bounds parsing, nesting and rewrite-heavy inputs', () => {
  const root = fileURLToPath(new URL('../', import.meta.url));
  const result = spawnSync(process.execPath, ['-e', `
    const assert = require('node:assert/strict');
    const path = require('node:path');
    const {createRequire} = require('node:module');
    const npmRequire = createRequire(path.join(process.argv[1], 'toolchain/node_modules/npm/package.json'));
    const minimatchRequire = createRequire(npmRequire.resolve('minimatch'));
    const {expand} = minimatchRequire('brace-expansion');
    // GHSA-6j4f-fj2g-mc7p: parsing chained comma groups must not exhaust the stack.
    const chained = '{' + '{a},'.repeat(8000) + 'z}';
    assert.equal(expand(chained, {max: 1, maxLength: 16384}).length, 1);
    // GHSA-qhr7-859c-m2p7: nesting beyond the default limit remains literal.
    const nested = '{'.repeat(4000) + 'a,b' + '}'.repeat(4000);
    assert.deepEqual(expand(nested), [nested]);
    // GHSA-q2hr-2g5m-vwhr: stop repeated full-input rewrites at the default limit.
    const rewritten = '{a}' + '}'.repeat(64000) + ',z}';
    assert.deepEqual(expand(rewritten), [rewritten]);
    assert.deepEqual(expand('file-{a,b}.txt'), ['file-a.txt', 'file-b.txt']);
    console.log('bounded brace expansion and normal control passed');
  `, root], {encoding: 'utf8', timeout: 5000, maxBuffer: 64 * 1024});
  assert.ifError(result.error);
  assert.equal(result.signal, null);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /bounded brace expansion and normal control passed/);
});
