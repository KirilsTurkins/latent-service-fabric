// Fresh signed v2 of one site; the independently published documentation is unchanged.
import {readFile, writeFile, realpath, mkdir} from 'node:fs/promises';
import {main} from '../static-release/release.mjs';
import {jsonBytes, sha256, writeBytes, writeJson} from '../static-release/files.mjs';

const {work} = JSON.parse(await readFile('/work/current.json', 'utf8'));
const build = work + '/site-v2-build';
await mkdir(build, {mode: 0o700});
const html = Buffer.from('<!doctype html><html lang="en"><title>Site v2</title><h1>Updated site</h1></html>\n');
await writeBytes(build + '/index.html', html);
const observations = [];
for (const [kind, value] of [['source', [{path: 'index.html', sha256: sha256(html)}]],
  ['toolchain', {node: process.version}], ['build', {mode: 'supplied-maintained-files', frameworkBuildExecuted: false}]]) {
  const bytes = jsonBytes(value); await writeBytes(build + '/' + kind + '.json', bytes);
  observations.push({kind, source: kind + '.json', digest: sha256(bytes)});
}
const inventory = work + '/site-v2-inventory.json', prepared = work + '/site-v2';
await writeJson(inventory, {formatVersion: 1, profile: 'static-site-input-v1', name: 'frontend-site', version: '2.0.0',
  assets: [{path: '/index.html', source: 'index.html'}], entryDocument: '/index.html',
  directoryIndex: {mode: 'disabled', document: '/index.html'}, fallback: {mode: 'spa', document: '/index.html'},
  excluded: [], observations});
await main(['prepare', '--cli', '/native/bin/latent', '--python', await realpath('/usr/bin/python3'),
  '--build-output', build, '--inventory', inventory, '--repository', 'https://example.com/anonymous/frontend', '--output', prepared]);
const approval = work + '/site-v2-approval.json';
await main(['request-signing', '--prepared', prepared, '--identities', work + '/identities.json',
  '--lifetime-seconds', '1800', '--output', approval]);
await main(['sign', '--cli', '/native/bin/latent', '--prepared', prepared, '--approval', approval,
  '--publisher-key', work + '/publisher.der', '--builder-key', work + '/builder.der', '--policy', work + '/policy.json',
  '--tenant', 'tests', '--output', work + '/site-v2-evidence']);
console.log(JSON.stringify({signedUpdatedSite: true, unrelatedPackageUnchanged: true}));
