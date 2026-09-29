import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const read = name => JSON.parse(fs.readFileSync(path.join(root, name), 'utf8'));
const website = read('package.json');
const toolchain = read('toolchain/package.json');
const lock = read('toolchain/package-lock.json');
const source = read('toolchain/source.json');
const npmVersion = source.base.version;
assert.equal(toolchain.dependencies.npm, lock.packages['node_modules/npm'].resolved);
assert.equal(lock.packages['node_modules/npm'].version, npmVersion);
assert.equal(npmVersion, website.engines.npm);
assert.equal(website.packageManager, `npm@${npmVersion}`);
assert.equal(read('content/toolchain.json').npm, npmVersion);
for (const patch of source.patches) {
  assert.equal(read(`toolchain/node_modules/npm/node_modules/${patch.name}/package.json`).version, patch.version);
}
assert.ok(Object.keys(lock.packages).length > 1 && Object.keys(lock.packages).length <= 300);
let packages = 0;
for (const [location, expected] of Object.entries(lock.packages)) {
  if (!location) continue;
  assert.match(location, /^node_modules\/(?:[A-Za-z0-9@._-]+\/)*[A-Za-z0-9@._-]+$/);
  assert.ok(location.split('/').every(part => part !== '.' && part !== '..'));
  const actual = read(`toolchain/${location}/package.json`);
  assert.equal(actual.version, expected.version, `Installed package manager dependency differs: ${location}`);
  packages++;
}
console.log(JSON.stringify({npm: npmVersion, distribution: source.profile, verifiedInstalledPackages: packages}));
