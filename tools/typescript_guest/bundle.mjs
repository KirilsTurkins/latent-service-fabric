import { realpath, readFile, writeFile, stat } from 'node:fs/promises';
import { resolve, relative, isAbsolute, extname } from 'node:path';
import { builtinModules } from 'node:module';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { activationModule } from './activation_module.mjs';
import { bufferBuiltin, BUFFER_PROFILE } from './buffer_builtin.mjs';
import { bufferGlobalReferences, bufferGlobalBuiltin, BUFFER_GLOBAL_PROFILE, BUFFER_GLOBAL_PRIVATE } from './buffer_globals.mjs';
import { netBuiltin, NET_PROFILE, NET_PRIVATE } from './net_builtin.mjs';
import { borrowProbeConfiguration, borrowProbeBuiltin } from './borrow_probe.mjs';

const [esbuildPath, projectPath, input, output, importsPath, configurationPath, parserPath] = process.argv.slice(2);
const { build } = await import(pathToFileURL(esbuildPath));
const project = await realpath(projectPath);
const imports = new Set(JSON.parse(await readFile(importsPath, 'utf8')));
const configuration = configurationPath ? JSON.parse(await readFile(configurationPath, 'utf8')) : {};
if (Object.keys(configuration).some(name => name.startsWith('standardBuffer')))
  throw new Error('application-cannot-override-standard-buffer-backend');
const bufferSource = await readFile(new URL('./node_buffer.mjs', import.meta.url), 'utf8');
const bufferBackend = bufferBuiltin(bufferSource);
const bufferDigest = 'sha256:' + createHash('sha256').update(bufferSource).digest('hex');
const bufferGlobalSource = await readFile(new URL('./buffer_globals.mjs', import.meta.url));
const bufferGlobalInitializer = await readFile(new URL('./buffer_global_initializer.mjs', import.meta.url), 'utf8');
const bufferGlobal = bufferGlobalBuiltin(bufferGlobalInitializer);
const standardNet = configuration.standardNetProfile === NET_PROFILE;
if (Object.keys(configuration).some(name => name.startsWith('standardNet') &&
    !['standardNetProfile', 'standardNetIdentities'].includes(name)) ||
    configuration.standardNetProfile !== undefined && (!standardNet ||
      configuration.runtimeProfile !== 'spidermonkey-activation-promises-clocks-imports-v1' ||
      !imports.has('latent:network/streams@0.1.0') || !configuration.standardNetIdentities || !parserPath))
  throw new Error('standard-node-net-requires-exact-stream-profile');
const netBackend = netBuiltin(await readFile(new URL('./node_net.mjs', import.meta.url), 'utf8'), standardNet);
const captured = !!configuration.moduleRoot;
const borrowProbe = borrowProbeConfiguration(configuration, imports);
const phaseFetch = configuration.standardFetchProfile === 'lsf-fetch-phase-buffered-v2';
const standardFetch = phaseFetch || configuration.standardFetchProfile === 'lsf-fetch-buffered-v1';
const fetchInterface = phaseFetch ? 'latent:http/phase-timing@0.4.0' : 'latent:http/streaming@0.3.0';
const entropyProfile = configuration.standardEntropyProfile ?? 'lsf-math-random-unsupported-v1';
const standardEntropy = entropyProfile === 'lsf-math-random-approved-v1';
if ((!standardEntropy && entropyProfile !== 'lsf-math-random-unsupported-v1') ||
    standardEntropy !== imports.has('latent:random/random@0.1.0')) {
  throw new Error('standard-entropy-requires-exact-profile-and-declared-random');
}
const standardConsole = configuration.standardConsoleProfile === 'lsf-console-strict-v1';
if (configuration.standardConsoleProfile !== undefined && (!standardConsole ||
    !imports.has('latent:log/log@0.1.0') || !parserPath)) {
  throw new Error('standard-console-requires-explicit-log-and-parser');
}
if (configuration.standardFetchProfile !== undefined && (!standardFetch ||
    configuration.runtimeProfile !== 'spidermonkey-activation-promises-clocks-imports-v1' ||
    !imports.has(fetchInterface))) {
  throw new Error('standard-fetch-requires-exact-async-runtime-and-typed-import');
}
const builtins = new Set(builtinModules.map(name => name.replace(/^node:/, '')));
const insideProject = path => {
  const inside = relative(project, path);
  return !inside.startsWith('..') && !isAbsolute(inside);
};
// Initializers run during component snapshot creation. Reject caller-dependent
// clock/entropy observations before any library initializer. The wrapper also
// checks when a module captures an intrinsic by reference.
const nativeClocks = ['spidermonkey-activation-promises-clocks-v1',
  'spidermonkey-activation-promises-clocks-imports-v1'].includes(configuration.runtimeProfile);
const clockInterfaces = ['latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'];
if (configuration.standardClockProfile !== undefined || configuration.standardClockBackendDigest !== undefined ||
    JSON.stringify(configuration.nativeClockInterfaces ?? []) !== JSON.stringify(nativeClocks ? clockInterfaces : [])) {
  throw new Error('standard-clock-requires-exact-profile-and-declared-clocks');
}
const clockProfile = nativeClocks ? 'lsf-standard-clock-native-v1' : 'lsf-standard-clock-unsupported-v1';
let guard = 'var __lsfSnapshotActive = true;\n';
const clockSource = await readFile(new URL('./clock_app.mjs', import.meta.url), 'utf8');
const clockAnchor = 'export function installApplicationClocks(';
if (clockSource.split(clockAnchor).length !== 2) throw new Error('compiler-owned-clock-install-shape');
const clockBackend = clockSource.replace(clockAnchor, 'function __lsfInstallApplicationClocks(') +
  '\n__lsfInstallApplicationClocks(' + nativeClocks + ', () => __lsfSnapshotActive);\n';
guard += clockBackend;
const entropySource = await readFile(new URL('./entropy.mjs', import.meta.url), 'utf8');
const entropyAnchor = 'export function installMathRandom(';
if (entropySource.split(entropyAnchor).length !== 2) throw new Error('compiler-owned-entropy-install-shape');
const entropyBackend = (standardEntropy ?
  "import * as __lsfEntropySource from 'latent:random/random@0.1.0';\n" : '') +
  entropySource.replace(entropyAnchor, 'function __lsfInstallMathRandom(') +
  '\n__lsfInstallMathRandom(' + (standardEntropy ? '__lsfEntropySource' : 'null') +
  ', () => __lsfSnapshotActive);\n';
guard += entropyBackend;
let backend = '';
let consoleBackend = '';
if (standardFetch) {
  const source = await readFile(new URL('./fetch.mjs', import.meta.url), 'utf8');
  const anchor = 'export function installFetch(';
  if (source.split(anchor).length !== 2) throw new Error('compiler-owned-fetch-install-shape');
  backend = "import * as __lsfFetchHttp from '" + fetchInterface + "';\n" +
    source.replace(anchor, 'function __lsfInstallFetch(') +
    (phaseFetch ? '\n__lsfInstallFetch(__lsfFetchHttp, () => __lsfSnapshotActive, globalThis, "lsf-fetch-phase-buffered-v2");\n'
      : '\n__lsfInstallFetch(__lsfFetchHttp, () => __lsfSnapshotActive);\n');
  guard += backend;
}
if (standardConsole) {
  const source = await readFile(new URL('./console.mjs', import.meta.url), 'utf8');
  const anchor = 'export function installConsole(';
  if (source.split(anchor).length !== 2) throw new Error('compiler-owned-console-install-shape');
  consoleBackend = "import * as __lsfConsoleLog from 'latent:log/log@0.1.0';\n" +
    source.replace(anchor, 'function __lsfInstallConsole(') +
    '\n__lsfInstallConsole(__lsfConsoleLog, () => __lsfSnapshotActive);\n';
  guard += consoleBackend;
}
const footer = '__lsfSnapshotActive = false;';
const options = {
  absWorkingDir: project, entryPoints: [input], outfile: output,
  bundle: true, format: 'esm', platform: 'neutral', target: 'es2022',
  conditions: configuration.conditions || [], mainFields: configuration.mainFields || ['module', 'main'],
  nodePaths: configuration.nodePaths || [],
  loader: captured ? { '.txt': 'text', '.bin': 'binary', '.json': 'json' } : {},
  sourcemap: captured ? 'external' : false, sourcesContent: false,
  minify: false, metafile: true, write: false, logLevel: 'warning',
  logOverride: { 'unsupported-dynamic-import': 'error', 'unsupported-require-call': 'error', 'direct-eval': 'error' },
  banner: { js: guard }, footer: { js: footer },
  plugins: [{ name: 'captured-closed-modules', setup(builder) {
    builder.onResolve({ filter: /.*/ }, args => {
      if (args.kind === 'dynamic-import' || args.kind.startsWith('require') && !captured) {
        return { errors: [{ text: 'dynamic module loading or uncaptured CommonJS is unsupported' }] };
      }
      if (args.path === borrowProbeBuiltin) {
        return borrowProbe ? {path: args.path, external: true} :
          {errors: [{text: 'compiler-owned-borrow-probe-not-selected'}]};
      }
      const ownedNet = netBackend.resolve(args);
      if (ownedNet) return ownedNet;
      const ownedGlobal = bufferGlobal.resolve(args);
      if (ownedGlobal) return ownedGlobal;
      if (imports.has(args.path)) return { path: args.path, external: true };
      const ownedBuffer = bufferBackend.resolve(args.path);
      if (ownedBuffer) return ownedBuffer;
      if (args.path.startsWith('node:') || builtins.has(args.path)) {
        return { errors: [{ text: 'standard-runtime-module-not-installed:' + args.path + ':' + (configuration.runtimeProfile || 'spidermonkey-public-sync-v1') }] };
      }
      if (isAbsolute(args.path) && !insideProject(resolve(args.path))) {
        return { errors: [{ text: 'module-path-outside-captured-inputs' }] };
      }
      if (args.kind !== 'entry-point' && !args.path.startsWith('.') && !captured) {
        return { errors: [{ text: 'only captured relative modules and declared WIT imports are supported' }] };
      }
      return undefined;
    });
    builder.onLoad({ filter: /.*/, namespace: 'lsf-owned-node-net' }, args => netBackend.load(args));
    builder.onLoad({ filter: /.*/, namespace: 'lsf-owned-node-buffer' }, args => bufferBackend.load(args));
    builder.onLoad({ filter: /.*/, namespace: 'lsf-owned-buffer-global' }, args => bufferGlobal.load(args));
    builder.onLoad({ filter: /.*/ }, async args => {
      const path = await realpath(args.path);
      const suffixes = captured ? ['.ts', '.js', '.mjs', '.cjs', '.json', '.txt', '.bin'] : ['.ts', '.js', '.mjs'];
      if (!insideProject(path) || !suffixes.includes(extname(path)) || (await stat(path)).size > 4 * 1024 * 1024) {
        return { errors: [{ text: 'bundle-input-outside-captured-source-or-profile' }] };
      }
      return undefined;
    });
  } }],
};
let result = await build(options);
let globalReferences = [];
if (parserPath) {
  const {parse} = await import(pathToFileURL(parserPath));
  const original = result.outputFiles.find(file => file.path === resolve(output));
  if (!original || original.contents.byteLength > 32 * 1024 * 1024)
    throw new Error('buffer-global-selection-output-bound');
  globalReferences = bufferGlobalReferences(original.text, parse);
  if (globalReferences.length) {
    // Selection is data-only. Final code retains real global reads/writes;
    // injected exported aliases would change reassignment semantics.
    bufferGlobal.enable();
    result = await build({...options, inject: [BUFFER_GLOBAL_PRIVATE]});
    const final = result.outputFiles.find(file => file.path === resolve(output));
    if (!final || final.contents.byteLength > 32 * 1024 * 1024 ||
        JSON.stringify(bufferGlobalReferences(final.text, parse)) !== JSON.stringify(globalReferences))
      throw new Error('buffer-global-selection-input-drift');
    const name = Object.keys(result.metafile.outputs).find(name => resolve(project, name) === resolve(output));
    bufferGlobal.verify(result.metafile, name);
  }
}
const inputs = [];
let total = 0;
if (bufferBackend.selection().length && !Object.hasOwn(result.metafile.inputs, 'lsf-owned-node-buffer:node:buffer'))
  throw new Error('compiler-owned-buffer-input-missing');
for (const name of Object.keys(result.metafile.inputs)) {
  if (name === 'lsf-owned-node-buffer:node:buffer') {
    if (JSON.stringify(bufferBackend.selection()) !== '["node:buffer"]')
      throw new Error('compiler-owned-buffer-input-identity');
    continue; // Authenticated compiler recipe input, not an application capture.
  }
  if (name === 'lsf-owned-node-net:node:net') continue; // Compiler-owned recipe input.
  if (name === 'lsf-owned-buffer-global:' + BUFFER_GLOBAL_PRIVATE) continue;
  const path = await realpath(resolve(project, name));
  if (!insideProject(path)) throw new Error('bundle-input-outside-captured-source');
  const bytes = await readFile(path);
  total += bytes.byteLength;
  if (inputs.length >= 8192 || total > 64 * 1024 * 1024) throw new Error('bundle-selected-input-limit');
  inputs.push({ path: relative(project, path).replaceAll('\\', '/'),
                digest: 'sha256:' + createHash('sha256').update(bytes).digest('hex'), size: bytes.byteLength });
}
const application = result.outputFiles.find(file => file.path === resolve(output));
if (!application || application.contents.byteLength > 32 * 1024 * 1024) throw new Error('bundle-output-limit');
const outputName = Object.keys(result.metafile.outputs).find(name => resolve(project, name) === application.path);
const netModules = standardNet ? netBackend.selection(result.metafile, outputName) : [];
let applicationText = application.text, deferred;
if (standardConsole) {
  const { parse } = await import(pathToFileURL(parserPath));
  if (!applicationText.startsWith(guard) || !applicationText.endsWith(footer + '\n')) {
    throw new Error('console-activation-bootstrap-shape');
  }
  deferred = activationModule(applicationText.slice(guard.length, -footer.length - 1),
    configuration.activationExports, parse);
  applicationText = guard + deferred.source + footer + '\n';
}
if (netModules.length) {
  if (!applicationText.endsWith(footer + '\n')) throw new Error('node-net-snapshot-footer-shape');
  const {parse} = await import(pathToFileURL(parserPath));
  const tree = parse(applicationText, {ecmaVersion: 2022, sourceType: 'module'});
  const nodes = [tree];
  for (let count = 0; nodes.length; ++count) {
    if (count > 1000000) throw new Error('node-net-snapshot-syntax-bound');
    const node = nodes.pop();
    if (node.type === 'Identifier' && node.name === '__lsfNetSnapshotTransport')
      throw new Error('node-net-snapshot-binding-reserved');
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) { for (const child of value) if (child?.type) nodes.push(child); }
      else if (value?.type) nodes.push(value);
    }
  }
  applicationText = applicationText.slice(0, -footer.length - 1) +
    'import * as __lsfNetSnapshotTransport from ' + JSON.stringify(NET_PRIVATE) + ';\n' +
    '__lsfNetSnapshotTransport.assertEmpty();\n' + footer + '\n';
}
if (parserPath) {
  const { parse } = await import(pathToFileURL(parserPath));
  const source = parse(applicationText, { ecmaVersion: 2022, sourceType: 'module' });
  const pending = [source];
  let nodes = 0;
  while (pending.length) {
    const node = pending.pop();
    if (++nodes > 1000000) throw new Error('bundle-syntax-node-limit');
    const callee = node.callee;
    if (['CallExpression', 'NewExpression'].includes(node.type) &&
        (callee.type === 'Identifier' && ['eval', 'Function', 'require', '__require'].includes(callee.name)
         || callee.type === 'MemberExpression' && callee.object.type === 'Identifier' && callee.object.name === 'globalThis'
             && (callee.property.name === 'eval' || callee.property.value === 'eval'))) {
      throw new Error('reachable-dynamic-code-or-module-loading-unsupported');
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) {
        for (const child of value) if (child && typeof child.type === 'string') pending.push(child);
      } else if (value && typeof value.type === 'string') pending.push(value);
    }
  }
}
for (const file of result.outputFiles) {
  let contents = file.path === application.path ? new TextEncoder().encode(applicationText) : file.contents;
  if (standardConsole && file.path === application.path + '.map') {
    const map = JSON.parse(file.text), lines = map.mappings.split(';');
    const offset = guard.split('\n').length - 1;
    for (const line of deferred.erasedLines) lines[offset + line] = '';
    lines.splice(offset, 0, ...Array(deferred.lineShift).fill(''));
    map.mappings = lines.join(';');
    contents = new TextEncoder().encode(JSON.stringify(map));
  }
  if (contents.byteLength > 32 * 1024 * 1024) throw new Error('bundle-output-limit');
  for (const [name, value] of Object.entries(result.metafile.outputs)) {
    if (resolve(project, name) === file.path) value.bytes = contents.byteLength;
  }
  await writeFile(file.path, contents, { flag: 'wx' });
}
await writeFile(output + '.inputs.json', JSON.stringify({
  ...result.metafile, capturedInputs: inputs, selection: configuration,
  standardClockProfile: clockProfile,
  standardClockBackendDigest: 'sha256:' + createHash('sha256').update(clockBackend).digest('hex'),
  snapshotGuardDigest: 'sha256:' + createHash('sha256').update(guard).digest('hex'),
  standardEntropyProfile: entropyProfile,
  standardEntropyBackendDigest: 'sha256:' + createHash('sha256').update(entropyBackend).digest('hex'),
  ...(bufferBackend.selection().length ? {standardBufferProfile: BUFFER_PROFILE,
    standardBufferBackendDigest: bufferDigest, standardBufferModules: bufferBackend.selection()} : {}),
  ...(globalReferences.length ? {standardBufferGlobalProfile: BUFFER_GLOBAL_PROFILE,
    standardBufferGlobalReferences: globalReferences,
    standardBufferGlobalIdentities: {
      selector: 'sha256:' + createHash('sha256').update(bufferGlobalSource).digest('hex'),
      initializer: 'sha256:' + createHash('sha256').update(bufferGlobalInitializer).digest('hex'),
    }} : {}),
  ...(netModules.length ? {standardNetProfile: NET_PROFILE, standardNetModules: netModules,
    standardNetIdentities: configuration.standardNetIdentities} : {}),
  ...(standardFetch ? {standardFetchProfile: configuration.standardFetchProfile,
    standardFetchBackendDigest: 'sha256:' + createHash('sha256').update(backend).digest('hex')} : {}),
  ...(standardConsole ? {standardConsoleProfile: configuration.standardConsoleProfile,
    standardConsoleBackendDigest: 'sha256:' + createHash('sha256').update(consoleBackend).digest('hex'),
    activationModuleSourceDigest: 'sha256:' + createHash('sha256').update(
      await readFile(new URL('./activation_module.mjs', import.meta.url))).digest('hex'),
    applicationInitialization: 'activation-first-export;sticky-failure;no-user-build-initializers',
    activationExports: configuration.activationExports} : {}),
  moduleResolution: 'neutral-native-exports-import-require-default-with-explicit-custom-conditions',
}, null, 2) + '\n', { flag: 'wx' });
