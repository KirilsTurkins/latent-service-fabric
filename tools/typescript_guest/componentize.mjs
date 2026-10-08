// Checksum-pinned compiler adapter: expose core output and normalize the
// maintained generator's signed i64 lowering to the embedding's core ABI.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { basename, dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { coreIntegerLowering } from './signed64.mjs';
import { explicitResourceOwners } from './resources.mjs';

const [compiler, witPath, sourcePath, output, world = 'capsule', engine, selectionPath, sourceSplicer] = process.argv.slice(2);
const prepareImport = witPath === '--source-import-adapter';
const importProfile = 'spidermonkey-activation-promises-clocks-imports-v1';
const useImportAdapter = prepareImport || !!sourceSplicer;
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
let adapted = original.replace(before, '  return {\n    core: finalBin,\n    component,\n')
  .replace(bindingWrite, '  jsBindings = opts.lsfBindings(jsBindings);\n' + bindingWrite);
if (useImportAdapter) {
  const importAnchor = "import { splicer } from '../lib/spidermonkey-embedding-splicer.js';";
  const selectionAnchor = '  const engine = getEnginePath(opts);';
  if (adapted.split(importAnchor).length !== 2 || adapted.split(selectionAnchor).length !== 2) {
    throw new Error('compiler-source-splicer-hook-drift');
  }
  adapted = adapted.replace(importAnchor, "import { splicer as publicSplicer } from '../lib/spidermonkey-embedding-splicer.js';")
    .replace(selectionAnchor, selectionAnchor + '\n  const splicer = opts.lsfSplicer || publicSplicer;');
}
const path = join(dirname(compiler), useImportAdapter ? 'componentize.lsf-import-v1.mjs' : 'componentize.lsf-core-v2.mjs');
try {
  await writeFile(path, adapted, { flag: 'wx' });
} catch (error) {
  if (error.code !== 'EEXIST' || await readFile(path, 'utf8') !== adapted) throw error;
}
const { componentize } = await import(pathToFileURL(path));
if (!witPath || prepareImport) process.exit(0); // Prepare/hash before the build.
// Wizer's host cache requires a home/config location even for an isolated UID
// with no passwd entry. Keep it in this compiler attempt, without inheriting
// the developer's environment or touching the immutable compiler prefix.
const compilerHome = join(output, 'compiler-home');
await mkdir(compilerHome);
const compilerEnv = { HOME: compilerHome,
  XDG_CONFIG_HOME: join(compilerHome, 'config'), XDG_CACHE_HOME: join(compilerHome, 'cache') };
let generatedBindings;
let selectedEngine;
let selectedSplicer;
if (engine || selectionPath) {
  if (!engine || !selectionPath) throw new Error('selected-native-engine-inputs-required');
  const selection = JSON.parse(await readFile(selectionPath, 'utf8'));
  const raw = await readFile(engine);
  const actual = 'sha256:' + createHash('sha256').update(raw).digest('hex');
  if (!['spidermonkey-activation-promises-v1','spidermonkey-activation-promises-clocks-v1',importProfile].includes(selection.profile) ||
      selection.qualification !== 'unknown' || selection.apiSupport !== 'not-evaluated' ||
      selection.engineInput.coreDigest !== actual || selection.engineInput.coreBytes !== raw.byteLength) {
    throw new Error('selected-native-engine-identity-or-qualification-changed');
  }
  if (selection.profile === importProfile) {
    if (!sourceSplicer || !selection.compilerSplicerInput ||
        selection.compilerSplicerInput.qualification !== 'unknown' || selection.compilerSplicerInput.apiSupport !== 'not-evaluated') {
      throw new Error('source-bound-import-compiler-inputs-required');
    }
    for (const row of selection.compilerSplicerInput.files) {
      const raw = await readFile(join(dirname(sourceSplicer),row.path));
      if (raw.byteLength !== row.size || 'sha256:' + createHash('sha256').update(raw).digest('hex') !== row.digest) {
        throw new Error('source-built-splicer-byte-identity-changed');
      }
    }
    ({splicer:selectedSplicer} = await import(pathToFileURL(sourceSplicer)));
  } else if (sourceSplicer) throw new Error('source-splicer-requires-import-profile');
  selectedEngine = { digest: actual, size: raw.byteLength, profile: selection.profile,
    qualification: 'unknown', apiSupport: 'not-evaluated' };
}
const result = await componentize({
  sourcePath, sourceName: basename(sourcePath),
  witPath, worldName: world, enableAot: false, env: compilerEnv,
  ...(engine ? { engine } : {}),
  ...(selectedSplicer ? {lsfSplicer:selectedSplicer} : {}),
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
  ...(selectedSplicer ? {selectedCompilerSplicer:true,qualification:'unknown'} : {}),
}, null, 2) + '\n', { flag: 'wx' });
