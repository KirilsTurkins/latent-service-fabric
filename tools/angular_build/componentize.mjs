// The build supervisor owns this process and its Wizer/esbuild descendants.
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import {writeFile} from 'node:fs/promises';
const [toolchain, stage] = process.argv.slice(2);
if (process.version !== 'v24.19.0') throw new Error('angular-build-runtime');
// 0.22.0 exports only an ESM import condition, not a CommonJS require entry.
// This exact module path is part of the observed, pinned tool tree.
const {componentize} = await import(pathToFileURL(path.join(toolchain,
  'node_modules/@bytecodealliance/componentize-js/src/componentize.js')));
const result = await componentize({sourcePath: path.join(stage, 'bridge.js'),
  witPath: path.join(stage, 'wit'), worldName: 'renderer', env: {},
  disableFeatures: ['stdio', 'random', 'clocks', 'http', 'fetch-event'], enableAot: false});
if (result.imports.length || result.component.length > 32 * 1024 * 1024) throw new Error('angular-private-component-profile');
await writeFile(path.join(stage, 'renderer.wasm'), result.component);
