import {digest, LIMITS, requireValue} from './io.mjs';

export function extractRegions(text) {
  const result = new Map();
  const lines = text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  let active;
  for (const [index, line] of lines.entries()) {
    const match = /^[ \t]*\/\/ lsf-example-(begin|end): ([a-z][a-z0-9-]{0,63})[ \t]*(?:\r?\n)?$/.exec(line);
    if (!match) {
      requireValue(!/^[ \t]*\/\/\s*lsf-example-/.test(line), 'Malformed example region marker');
      if (active) {
        active.bytes += Buffer.byteLength(line);
        requireValue(active.bytes <= LIMITS.regionBytes, 'Example region byte limit');
        active.lines.push(line);
      }
      continue;
    }
    const [, action, id] = match;
    if (action === 'begin') {
      requireValue(!active, 'Nested example regions are not supported');
      requireValue(!result.has(id), 'Duplicate example region marker');
      requireValue(result.size < LIMITS.regions, 'Example region count limit');
      active = {id, startLine: index + 2, lines: [], bytes: 0};
    } else {
      requireValue(active?.id === id, 'Unmatched example region end');
      const code = active.lines.join('');
      requireValue(code.trim().length > 0, 'Empty example region');
      result.set(id, {code, startLine: active.startLine, endLine: index, sha256: digest(code)});
      active = undefined;
    }
  }
  requireValue(!active, 'Unclosed example region');
  return result;
}
