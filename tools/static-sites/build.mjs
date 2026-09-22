// Fixed AOT CSR recipe, separate from static capture and package assembly.
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import assert from 'node:assert/strict';

const [toolchain, input, output, mode] = process.argv.slice(2);
assert.equal(process.version, 'v24.19.0');
assert.ok(['configure', 'bundle'].includes(mode));
const requireTool = createRequire(path.join(toolchain, 'package.json'));
const modules = path.join(toolchain, 'node_modules');
if (mode === 'configure') {
  await mkdir(output, {recursive: true});
  await writeFile(path.join(output, 'tsconfig.json'), JSON.stringify({
    compilerOptions: {target: 'ES2022', module: 'ES2022', moduleResolution: 'bundler',
      experimentalDecorators: true, strict: true, skipLibCheck: true,
      rootDir: input, outDir: path.join(output, 'compiled'), lib: ['ES2022', 'DOM'],
      paths: {'@angular/*': [path.join(modules, '@angular/*')],
        'rxjs': [path.join(modules, 'rxjs')], 'rxjs/*': [path.join(modules, 'rxjs/*')]}, types: []},
    angularCompilerOptions: {compilationMode: 'full', strictTemplates: true},
    files: ['main.ts', 'order.ts', 'version.ts'].map(name => path.join(input, name)),
  }));
} else {
  const {build} = requireTool('esbuild');
  const {transformAsync} = await import(pathToFileURL(requireTool.resolve('@babel/core')));
  const {default: linker} = await import(pathToFileURL(requireTool.resolve('@angular/compiler-cli/linker/babel')));
  const plugin = {name: 'fixed-angular-linker', setup(builder) {
    builder.onLoad({filter: /\.mjs$/}, async ({path: filename}) => {
      if (!filename.replaceAll('\\', '/').includes('/@angular/')) return;
      const result = await transformAsync(await readFile(filename, 'utf8'), {
        filename, plugins: [linker], configFile: false, babelrc: false, sourceMaps: false});
      return {contents: result.code, loader: 'js'};
    });
  }};
  const result = await build({entryPoints: [path.join(output, 'compiled/main.js')],
    bundle: true, splitting: true, format: 'esm', platform: 'browser', target: 'es2022',
    outdir: path.join(output, 'public/assets'), entryNames: '[name]-[hash]', chunkNames: '[name]-[hash]',
    minify: true, legalComments: 'eof', metafile: true, plugins: [plugin], nodePaths: [modules],
    define: {ngDevMode: 'false', ngJitMode: 'false'}, sourcemap: false, logLevel: 'silent'});
  const inputs = Object.keys(result.metafile.inputs);
  assert.ok(inputs.length > 0 && inputs.length <= 4096);
  const dependencies = new Set();
  for (const filename of inputs) {
    const absolute = path.resolve(filename);
    const compiled = path.relative(path.join(output, 'compiled'), absolute);
    const dependency = path.relative(modules, absolute).replaceAll('\\', '/');
    if (!compiled.startsWith('..') && !path.isAbsolute(compiled)) continue;
    assert.ok(!dependency.startsWith('..') && !path.isAbsolute(dependency));
    const parts = dependency.split('/');
    dependencies.add(parts[0].startsWith('@') ? parts.slice(0, 2).join('/') : parts[0]);
  }
  const outputs = [];
  for (const [filename, record] of Object.entries(result.metafile.outputs)) {
    const name = path.relative(path.join(output, 'public'), path.resolve(filename)).replaceAll('\\', '/');
    assert.match(name, /^assets\/[A-Za-z0-9_-]+\.js$/);
    assert.ok(record.bytes <= 8 * 1024 * 1024 && !record.imports.some(row => row.external));
    outputs.push({name, entry: record.entryPoint?.replaceAll('\\', '/').endsWith('/main.js') ?? false,
      lazy: record.entryPoint?.replaceAll('\\', '/').endsWith('/order.js') ?? false});
  }
  assert.ok(outputs.length >= 2 && outputs.length <= 16 && outputs.filter(row => row.entry).length === 1);
  assert.ok(outputs.some(row => row.lazy));
  await writeFile(path.join(output, 'outputs.json'), JSON.stringify({
    outputs: outputs.sort((a, b) => a.name.localeCompare(b.name)), dependencies: [...dependencies].sort(),
    aot: true, serverRenderer: false, sourceMaps: false, lifecycleScripts: false,
  }));
}
