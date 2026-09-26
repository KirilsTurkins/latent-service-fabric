import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

assert.equal(process.argv.length, 3);
const toolchain = resolve(process.argv[2]);
const locked = JSON.parse(await readFile(resolve(toolchain, 'package-lock.json'), 'utf8'));
const profile = JSON.parse(await readFile(new URL('../../examples/renderer-profile/profile.json', import.meta.url), 'utf8'));
assert.equal(process.versions.node, profile.nodeBuild);
assert.equal(profile.enableAot, false);
assert.equal(locked.packages['node_modules/@bytecodealliance/weval'].version, '0.5.0');
const weval = await import(pathToFileURL(resolve(toolchain, 'node_modules/@bytecodealliance/weval/index.js')).href);
const {componentize, version} = await import(pathToFileURL(resolve(toolchain, 'node_modules/@bytecodealliance/componentize-js/src/componentize.js')).href);
assert.equal(typeof weval.default, 'function');
assert.equal(typeof componentize, 'function');
assert.equal(version, profile.componentizeJs);
console.log(JSON.stringify({fixture: 'renderer-extractor-remediation', node: process.version,
  componentizeJs: version, weval: '0.5.0', aot: false, validation: 'imports-only'}));
