import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const read = name => JSON.parse(fs.readFileSync(path.join(root, name), 'utf8'));
const website = read('package.json');
const toolchain = read('toolchain/package.json');
const lock = read('toolchain/package-lock.json');
assert.equal(toolchain.dependencies.npm, website.engines.npm);
assert.equal(website.packageManager, `npm@${toolchain.dependencies.npm}`);
assert.equal(read('content/toolchain.json').npm, toolchain.dependencies.npm);
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
console.log(JSON.stringify({npm: toolchain.dependencies.npm, verifiedInstalledPackages: packages}));
