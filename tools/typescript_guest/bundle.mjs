import { realpath, readFile, writeFile } from 'node:fs/promises';
import { resolve, relative, isAbsolute, extname } from 'node:path';
import { pathToFileURL } from 'node:url';

const [esbuildPath, projectPath, input, output, importsPath] = process.argv.slice(2);
const { build } = await import(pathToFileURL(esbuildPath));
const project = await realpath(projectPath);
const imports = new Set(JSON.parse(await readFile(importsPath, 'utf8')));
const result = await build({
  absWorkingDir: project, entryPoints: [input], outfile: output,
  bundle: true, format: 'esm', platform: 'neutral', target: 'es2022',
  sourcemap: false, minify: false, metafile: true, logLevel: 'warning',
  plugins: [{ name: 'captured-source-only', setup(builder) {
    builder.onResolve({ filter: /.*/ }, args => {
      if (args.kind === 'dynamic-import' || args.kind.startsWith('require')) {
        return { errors: [{ text: 'dynamic or CommonJS module loading is unsupported' }] };
      }
      if (imports.has(args.path)) return { path: args.path, external: true };
      if (args.kind !== 'entry-point' && !args.path.startsWith('.')) {
        return { errors: [{ text: 'only captured relative modules and declared WIT imports are supported' }] };
      }
      return undefined;
    });
  } }],
});
for (const name of Object.keys(result.metafile.inputs)) {
  const path = await realpath(resolve(project, name));
  const inside = relative(project, path);
  if (inside.startsWith('..') || isAbsolute(inside) || !['.ts', '.js', '.mjs'].includes(extname(path))) {
    throw new Error('bundle-input-outside-captured-source');
  }
}
await writeFile(output + '.inputs.json', JSON.stringify(result.metafile, null, 2) + '\n', { flag: 'wx' });
