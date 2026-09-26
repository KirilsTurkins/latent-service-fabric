import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';

export const LIMITS = Object.freeze({registrations: 64, variants: 6, regions: 32, requests: 256,
  files: 512, fileBytes: 262144, regionBytes: 32768, inputBytes: 8 * 1024 * 1024,
  outputBytes: 1024 * 1024, metadataBytes: 16384});
export const digest = bytes => createHash('sha256').update(bytes).digest('hex');
export const blobId = bytes => createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
export function requireValue(value, message) { if (!value) throw new Error(message); }
export function canonicalPath(value) {
  requireValue(typeof value === 'string' && value.length <= 512 && value.length > 0, 'Invalid example path');
  requireValue(value.split('/').every(part => /^[A-Za-z0-9_-][A-Za-z0-9_.-]*$/.test(part)
    && !part.endsWith('.') && !/^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)/i.test(part)), 'Unsafe or ambiguous example path');
  return value;
}
export function revision(value) {
  requireValue(typeof value === 'string' && /^[a-f0-9]{40}$/.test(value), 'Examples require an exact local Git revision');
  return value;
}
export function sourceUrl(ref, relative) {
  return `https://github.com/KirilsTurkins/latent-service-fabric/blob/${revision(ref)}/${canonicalPath(relative)}`;
}

// A reviewed, quiescent checkout is a build input, not a sandbox for concurrent
// hostile repository writers. No filesystem glob, lazy fetch, shell or filters.
export function createReader(root) {
  root = fs.realpathSync(root);
  const inputs = new Map();
  const gitObjects = new Map();
  let total = 0;
  return {
    inputs,
    read(relative, maximum = LIMITS.fileBytes, optional = false) {
      canonicalPath(relative);
      requireValue(maximum > 0 && maximum <= LIMITS.fileBytes, 'Invalid example read limit');
      if (inputs.has(relative)) {
        const result = inputs.get(relative);
        requireValue(result.bytes.length <= maximum, 'Example file exceeds read limit');
        return result;
      }
      requireValue(inputs.size < LIMITS.files, 'Example file count limit');
      let current = root;
      const segments = relative.split('/');
      for (const [index, segment] of segments.entries()) {
        const names = fs.readdirSync(current);
        if (!names.includes(segment)) {
          requireValue(!names.some(name => name.toLowerCase() === segment.toLowerCase()), 'Incorrectly cased example path');
          if (optional) return null;
          throw new Error(`Missing or incorrectly cased example path: ${relative}`);
        }
        current = path.join(current, segment);
        const stat = fs.lstatSync(current);
        requireValue(!stat.isSymbolicLink(), 'Linked example input');
        if (index < segments.length - 1) requireValue(stat.isDirectory(), 'Non-directory example input');
      }
      const before = fs.lstatSync(current);
      requireValue(before.isFile() && before.size <= maximum, 'Nonregular or oversized example input');
      const fd = fs.openSync(current, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0) | (fs.constants.O_NONBLOCK ?? 0));
      try {
        const opened = fs.fstatSync(fd);
        requireValue(opened.isFile() && opened.size <= maximum && before.ino === opened.ino && before.dev === opened.dev, 'Example input changed before read');
        const buffer = Buffer.alloc(maximum + 1);
        let length = 0;
        while (length <= maximum) {
          const read = fs.readSync(fd, buffer, length, maximum + 1 - length, null);
          if (!read) break;
          length += read;
        }
        requireValue(length <= maximum, 'Example input grew beyond limit');
        const after = fs.fstatSync(fd);
        requireValue(after.size === length && after.mtimeMs === opened.mtimeMs && after.ctimeMs === opened.ctimeMs, 'Example input changed during read');
        total += length;
        requireValue(total <= LIMITS.inputBytes, 'Example aggregate input limit');
        const bytes = Buffer.from(buffer.subarray(0, length));
        const text = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(bytes);
        requireValue(!text.includes('\0') && !text.startsWith('\uFEFF'), 'NUL or BOM in example input');
        const result = {bytes, text, sha256: digest(bytes), blob: blobId(bytes)};
        inputs.set(relative, result);
        return result;
      } finally { fs.closeSync(fd); }
    },
    matches(ref, relative, blob) {
      revision(ref); canonicalPath(relative);
      const key = `${ref}:${relative}`;
      if (gitObjects.has(key)) return gitObjects.get(key) === blob;
      try {
        const actual = execFileSync('git', ['-c', 'gc.auto=0', 'rev-parse', '--verify', `${ref}:${relative}`], {
          cwd: root, encoding: 'utf8', timeout: 5000, maxBuffer: 1024,
          env: {...process.env, GIT_NO_REPLACE_OBJECTS: '1', GIT_NO_LAZY_FETCH: '1', GIT_TERMINAL_PROMPT: '0'},
          stdio: ['ignore', 'pipe', 'pipe'],
        }).trim();
        gitObjects.set(key, actual);
        return actual === blob;
      } catch { gitObjects.set(key, null); return false; }
    },
  };
}

export function writeSnapshot(root, bundle) {
  const bytes = `${JSON.stringify(bundle, null, 2)}\n`;
  requireValue(Buffer.byteLength(bytes) <= LIMITS.outputBytes, 'Example output byte limit');
  let directory = fs.realpathSync(root);
  for (const segment of ['website', '.generated', 'examples']) {
    directory = path.join(directory, segment);
    try { fs.mkdirSync(directory); } catch (error) { if (error.code !== 'EEXIST') throw error; }
    const stat = fs.lstatSync(directory);
    requireValue(stat.isDirectory() && !stat.isSymbolicLink(), 'Linked/non-directory example output');
  }
  const destination = path.join(directory, `${digest(bytes)}.json`);
  try { fs.writeFileSync(destination, bytes, {flag: 'wx'}); }
  catch (error) {
    if (error.code !== 'EEXIST') throw error;
    const stat = fs.lstatSync(destination);
    requireValue(stat.isFile() && !stat.isSymbolicLink() && stat.size === Buffer.byteLength(bytes)
      && fs.readFileSync(destination, 'utf8') === bytes, 'Example output collision; remove interrupted output before retrying');
  }
  return destination;
}
