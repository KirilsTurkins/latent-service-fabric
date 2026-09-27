import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {build, stop} from 'esbuild';
import {transformAsync} from '@babel/core';
import linker from '@angular/compiler-cli/linker/babel';

const root = path.dirname(fileURLToPath(import.meta.url));
const [destination, selectedMount, ...extra] = process.argv.slice(2);
assert.ok(destination && ['/', '/app'].includes(selectedMount) && extra.length === 0);
const mount = selectedMount === '/' ? '' : selectedMount;
const output = path.resolve(destination);
await mkdir(output, {recursive: true});
const plugin = {name: 'pinned-angular-aot-linker', setup(builder) {
  builder.onLoad({filter: /\.mjs$/}, async ({path: filename}) => {
    if (!filename.replaceAll('\\', '/').includes('/node_modules/')) return;
    const code = await readFile(filename, 'utf8');
    if (!code.includes('ɵɵngDeclare')) return {contents: code, loader: 'js'};
    const result = await transformAsync(code, {filename, plugins: [linker], configFile: false, babelrc: false, sourceMaps: false});
    return {contents: result.code, loader: 'js'};
  });
}};
try {
  const result = await build({entryPoints: [path.join(root, 'target/angular/main.js')], bundle: true,
    splitting: true, format: 'esm', platform: 'browser', target: 'es2022',
    outdir: path.join(output, 'assets'), entryNames: '[name]-[hash]', chunkNames: '[name]-[hash]',
    minify: true, legalComments: 'eof', metafile: true, plugins: [plugin],
    define: {ngDevMode: 'false', ngJitMode: 'false', LSF_MOUNT: JSON.stringify(mount)}, sourcemap: false});
  const files = Object.entries(result.metafile.outputs);
  assert.ok(files.length <= 32 && files.some(([, row]) => row.entryPoint?.endsWith('order.js')));
  const entry = files.find(([, row]) => row.entryPoint?.endsWith('main.js'));
  const script = path.relative(output, path.resolve(entry[0])).replaceAll('\\', '/');
  await writeFile(path.join(output, 'index.html'), `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Framework compatibility</title></head><body><lsf-framework-app></lsf-framework-app><script type="module" src="${mount}/${script}"></script></body></html>`);
  console.log(JSON.stringify({framework: 'Angular 20.3.32 / PrimeNG 20.4.0', mount, lazyChunks: files.length - 1}));
} finally { stop(); }
