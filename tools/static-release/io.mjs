import {constants} from 'node:fs';
import {open, lstat, rename, unlink, realpath} from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {canonical, digest, requireValue} from './model.mjs';

const MAXIMUM = 1024 * 1024;
export async function readJson(name, protectedFile = false) {
  const handle = await open(name, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = await handle.stat();
    requireValue(stat.isFile() && stat.size <= MAXIMUM && stat.nlink === 1, 'input-file-bound');
    if (protectedFile) requireValue(stat.uid === process.getuid() && (stat.mode & 0o077) === 0, 'protected-file-required');
    const bytes = Buffer.alloc(MAXIMUM + 1);
    let bytesRead = 0;
    while (bytesRead < bytes.length) {
      const result = await handle.read(bytes, bytesRead, bytes.length - bytesRead, bytesRead);
      if (!result.bytesRead) break;
      bytesRead += result.bytesRead;
    }
    requireValue(bytesRead <= MAXIMUM, 'input-file-bound');
    return JSON.parse(bytes.subarray(0, bytesRead).toString('utf8'));
  } finally { await handle.close(); }
}
export async function durableWrite(name, value, create = false) {
  const raw = Buffer.from(canonical(value) + '\n');
  requireValue(raw.length <= MAXIMUM, 'journal-byte-bound');
  if (create) {
    try { await lstat(name); throw new Error('journal-already-exists'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  const temporary = name + '.' + randomUUID() + '.pending';
  const handle = await open(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  try { await handle.writeFile(raw); await handle.sync(); }
  finally { await handle.close(); }
  await rename(temporary, name);
  const directory = await open(path.dirname(name), constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try { await directory.sync(); } finally { await directory.close(); }
}
export async function locked(journal, action) {
  requireValue(process.platform === 'linux', 'linux-or-wsl-required-for-durable-journal');
  const parent = path.dirname(journal);
  requireValue(await realpath(parent) === parent, 'canonical-journal-parent-required');
  const stat = await lstat(parent);
  requireValue(stat.isDirectory() && stat.uid === process.getuid() && (stat.mode & 0o077) === 0, 'private-journal-directory-required');
  const lock = journal + '.lock';
  const handle = await open(lock, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  try {
    await handle.writeFile(canonical({pid: process.pid, startedAt: new Date().toISOString()})); await handle.sync();
    return await action();
  } finally { await handle.close(); await unlink(lock); }
}

export class NativeClient {
  constructor({cli, config, profile, tenant, endpoint, directory, deadlineSeconds = 120}) {
    requireValue(Number.isInteger(deadlineSeconds) && deadlineSeconds >= 1 && deadlineSeconds <= 600, 'deadline-bound');
    Object.assign(this, {cli, config, profile, tenant, endpoint, directory});
    this.deadline = performance.now() + deadlineSeconds * 1000;
    this.calls = 0;
  }
  async call(args) {
    requireValue(++this.calls <= 256 && performance.now() < this.deadline, 'command-budget-exhausted');
    const remaining = Math.min(15000, Math.floor(this.deadline - performance.now()));
    const argv = ['--config', this.config, '--profile', this.profile, '--tenant', this.tenant, '--endpoint', this.endpoint,
      '--output', 'json', '--rpc-timeout-ms', String(Math.max(1, remaining - 500)), ...args];
    return new Promise((resolve, reject) => {
      const child = spawn(this.cli, argv, {cwd: this.directory, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
      const chunks = []; let bytes = 0, failure;
      const fail = code => { failure ??= code; child.kill('SIGKILL'); };
      const timer = setTimeout(() => fail('command-deadline'), remaining);
      child.on('error', () => { failure ??= 'command-start-failed'; });
      child.stdout.on('data', data => {
        bytes += data.length;
        if (bytes > MAXIMUM) fail('command-output-bound'); else chunks.push(data);
      });
      child.stderr.on('data', data => { bytes += data.length; if (bytes > MAXIMUM) fail('command-output-bound'); });
      child.on('close', code => {
        clearTimeout(timer);
        if (failure) { reject(new Error(failure)); return; }
        try {
          const value = JSON.parse(Buffer.concat(chunks).toString('utf8'));
          const codes = {success: 0, 'local-error': 2, 'declared-error': 3, 'platform-failure': 4, 'transport-failure': 5, 'not-found': 6, interrupted: 130};
          requireValue(value.schemaVersion === 'latent.cli.result.v1' && typeof value.outcomeKnown === 'boolean'
            && typeof value.requestDispatched === 'boolean' && value.data && typeof value.data === 'object'
            && codes[value.category] === code, 'command-response-invalid');
          resolve(value);
        } catch { reject(new Error('command-response-invalid')); }
      });
    });
  }
  async apply(manifest, attempt) {
    const name = path.join(this.directory, attempt.id + '.json');
    await durableWrite(name, manifest, true);
    return this.call(['trigger', 'apply', name, '--operation-id', attempt.id,
      '--expected-generation', attempt.generation, '--expected-state-version', attempt.stateVersion]);
  }
}

export async function connection(options, tenant) {
  const config = await readJson(options.config, true);
  const profile = config.profiles?.find(row => row.name === options.profile);
  requireValue(profile?.tenant === tenant && typeof profile.endpoint === 'string', 'profile-tenant-mismatch');
  const binding = digest({endpoint: profile.endpoint, tenant, profile: options.profile, node: options.node});
  const client = new NativeClient({...options, tenant, endpoint: profile.endpoint, directory: path.dirname(options.journal)});
  const result = await client.call(['node', 'get', options.node]);
  requireValue(result.category === 'success' && result.outcomeKnown === true
    && result.data.inventory?.node?.id === options.node, 'node-identity-unavailable');
  return {client, binding};
}
