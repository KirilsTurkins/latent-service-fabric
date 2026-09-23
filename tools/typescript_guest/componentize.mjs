// Checksum-pinned compiler adapter: expose core output and normalize the
// maintained generator's signed i64 lowering to the embedding's core ABI.
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { basename, dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { coreIntegerLowering } from './signed64.mjs';

const [compiler, witPath, sourcePath, output, world = 'capsule'] = process.argv.slice(2);
const bytes = await readFile(compiler);
if (createHash('sha256').update(bytes).digest('hex') !==
    'e58ef4f3b126f4a3fd07c61b368930bbf02dd0029f0f03e4c6928528e994e559') {
  throw new Error('unreviewed-componentize-js-source');
}
const original = bytes.toString('utf8');
const before = '  return {\n    component,\n';
if (original.split(before).length !== 2) throw new Error('compiler-output-shape-drift');
const bindingWrite = '  await writeFile(initializerPath, jsBindings);';
if (original.split(bindingWrite).length !== 2) throw new Error('compiler-binding-hook-drift');
const adapted = original.replace(before, '  return {\n    core: finalBin,\n    component,\n')
  .replace(bindingWrite, '  jsBindings = opts.lsfBindings(jsBindings);\n' + bindingWrite);
const path = join(dirname(compiler), 'componentize.lsf-core-v2.mjs');
try {
  await writeFile(path, adapted, { flag: 'wx' });
} catch (error) {
  if (error.code !== 'EEXIST' || await readFile(path, 'utf8') !== adapted) throw error;
}
const { componentize } = await import(pathToFileURL(path));
if (!witPath) process.exit(0); // Prepare and hash the reviewed adapter before the build.
let generatedBindings;
const result = await componentize({
  sourcePath, sourceName: basename(sourcePath),
  witPath, worldName: world, enableAot: false, env: {},
  lsfBindings(source) { generatedBindings = coreIntegerLowering(source); return generatedBindings; },
  disableFeatures: ['stdio', 'random', 'clocks', 'http', 'fetch-event'],
});
await writeFile(join(output, 'generated-bindings.js'), generatedBindings, { flag: 'wx' });
if (!result.core || result.core.byteLength > 64 * 1024 * 1024) throw new Error('core-output-bound');
await writeFile(join(output, 'core.wasm'), result.core, { flag: 'wx' });
await writeFile(join(output, 'compiler.json'), JSON.stringify({
  preimage: createHash('sha256').update(bytes).digest('hex'),
  adapted: createHash('sha256').update(adapted).digest('hex'), imports: result.imports,
}, null, 2) + '\n', { flag: 'wx' });
