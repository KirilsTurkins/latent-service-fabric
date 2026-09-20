import {execFileSync} from 'node:child_process';
import {canonicalPath, digest, LIMITS, revision} from '../../plugins/examples/io.mjs';
import {requireValue} from '../repository.mjs';

export const SNAPSHOT_LIMITS = Object.freeze({files: 2000, bytes: 32 * 1024 * 1024, versions: 3});
const environment = {...process.env, GIT_NO_REPLACE_OBJECTS: '1', GIT_NO_LAZY_FETCH: '1', GIT_TERMINAL_PROMPT: '0'};

export function gitBytes(root, args, maximum = 8 * 1024 * 1024) {
  return execFileSync('git', ['-c', 'gc.auto=0', ...args], {cwd: root, timeout: 15000, maxBuffer: maximum,
    env: environment, stdio: ['ignore', 'pipe', 'pipe']});
}

export function committedTree(root, identity) {
  revision(identity);
  requireValue(gitBytes(root, ['rev-parse', '--verify', `${identity}^{commit}`], 1024).toString().trim() === identity, 'Missing exact local snapshot commit');
  const entries = gitBytes(root, ['ls-tree', '-rz', '--full-tree', identity]).toString('utf8').split('\0').filter(Boolean);
  requireValue(entries.length > 0 && entries.length <= 20000, 'Snapshot tree inventory limit');
  const result = new Map();
  const spellings = new Set();
  for (const entry of entries) {
    const match = /^(\d{6}) (blob|commit) ([a-f0-9]{40})\t(.+)$/.exec(entry);
    requireValue(match, 'Invalid snapshot tree entry');
    const [, mode, type, object, name] = match;
    requireValue(!spellings.has(name.toLowerCase()), 'Case-colliding snapshot tree');
    spellings.add(name.toLowerCase());
    result.set(name, {mode, type, object});
  }
  return result;
}

export function sourceReader(root, documentationRevision, sourceRevision = documentationRevision) {
  const trees = new Map();
  function tree(ref) {
    revision(ref);
    if (!trees.has(ref)) trees.set(ref, committedTree(root, ref));
    return trees.get(ref);
  }
  const inputs = new Map();
  let bytes = 0;
  function readAt(ref, name, maximum = 2 * 1024 * 1024, optional = false) {
    canonicalPath(name);
    requireValue(/^(docs|adr|sdk|examples|tools|apps|crates|tests|website\/scripts)\//.test(name)
      || /^benchmarks\/.+\.md$/.test(name)
      || /^(README|ARCHITECTURE|CONTRIBUTING|VALIDATION|CHANGELOG|SECURITY)\.md$/.test(name), `Unapproved snapshot content root: ${name}`);
    const entry = tree(ref).get(name);
    if (optional && !entry) return null;
    requireValue(entry?.type === 'blob' && ['100644', '100755'].includes(entry.mode), 'Missing, linked or nonregular snapshot source');
    const length = Number(gitBytes(root, ['cat-file', '-s', entry.object], 1024).toString().trim());
    requireValue(Number.isSafeInteger(length) && length <= maximum, 'Snapshot source size limit');
    const value = gitBytes(root, ['cat-file', 'blob', entry.object], maximum + 1);
    bytes += value.length;
    requireValue(value.length === length && bytes <= SNAPSHOT_LIMITS.bytes, 'Snapshot source corpus limit');
    return {bytes: value, text: new TextDecoder('utf-8', {fatal: true}).decode(value), sha256: digest(value), blob: entry.object};
  }
  return {
    inputs, tree, readAt,
    read(name, maximum = LIMITS.fileBytes, optional = false) {
      const ref = name.startsWith('docs/') ? documentationRevision : sourceRevision;
      if (inputs.has(name)) {
        const cached = inputs.get(name);
        requireValue(cached.bytes.length <= maximum, 'Snapshot example file size limit');
        return cached;
      }
      requireValue(inputs.size < LIMITS.files, 'Snapshot example file count limit');
      const value = readAt(ref, name, maximum, optional);
      if (value) inputs.set(name, value);
      return value;
    },
    matches(ref, name, blob) { return tree(ref).get(name)?.object === blob; },
  };
}
