import {constants} from 'node:fs';
import {lstat, open, realpath, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {canonical, requireValue} from './model.mjs';

export const sha256 = bytes => 'sha256:' + createHash('sha256').update(bytes).digest('hex');
export const jsonBytes = value => Buffer.from(canonical(value));
export function closed(value, fields) {
  requireValue(value && typeof value === 'object' && !Array.isArray(value)
    && canonical(Object.keys(value).sort()) === canonical(fields.slice().sort()), 'closed-release-input-required');
}
export function boundedJson(bytes, maximum = 1024 * 1024) {
  requireValue(bytes.length <= maximum, 'release-json-byte-bound');
  const text = new TextDecoder('utf-8', {fatal: true}).decode(bytes);
  // The signing interface consumes canonical machine-prepared JSON. This also
  // refuses duplicate keys, unsafe integers, alternate lexical forms and depth.
  let value;
  try { value = JSON.parse(text); } catch { throw new Error('invalid-release-json'); }
  let nodes = 0;
  function visit(item, depth) {
    requireValue(++nodes <= 8192 && depth <= 16, 'release-json-work-bound');
    if (typeof item === 'number') requireValue(Number.isSafeInteger(item) && item >= 0, 'release-json-integer-bound');
    if (typeof item === 'string') requireValue(Buffer.byteLength(item) <= 4096, 'release-json-string-bound');
    if (item && typeof item === 'object') for (const [key, child] of Object.entries(item)) {
      requireValue(key.length <= 256, 'release-json-key-bound'); visit(child, depth + 1);
    }
  }
  visit(value, 0);
  requireValue(text === canonical(value) || text === canonical(value) + '\n', 'canonical-release-json-required');
  return value;
}
export async function privateDirectory(name, fresh = false) {
  requireValue(process.platform === 'linux', 'linux-or-wsl-required-for-protected-release-files');
  const absolute = path.resolve(name);
  if (fresh) {
    requireValue(await realpath(path.dirname(absolute)) === path.dirname(absolute), 'canonical-release-parent-required');
    await mkdir(absolute, {mode: 0o700});
  }
  requireValue(await realpath(absolute) === absolute, 'canonical-release-directory-required');
  const stat = await lstat(absolute);
  requireValue(stat.isDirectory() && stat.uid === process.getuid() && (stat.mode & 0o077) === 0,
    'private-release-directory-required');
  return absolute;
}
export async function readBytes(name, maximum, secret = false) {
  requireValue(Number.isSafeInteger(maximum) && maximum > 0 && maximum <= 256 * 1024 * 1024, 'release-read-bound');
  const absolute = path.resolve(name);
  requireValue(await realpath(path.dirname(absolute)) === path.dirname(absolute), 'canonical-release-parent-required');
  if (secret) await privateDirectory(path.dirname(absolute));
  const handle = await open(absolute, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  let bytes;
  try {
    const before = await handle.stat({bigint: true});
    requireValue(before.isFile() && before.size > 0n && before.size <= BigInt(maximum), 'release-file-bound');
    if (secret) requireValue(before.uid === BigInt(process.getuid()) && (before.mode & 0o077n) === 0n
      && before.nlink === 1n, 'protected-release-input-required');
    bytes = Buffer.alloc(Number(before.size) + 1);
    let used = 0;
    while (used < bytes.length) {
      const result = await handle.read(bytes, used, bytes.length - used, used);
      if (!result.bytesRead) break;
      used += result.bytesRead;
    }
    const after = await handle.stat({bigint: true}), final = await lstat(absolute, {bigint: true});
    requireValue(used === Number(before.size) && !final.isSymbolicLink()
      && ['dev', 'ino', 'size', 'mtimeNs', 'ctimeNs'].every(key => before[key] === after[key] && before[key] === final[key]),
      'release-input-changed');
    return bytes.subarray(0, used);
  } catch (error) { if (secret) bytes?.fill(0); throw error; }
  finally { await handle.close(); }
}
export async function writeBytes(name, bytes) {
  requireValue(bytes.length <= 1024 * 1024, 'release-output-bound');
  const handle = await open(name, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  try { await handle.writeFile(bytes); await handle.sync(); } finally { await handle.close(); }
}
export const writeJson = (name, value) => writeBytes(name, jsonBytes(value));
