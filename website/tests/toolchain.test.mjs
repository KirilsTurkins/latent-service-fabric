import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import serialize from 'serialize-javascript';
import {template} from 'lodash-es';
import {repositoryRoot, websiteRoot} from '../lib/repository.mjs';

test('website pins and lock agree without a root workspace or dependency lifecycle scripts', () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'package.json'), 'utf8'));
  const lock = JSON.parse(fs.readFileSync(path.join(websiteRoot, 'package-lock.json'), 'utf8'));
  assert.equal(manifest.private, true);
  assert.equal(manifest.engines.node, '24.19.0');
  assert.equal(manifest.engines.npm, '11.19.1');
  for (const [name, version] of Object.entries({...manifest.dependencies, ...manifest.devDependencies})) {
    assert.match(version, /^\d+\.\d+\.\d+$/);
    assert.equal(lock.packages[`node_modules/${name}`].version, version);
  }
  assert.equal(lock.lockfileVersion, 3);
  for (const [location, dependency] of Object.entries(lock.packages)) {
    if (location === '') continue;
    assert.match(dependency.version, /^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/);
    assert.equal(new URL(dependency.resolved).origin, 'https://registry.npmjs.org');
    assert.match(dependency.integrity, /^sha512-[A-Za-z0-9+/]+={0,2}$/);
    assert.equal(dependency.link, undefined);
  }
  assert.match(fs.readFileSync(path.join(websiteRoot, '.npmrc'), 'utf8'), /^ignore-scripts=true$/m);
  assert.equal(fs.existsSync(path.join(websiteRoot, '../package.json')), false);
  assert.equal(fs.existsSync(path.join(websiteRoot, 'docs')), false);
});

test('reviewed security overrides retain the APIs used by the actual build dependencies', () => {
  const requireSockjs = createRequire(path.join(websiteRoot, 'node_modules/sockjs/package.json'));
  assert.match(requireSockjs('uuid').v4(), /^[a-f0-9-]{14}4[a-f0-9-]{21}$/);
  assert.equal(template('Hello <%= name %>')({name: 'fixture'}), 'Hello fixture');
  const serialized = serialize({message: '</script>', observed: new Date(0)});
  assert.equal(serialized.includes('</script>'), false);
  assert.match(serialized, /new Date/);
});

test('Docusaurus client configuration never serializes the private source index or absolute build paths', async () => {
  const {default: configuration} = await import('../docusaurus.config.ts');
  const serialized = JSON.stringify(configuration);
  assert.equal(serialized.includes(JSON.stringify(repositoryRoot).slice(1, -1)), false);
  assert.equal(serialized.includes('"paths":'), false);
  assert.equal(serialized.includes('"directories":'), false);
  assert.ok(configuration.staticDirectories.every(directory => !path.isAbsolute(directory)));
});
