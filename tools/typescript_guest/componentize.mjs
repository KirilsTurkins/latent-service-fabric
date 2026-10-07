// Checksum-pinned compiler adapter: expose core output and normalize the
// maintained generator's signed i64 lowering to the embedding's core ABI.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { basename, dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { coreIntegerLowering } from './signed64.mjs';
import { explicitResourceOwners } from './resources.mjs';

const [compiler, witPath, sourcePath, output, world = 'capsule', engine, selectionPath] = process.argv.slice(2);
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
// Wizer's host cache requires a home/config location even for an isolated UID
// with no passwd entry. Keep it in this compiler attempt, without inheriting
// the developer's environment or touching the immutable compiler prefix.
const compilerHome = join(output, 'compiler-home');
await mkdir(compilerHome);
const compilerEnv = { HOME: compilerHome,
  XDG_CONFIG_HOME: join(compilerHome, 'config'), XDG_CACHE_HOME: join(compilerHome, 'cache') };
let generatedBindings;
let selectedEngine;
if (engine || selectionPath) {
  if (!engine || !selectionPath) throw new Error('selected-native-engine-inputs-required');
  const selection = JSON.parse(await readFile(selectionPath, 'utf8'));
  const raw = await readFile(engine);
  const actual = 'sha256:' + createHash('sha256').update(raw).digest('hex');
  if (!['spidermonkey-activation-promises-v1','spidermonkey-activation-promises-clocks-v1'].includes(selection.profile) ||
      selection.qualification !== 'unknown' || selection.apiSupport !== 'not-evaluated' ||
      selection.engineInput.coreDigest !== actual || selection.engineInput.coreBytes !== raw.byteLength) {
    throw new Error('selected-native-engine-identity-or-qualification-changed');
  }
  selectedEngine = { digest: actual, size: raw.byteLength, profile: selection.profile,
    qualification: 'unknown', apiSupport: 'not-evaluated' };
}
const result = await componentize({
  sourcePath, sourceName: basename(sourcePath),
  witPath, worldName: world, enableAot: false, env: compilerEnv,
  ...(engine ? { engine } : {}),
  lsfBindings(source) {
    generatedBindings = explicitResourceOwners(coreIntegerLowering(source));
    return generatedBindings;
  },
  disableFeatures: ['stdio', 'random', 'clocks', 'http', 'fetch-event'],
});
await writeFile(join(output, 'generated-bindings.js'), generatedBindings, { flag: 'wx' });
if (!result.core || result.core.byteLength > 64 * 1024 * 1024) throw new Error('core-output-bound');
await writeFile(join(output, 'core.wasm'), result.core, { flag: 'wx' });
await writeFile(join(output, 'compiler.json'), JSON.stringify({
  preimage: createHash('sha256').update(bytes).digest('hex'),
  adapted: createHash('sha256').update(adapted).digest('hex'), imports: result.imports,
  ...(selectedEngine ? { selectedEngine } : {}),
}, null, 2) + '\n', { flag: 'wx' });
