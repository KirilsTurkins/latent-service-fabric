import {componentize} from '@bytecodealliance/componentize-js';
import {_setPreopens, _clearPreopens} from '@bytecodealliance/preview2-shim/filesystem';
import {readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import assert from 'node:assert/strict';

const profileBytes = await readFile('profile.json');
const profile = JSON.parse(profileBytes);
assert.equal(process.version, 'v' + profile.nodeBuild);
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const started = performance.now();
// The trusted build splicer needs only this fixture's WIT directory.
const witDirectory = path.resolve('.');
_setPreopens({[path.toNamespacedPath(witDirectory).replaceAll('\\', '/')]: witDirectory});
let result;
try {
  result = await componentize({
    sourcePath: './timer-bridge.js', witPath: './renderer.wit', env: {},
    disableFeatures: profile.disableFeatures,
    enableAot: profile.enableAot,
  });
} finally {
  _clearPreopens();
}
assert.deepEqual(result.imports, profile.allowedComponentImports);
assert.ok(result.component.length <= 32 * 1024 * 1024);
await writeFile('dist/renderer.wasm', result.component);
const report = {
  componentizeJs: '0.23.0', node: process.version,
  bytes: result.component.length, imports: result.imports,
  sha256: digest(result.component),
  profileSha256: digest(profileBytes),
  packageLockSha256: digest(await readFile('package-lock.json')),
  embeddingSha256: digest(await readFile('node_modules/@bytecodealliance/componentize-js/lib/starlingmonkey_embedding.wasm')),
  serverSha256: digest(await readFile('dist/server.js')),
  clientSha256: digest(await readFile('dist/client.js')),
  componentizeMillis: performance.now() - started,
};
await writeFile('dist/build-observation.json', JSON.stringify(report) + '\n');
console.log(JSON.stringify(report));
