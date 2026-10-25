// Checksum-pinned compiler adapter: expose core output and normalize the
// maintained generator's signed i64 lowering to the embedding's core ABI.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { basename, dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { coreIntegerLowering } from './signed64.mjs';
import { explicitResourceOwners } from './resources.mjs';
import { selectedSourceSplicer } from './source_splicer.mjs';
import { lazySyncImportWaiters, retireGeneratedTaskSlots, applicationRealmImportPromises, fuseNativeImportAwaits, directIdleTaskSlots, nativeCarrierImports } from './async_waiters.mjs';
import { borrowReleaseHandoff } from './import_cancellation.mjs';
import { borrowProbeBindings, borrowProbeProfile, borrowProbeSpliceCapture } from './borrow_probe.mjs';
import { nodeNetBindings, NET_PROFILE } from './node_net_bindings.mjs';

const arguments_ = process.argv.slice(2);
const netArguments = arguments_.filter(value => value.startsWith('--node-net-selection='));
if (netArguments.length > 1) throw new Error('compiler-owned-node-net-selection-duplicate');
const [compiler, witPath, sourcePath, output, world = 'capsule', engine, selectionPath, sourceSplicer, bindingParser, diagnosticProfile] =
  arguments_.filter(value => !value.startsWith('--node-net-selection='));
const netSelectionPath = netArguments[0]?.slice('--node-net-selection='.length);
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
    .replace(selectionAnchor, selectionAnchor +
      "\n  if (!opts.lsfSplicer || typeof opts.lsfSplicer !== 'object' || typeof opts.lsfSplicer.spliceBindings !== 'function' || typeof opts.lsfSplicer.stubWasi !== 'function') throw new Error('source-built-splicer-callable-export-required');" +
      '\n  const splicer = opts.lsfSplicer;');
}
// Exact pinned public adapter shape (SHA256 e58ef4f3...994e559). Do not
// wrap or make asynchronous its original synchronous spliceBindings API.
const spliceAnchor = `  let { wasm, jsBindings, exports, imports } = splicer.spliceBindings(
    await readFile(engine),
    [...features],
    witWorld,
    maybeWindowsPath(witPath),
    worldName,
    false,
  );`;
if (adapted.split(spliceAnchor).length !== 2) throw new Error('compiler-splice-tap-shape-drift');
adapted = adapted.replace(spliceAnchor,
  spliceAnchor.replace('let { wasm, jsBindings, exports, imports } =', 'const lsfSpliceResult =') +
  `
  if (opts.lsfSpliceTap !== undefined && opts.lsfSpliceTap(lsfSpliceResult) !== lsfSpliceResult)
    throw new Error('compiler-splice-tap-result-identity');
  let { wasm, jsBindings, exports, imports } = lsfSpliceResult;`);
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
    selectedSplicer = selectedSourceSplicer(await import(pathToFileURL(sourceSplicer)));
  } else if (sourceSplicer) throw new Error('source-splicer-requires-import-profile');
  selectedEngine = { digest: actual, size: raw.byteLength, profile: selection.profile,
    qualification: 'unknown', apiSupport: 'not-evaluated' };
}
let parseBindings;
if (selectedSplicer) {
  if (!bindingParser) throw new Error('source-owned-binding-parser-required');
  ({parse: parseBindings} = await import(pathToFileURL(bindingParser)));
  if (typeof parseBindings !== 'function') throw new Error('source-owned-binding-parser-required');
}
if (diagnosticProfile !== undefined && (!selectedSplicer || diagnosticProfile !== borrowProbeProfile)) {
  throw new Error('compiler-owned-borrow-probe-runtime');
}
let netSelection, netExports;
if (netSelectionPath !== undefined) {
  if (!selectedSplicer || diagnosticProfile !== undefined) throw new Error('compiler-owned-node-net-runtime');
  const raw = await readFile(netSelectionPath);
  if (raw.byteLength > 65536) throw new Error('compiler-owned-node-net-selection-bound');
  netSelection = JSON.parse(raw);
  const fixed = {schemaVersion:'latent.typescript.standard-net-selection.v1', profile:NET_PROFILE,
    modules:['node:net'], identities:netSelection.identities, maximumSocketStates:2,
    maximumPendingOperationsPerSocket:3, maximumQueuedWriteBytes:65536, maximumQueuedWriteRecords:16,
    maximumTransferWindowBytes:16384,
    transport:'tcp', tlsApi:false, dnsApi:false, listeners:false, descriptorNamespace:false,
    rootRequiresCompletedClose:true, automaticCloseDrain:true,
    closeDrain:'accepted-terminal-intent-only-v1', maximumRootCloseWaiters:1,
    pausedEndRead:'eof-only-unread-data-refuses', physicalRetirement:'not-inferred',
    authority:'none', qualification:'unknown'};
  const canonical = value => JSON.stringify(value, Object.keys(value).sort());
  if (canonical(netSelection) !== canonical(fixed) || !netSelection.identities ||
      Object.keys(netSelection.identities).sort().join(',') !== 'backend,bindings,declaration,interface,resolver,transport' ||
      Object.values(netSelection.identities).some(value => !/^sha256:[0-9a-f]{64}$/.test(value)))
    throw new Error('compiler-owned-node-net-selection-shape');
  for (const [name, file] of [['backend','node_net.mjs'],['bindings','node_net_bindings.mjs'],
      ['resolver','net_builtin.mjs'],['transport','node_net_transport.mjs']]) {
    const actual = 'sha256:' + createHash('sha256').update(await readFile(new URL(file, import.meta.url))).digest('hex');
    if (actual !== netSelection.identities[name]) throw new Error('compiler-owned-node-net-source-drift');
  }
}
const diagnosticTap = borrowProbeSpliceCapture(diagnosticProfile,
  (name, value) => writeFileSync(join(output,name),value,{flag:'wx'}));
const result = await componentize({
  sourcePath, sourceName: basename(sourcePath),
  witPath, worldName: world, enableAot: false, env: compilerEnv,
  ...(engine ? { engine } : {}),
  ...(selectedSplicer ? {lsfSplicer:selectedSplicer} : {}),
  lsfSpliceTap: netSelection ? result => {
    if (!result || !Array.isArray(result.exports) || result.exports.length > 64)
      throw new Error('compiler-owned-node-net-splice-exports');
    netExports = result.exports;
    return result; // Preserve exact synchronous result object/receiver/arguments.
  } : diagnosticTap,
  lsfBindings(source) {
    generatedBindings = explicitResourceOwners(coreIntegerLowering(source));
    if (selectedEngine) {
      generatedBindings = retireGeneratedTaskSlots(lazySyncImportWaiters(generatedBindings));
    }
    if (selectedSplicer) {
      generatedBindings = directIdleTaskSlots(generatedBindings);
      generatedBindings = fuseNativeImportAwaits(generatedBindings, parseBindings);
      generatedBindings = nativeCarrierImports(generatedBindings, parseBindings);
      generatedBindings = borrowReleaseHandoff(generatedBindings, parseBindings);
      generatedBindings = borrowProbeBindings(generatedBindings, parseBindings, diagnosticProfile);
      generatedBindings = nodeNetBindings(generatedBindings, parseBindings, netSelection?.profile, netExports);
      generatedBindings = applicationRealmImportPromises(generatedBindings);
    }
    if (diagnosticProfile === borrowProbeProfile) {
      if (Buffer.byteLength(generatedBindings,'utf8') > 8 * 1024 * 1024)
        throw new Error('compiler-owned-borrow-generated-bindings-bound');
      writeFileSync(join(output,'pre-wizer-bindings.js'),generatedBindings,{flag:'wx'});
    }
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
