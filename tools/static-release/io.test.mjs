import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, chmod, rm, symlink, writeFile, lstat} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {durableWrite, locked, readJson, NativeClient} from './io.mjs';

const linux = {skip: process.platform !== 'linux'};
test('durable journal replace, exclusive owner and interrupted staging preserve prior complete intent', linux, async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'lsf-route-test-')); await chmod(root, 0o700);
  const journal = path.join(root, 'journal.json');
  try {
    await locked(journal, async () => {
      await durableWrite(journal, {generation: '1'}, true);
      await assert.rejects(locked(journal, async () => assert.fail('second owner')), {code: 'EEXIST'});
      await writeFile(journal + '.interrupted.pending', '{', {mode: 0o600});
      assert.deepEqual(await readJson(journal, true), {generation: '1'});
      await durableWrite(journal, {generation: '2'});
      assert.equal((await lstat(journal)).mode & 0o077, 0);
      await assert.rejects(durableWrite(journal, {}, true), /journal-already-exists/);
    });
    await locked(journal, async () => assert.deepEqual(await readJson(journal, true), {generation: '2'}));
  } finally { await rm(root, {recursive: true}); }
});
test('journal inputs reject symlinks, public modes and excessive bytes', linux, async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'lsf-route-test-')); await chmod(root, 0o700);
  const file = path.join(root, 'file');
  try {
    await writeFile(file, '{}', {mode: 0o644}); await chmod(file, 0o644);
    await assert.rejects(readJson(file, true), /protected-file-required/);
    await symlink(file, path.join(root, 'alias'));
    await assert.rejects(readJson(path.join(root, 'alias')));
    await writeFile(file, ' '.repeat(1024 * 1024 + 1));
    await assert.rejects(readJson(file), /input-file-bound/);
  } finally { await rm(root, {recursive: true}); }
});
test('native child output is bounded and rejects malformed result without reflecting it', linux, async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'lsf-route-test-')); await chmod(root, 0o700);
  const script = path.join(root, 'untrusted-output');
  try {
    await writeFile(script, '#!/bin/sh\nprintf "private-data-not-json"\n', {mode: 0o700});
    const client = new NativeClient({cli: script, config: '/unused', profile: 'operator', tenant: 'example',
      endpoint: 'http://127.0.0.1:1', directory: root, deadlineSeconds: 2});
    await assert.rejects(client.call(['node', 'get', 'test']), error => error.message === 'command-response-invalid');
  } finally { await rm(root, {recursive: true}); }
});
