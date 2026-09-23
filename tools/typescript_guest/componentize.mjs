// Narrow, checksum-pinned diagnostic: expose the real compiler's core output.
// The compiler and engine are unchanged; only the returned object gains bytes.
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { basename, dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const [compiler, witPath, sourcePath, output] = process.argv.slice(2);
const bytes = await readFile(compiler);
if (createHash('sha256').update(bytes).digest('hex') !==
    'e58ef4f3b126f4a3fd07c61b368930bbf02dd0029f0f03e4c6928528e994e559') {
  throw new Error('unreviewed-componentize-js-source');
}
const original = bytes.toString('utf8');
const before = '  return {\n    component,\n';
if (original.split(before).length !== 2) throw new Error('compiler-output-shape-drift');
const adapted = original.replace(before, '  return {\n    core: finalBin,\n    component,\n');
const path = join(dirname(compiler), 'componentize.lsf-core.mjs');
try {
  await writeFile(path, adapted, { flag: 'wx' });
} catch (error) {
  if (error.code !== 'EEXIST' || await readFile(path, 'utf8') !== adapted) throw error;
}
const { componentize } = await import(pathToFileURL(path));
const result = await componentize({
  sourcePath, sourceName: basename(sourcePath),
  witPath, worldName: 'capsule', enableAot: false, env: {},
  disableFeatures: ['stdio', 'random', 'clocks', 'http', 'fetch-event'],
});
if (!result.core || result.core.byteLength > 64 * 1024 * 1024) throw new Error('core-output-bound');
await writeFile(join(output, 'core.wasm'), result.core, { flag: 'wx' });
await writeFile(join(output, 'compiler.json'), JSON.stringify({
  preimage: createHash('sha256').update(bytes).digest('hex'),
  adapted: createHash('sha256').update(adapted).digest('hex'), imports: result.imports,
}, null, 2) + '\n', { flag: 'wx' });
