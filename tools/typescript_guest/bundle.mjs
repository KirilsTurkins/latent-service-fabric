import { realpath, readFile, writeFile, stat } from 'node:fs/promises';
import { resolve, relative, isAbsolute, extname } from 'node:path';
import { builtinModules } from 'node:module';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import { activationModule } from './activation_module.mjs';

const [esbuildPath, projectPath, input, output, importsPath, configurationPath, parserPath] = process.argv.slice(2);
const { build } = await import(pathToFileURL(esbuildPath));
const project = await realpath(projectPath);
const imports = new Set(JSON.parse(await readFile(importsPath, 'utf8')));
const configuration = configurationPath ? JSON.parse(await readFile(configurationPath, 'utf8')) : {};
const captured = !!configuration.moduleRoot;
const standardFetch = configuration.standardFetchProfile === 'lsf-fetch-buffered-v1';
const standardConsole = configuration.standardConsoleProfile === 'lsf-console-strict-v1';
if (configuration.standardConsoleProfile !== undefined && (!standardConsole ||
    !imports.has('latent:log/log@0.1.0') || !parserPath)) {
  throw new Error('standard-console-requires-explicit-log-and-parser');
}
if (configuration.standardFetchProfile !== undefined && (!standardFetch ||
    configuration.runtimeProfile !== 'spidermonkey-activation-promises-clocks-imports-v1' ||
    !imports.has('latent:http/streaming@0.3.0'))) {
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
if (configuration.standardClockProfile !== undefined || configuration.standardClockBackendDigest !== undefined ||
    nativeClocks && !['latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'].every(name => imports.has(name))) {
  throw new Error('standard-clock-requires-exact-profile-and-declared-clocks');
}
const clockProfile = nativeClocks ? 'lsf-standard-clock-native-v1' : 'lsf-standard-clock-unsupported-v1';
let guard = 'var __lsfSnapshotActive = true;\n' + (captured || standardFetch || standardConsole ? `
var __lsfOriginalRandom = Math.random;
Math.random = function() {
  if (__lsfSnapshotActive) throw new Error('snapshot-time-entropy-observation-unsupported');
  return __lsfOriginalRandom();
};
` : '');
const clockSource = await readFile(new URL('./clock_app.mjs', import.meta.url), 'utf8');
const clockAnchor = 'export function installApplicationClocks(';
if (clockSource.split(clockAnchor).length !== 2) throw new Error('compiler-owned-clock-install-shape');
const clockBackend = clockSource.replace(clockAnchor, 'function __lsfInstallApplicationClocks(') +
  '\n__lsfInstallApplicationClocks(' + nativeClocks + ', () => __lsfSnapshotActive);\n';
guard += clockBackend;
let backend = '';
let consoleBackend = '';
if (standardFetch) {
  const source = await readFile(new URL('./fetch.mjs', import.meta.url), 'utf8');
  const anchor = 'export function installFetch(';
  if (source.split(anchor).length !== 2) throw new Error('compiler-owned-fetch-install-shape');
  backend = "import * as __lsfFetchHttp from 'latent:http/streaming@0.3.0';\n" +
    source.replace(anchor, 'function __lsfInstallFetch(') +
    '\n__lsfInstallFetch(__lsfFetchHttp, () => __lsfSnapshotActive);\n';
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
const result = await build({
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
      if (imports.has(args.path)) return { path: args.path, external: true };
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
    builder.onLoad({ filter: /.*/ }, async args => {
      const path = await realpath(args.path);
      const suffixes = captured ? ['.ts', '.js', '.mjs', '.cjs', '.json', '.txt', '.bin'] : ['.ts', '.js', '.mjs'];
      if (!insideProject(path) || !suffixes.includes(extname(path)) || (await stat(path)).size > 4 * 1024 * 1024) {
        return { errors: [{ text: 'bundle-input-outside-captured-source-or-profile' }] };
      }
      return undefined;
    });
  } }],
});
const inputs = [];
let total = 0;
for (const name of Object.keys(result.metafile.inputs)) {
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
