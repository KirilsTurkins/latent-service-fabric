import { realpath, readFile, writeFile, stat } from 'node:fs/promises';
import { resolve, relative, isAbsolute, extname } from 'node:path';
import { builtinModules } from 'node:module';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';

const [esbuildPath, projectPath, input, output, importsPath, configurationPath, parserPath] = process.argv.slice(2);
const { build } = await import(pathToFileURL(esbuildPath));
const project = await realpath(projectPath);
const imports = new Set(JSON.parse(await readFile(importsPath, 'utf8')));
const configuration = configurationPath ? JSON.parse(await readFile(configurationPath, 'utf8')) : {};
const captured = !!configuration.moduleRoot;
const builtins = new Set(builtinModules.map(name => name.replace(/^node:/, '')));
const insideProject = path => {
  const inside = relative(project, path);
  return !inside.startsWith('..') && !isAbsolute(inside);
};
// Initializers run during component snapshot creation. Reject caller-dependent
// clock/entropy observations before any library initializer. The wrapper also
// checks when a module captures an intrinsic by reference.
const guard = captured ? `
var __lsfSnapshotActive = true;
var __lsfOriginalRandom = Math.random, __lsfOriginalDate = Date;
Math.random = function() {
  if (__lsfSnapshotActive) throw new Error('snapshot-time-entropy-observation-unsupported');
  return __lsfOriginalRandom();
};
globalThis.Date = new Proxy(__lsfOriginalDate, {
  apply(target, self, args) {
    if (__lsfSnapshotActive) throw new Error('snapshot-time-clock-observation-unsupported');
    return Reflect.apply(target, self, args);
  },
  construct(target, args, receiver) {
    if (__lsfSnapshotActive && args.length === 0) throw new Error('snapshot-time-clock-observation-unsupported');
    return Reflect.construct(target, args, receiver);
  },
  get(target, name, receiver) {
    if (name === 'now') return function() {
      if (__lsfSnapshotActive) throw new Error('snapshot-time-clock-observation-unsupported');
      return target.now();
    };
    return Reflect.get(target, name, receiver);
  }
});
` : '';
const result = await build({
  absWorkingDir: project, entryPoints: [input], outfile: output,
  bundle: true, format: 'esm', platform: 'neutral', target: 'es2022',
  conditions: configuration.conditions || [], mainFields: configuration.mainFields || ['module', 'main'],
  nodePaths: configuration.nodePaths || [],
  loader: captured ? { '.txt': 'text', '.bin': 'binary', '.json': 'json' } : {},
  sourcemap: captured ? 'external' : false, sourcesContent: false,
  minify: false, metafile: true, write: false, logLevel: 'warning',
  logOverride: { 'unsupported-dynamic-import': 'error', 'unsupported-require-call': 'error', 'direct-eval': 'error' },
  banner: { js: guard }, footer: { js: captured ? '__lsfSnapshotActive = false;' : '' },
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
if (parserPath) {
  const { parse } = await import(pathToFileURL(parserPath));
  const source = parse(application.text, { ecmaVersion: 2022, sourceType: 'module' });
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
  if (file.contents.byteLength > 32 * 1024 * 1024) throw new Error('bundle-output-limit');
  await writeFile(file.path, file.contents, { flag: 'wx' });
}
await writeFile(output + '.inputs.json', JSON.stringify({
  ...result.metafile, capturedInputs: inputs, selection: configuration,
  snapshotGuardDigest: 'sha256:' + createHash('sha256').update(guard).digest('hex'),
  moduleResolution: 'neutral-native-exports-import-require-default-with-explicit-custom-conditions',
}, null, 2) + '\n', { flag: 'wx' });
