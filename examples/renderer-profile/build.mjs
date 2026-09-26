import { build } from 'esbuild';
import { transformAsync } from '@babel/core';
import linker from '@angular/compiler-cli/linker/babel';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
const linkerPlugin = {name:'angular-linker', setup(builder) {
  builder.onLoad({filter:/\.mjs$/}, async ({path}) => {
    if (!path.replaceAll('\\','/').includes('/@angular/')) return;
    const r = await transformAsync(await readFile(path, 'utf8'), {filename:path, plugins:[linker], configFile:false, babelrc:false, sourceMaps:false});
    return {contents:r.code, loader:'js'};
  });
  builder.onResolve({filter:/^xhr2$/}, () => ({path:'xhr2', namespace:'denied'}));
  builder.onLoad({filter:/.*/, namespace:'denied'}, () => ({contents:'export class XMLHttpRequest { constructor() { throw new Error("renderer-xhr-denied"); } }',loader:'js'}));
}};
await mkdir('dist', {recursive:true});
for (const name of ['server','client']) {
  const result = await build({entryPoints:[`compiled/${name}.js`], bundle:true, format:'esm', platform:'browser', target:'es2022', outfile:`dist/${name}.js`, minify:true, legalComments:'eof', metafile:true, plugins:[linkerPlugin], define:{ngDevMode:'false',ngJitMode:'false'}});
  await writeFile(`dist/${name}.meta.json`,JSON.stringify(result.metafile));
}
