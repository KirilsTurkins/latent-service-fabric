// Fixed compiler/linker recipe. No application npm scripts, tsconfig, Babel
// configuration, esbuild plugins or environment substitutions are loaded.
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {checkSource} from './guard.mjs';

const [toolchain, input, output, mode] = process.argv.slice(2);
if (process.version !== 'v24.19.0' || !['configure', 'bundle'].includes(mode)) throw new Error('angular-build-runtime');
const requireTool = createRequire(path.join(toolchain, 'package.json'));
const ts = requireTool('typescript');
const config = JSON.parse(await readFile(path.join(input, 'angular-build.json'), 'utf8'));
const names = new Set(config.sources);
await mkdir(output, {recursive: true});
for (const name of config.sources.filter(name => name.endsWith('.ts'))) {
  checkSource(ts, name, await readFile(path.join(input, name), 'utf8'), names);
}
if (mode === 'configure') {
  const modules = path.join(toolchain, 'node_modules');
  await writeFile(path.join(output, 'tsconfig.json'), JSON.stringify({
    compilerOptions: {target: 'ES2022', module: 'ES2022', moduleResolution: 'bundler',
      experimentalDecorators: true, strict: true, skipLibCheck: true, rootDir: input,
      outDir: path.join(output, 'compiled'), lib: ['ES2022', 'DOM'],
      paths: {'@angular/*': [path.join(modules, '@angular/*')], 'rxjs': [path.join(modules, 'rxjs')],
        'rxjs/*': [path.join(modules, 'rxjs/*')]}, types: []},
    angularCompilerOptions: {compilationMode: 'full', strictTemplates: true},
    files: config.sources.filter(name => name.endsWith('.ts')).map(name => path.join(input, name)),
  }));
} else {
  const {build} = requireTool('esbuild');
  const {transformAsync} = await import(pathToFileURL(requireTool.resolve('@babel/core')));
  const {default: linker} = await import(pathToFileURL(requireTool.resolve('@angular/compiler-cli/linker/babel')));
  const plugin = {name: 'fixed-angular-linker', setup(builder) {
    builder.onLoad({filter: /\.mjs$/}, async ({path: filename}) => {
      if (!filename.replaceAll('\\', '/').includes('/@angular/')) return;
      const result = await transformAsync(await readFile(filename, 'utf8'), {filename,
        plugins: [linker], configFile: false, babelrc: false, sourceMaps: false});
      return {contents: result.code, loader: 'js'};
    });
    builder.onResolve({filter: /^xhr2$/}, () => ({path: 'xhr2', namespace: 'denied'}));
    builder.onLoad({filter: /.*/, namespace: 'denied'}, () => ({
      contents: 'export class XMLHttpRequest {constructor(){throw new Error("renderer-xhr-denied")}}', loader: 'js'}));
  }};
  const used = {};
  for (const area of ['server', 'client']) {
    const entry = path.join(output, 'compiled', config[area + 'Entry'].replace(/\.ts$/, '.js'));
    const result = await build({entryPoints: [entry], bundle: true, format: 'esm', platform: 'browser',
      target: 'es2022', outfile: path.join(output, area + '.js'), minify: true,
      legalComments: 'eof', metafile: true, plugins: [plugin], nodePaths: [path.join(toolchain, 'node_modules')],
      define: {ngDevMode: 'false', ngJitMode: 'false'}, sourcemap: false, logLevel: 'silent'});
    const records = Object.keys(result.metafile.inputs);
    if (records.length > 4096) throw new Error('angular-bundle-input-count');
    for (const name of records) {
      if (name === 'denied:xhr2') continue;
      const absolute = path.resolve(name);
      const local = path.relative(path.join(output, 'compiled'), absolute).replaceAll('\\', '/');
      const dependency = path.relative(path.join(toolchain, 'node_modules'), absolute).replaceAll('\\', '/');
      if (!local.startsWith('../') && !path.isAbsolute(local)) {
        const first = local.split('/')[0];
        if (!['shared', area].includes(first)) throw new Error('angular-client-server-separation');
      } else if (dependency.startsWith('../') || path.isAbsolute(dependency)) {
        throw new Error('angular-bundle-outside-capture');
      }
    }
    const products = Object.values(result.metafile.outputs);
    if (products.length !== 1 || products[0].imports.length || products[0].bytes > 8 * 1024 * 1024) {
      throw new Error('angular-bundle-output-profile');
    }
    used[area] = records.map(name => {
      const index = name.replaceAll('\\', '/').indexOf('/node_modules/');
      return index < 0 ? null : name.replaceAll('\\', '/').slice(index + 14);
    }).filter(Boolean).sort();
  }
  await writeFile(path.join(output, 'bundle-inputs.json'), JSON.stringify(used));
}
