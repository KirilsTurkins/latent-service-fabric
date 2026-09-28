// Real packaging/signing of bounded deterministic transfer fixtures, not a cloud model.
import './qualification_inputs.mjs';
import {readFile, writeFile, mkdir, realpath} from 'node:fs/promises';
import {main} from '../static-release/release.mjs';
import {jsonBytes, sha256, writeBytes, writeJson} from '../static-release/files.mjs';

const {work} = JSON.parse(await readFile('/work/current.json', 'utf8'));
const expected = [];
for (const name of ['alpha', 'beta']) {
  const build = work + '/' + name + '-build'; await mkdir(build, {mode: 0o700});
  const script = Buffer.from(('/* ' + name + ': maintained transfer fixture */\n').repeat(65536));
  const values = {'index.html': Buffer.from('<!doctype html><title>' + name + '</title>\n'),
    'bundle.js': script, 'unread.js': Buffer.from('/* previously unread immutable asset ' + name + ' */\n')};
  const observations = [];
  for (const [file, bytes] of Object.entries(values)) {
    if (bytes.length > 3 * 1024 * 1024) throw new Error('transfer-fixture-bound');
    await writeFile(build + '/' + file, bytes, {mode: 0o600, flag: 'wx'});
  }
  for (const [kind, value] of [['source', Object.entries(values).map(([path, bytes]) => ({path, digest: sha256(bytes)}))],
    ['toolchain', {node: process.version}], ['build', {mode: 'deterministic-transfer-fixture', frameworkBuildExecuted: false}]]) {
    const bytes = jsonBytes(value); await writeBytes(build + '/' + kind + '.json', bytes);
    observations.push({kind, source: kind + '.json', digest: sha256(bytes)});
  }
  const inventory = work + '/' + name + '-inventory.json', prepared = work + '/' + name;
  await writeJson(inventory, {formatVersion: 1, profile: 'static-site-input-v1', name: 'transfer-' + name, version: '1.0.0',
    assets: Object.keys(values).map(file => ({path: '/' + file, source: file})), entryDocument: '/index.html',
    directoryIndex: {mode: 'disabled', document: '/index.html'}, fallback: {mode: 'none'}, excluded: [], observations});
  await main(['prepare', '--cli', '/native/bin/latent', '--python', await realpath('/usr/bin/python3'),
    '--build-output', build, '--inventory', inventory, '--repository', 'https://example.com/anonymous/frontend', '--output', prepared]);
  const approval = work + '/' + name + '-approval.json';
  await main(['request-signing', '--prepared', prepared, '--identities', work + '/identities.json',
    '--lifetime-seconds', '1800', '--output', approval]);
  await main(['sign', '--cli', '/native/bin/latent', '--prepared', prepared, '--approval', approval,
    '--publisher-key', work + '/publisher.der', '--builder-key', work + '/builder.der', '--policy', work + '/policy.json',
    '--tenant', 'tests', '--output', work + '/' + name + '-evidence']);
  expected.push({name, path: '/' + name + '/bundle.js', digest: sha256(script), size: script.length});
}
await writeJson('/edge/compression.json', expected);
const config = JSON.parse(await readFile('/edge/edge.json', 'utf8')); config.compression = 'gzip';
await writeFile('/edge/edge.json', jsonBytes(config), {mode: 0o600});
console.log(JSON.stringify({compressionInputs: true, exactSourceOutputPreserved: true, expected}));
