// Maintained conformance fixture. Observed third-party application builds and
// publication are the separate production developer-plane adapter (#234).
import {componentize} from '@bytecodealliance/componentize-js';
import {readFile, writeFile, mkdir, copyFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';

const adapter = '../../tools/angular-renderer-adapter';
const output = 'dist/runtime';
const profile = JSON.parse(await readFile('profile.json', 'utf8'));
assert.equal(process.version, 'v' + profile.nodeBuild);
await mkdir(output + '/wit', {recursive: true});
for (const name of ['bridge.js', 'timers.js']) {
  await copyFile(`${adapter}/runtime/${name}`, `${output}/${name}`);
}
await copyFile('runtime-application.js', `${output}/application.js`);
await copyFile(`${adapter}/wit/adapter.wit`, `${output}/wit/adapter.wit`);
for (const name of ['context', 'web', 'http-v2']) {
  await mkdir(`${output}/wit/deps/${name}`, {recursive: true});
  await copyFile(`../../wit/platform/${name}/package.wit`, `${output}/wit/deps/${name}/package.wit`);
}
const result = await componentize({
  sourcePath: `${output}/bridge.js`, witPath: `${output}/wit`, worldName: 'renderer',
  env: {}, disableFeatures: profile.disableFeatures, enableAot: false,
});
assert.deepEqual(result.imports, []);
assert.ok(result.component.length <= 32 * 1024 * 1024);
await writeFile(`${output}/renderer.wasm`, result.component);
console.log(JSON.stringify({
  fixture: 'actual-generic-angular-runtime', bytes: result.component.length,
  sha256: createHash('sha256').update(result.component).digest('hex'),
  imports: result.imports,
}));
