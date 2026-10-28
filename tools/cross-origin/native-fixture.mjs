// Disposable signed inputs for the actual native ingress campaign. No policy
// peer serves these bytes: latent package build/verify and latentd admit them.
import assert from 'node:assert/strict';
import {mkdir, readFile, writeFile, chmod, realpath} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {identity} from '../static-release/test-identity.mjs';
import {approvalPlan} from '../static-release/evidence.mjs';
import {sha256, jsonBytes, writeBytes, writeJson} from '../static-release/files.mjs';
import {main} from '../static-release/release.mjs';
import {run} from '../static-release/process.mjs';

const repository = 'https://example.com/anonymous/cross-origin-fixture';
const load = async file => JSON.parse(await readFile(file, 'utf8'));

export async function sign(cli, work, name, label, lifetime) {
  assert.ok(['a', 'b', 'anonymous', 'foreign'].includes(name));
  assert.match(label, /^[a-z][a-z-]{0,31}$/);
  assert.ok(Number.isInteger(lifetime) && lifetime >= 10 && lifetime <= 1800);
  const roles = await load(path.join(work, 'identities.json'));
  const prepared = path.join(work, name);
  const receipt = await load(path.join(prepared, 'PREPARE-COMPLETE.json'));
  const issuedAt = Math.floor(Date.now() / 1000), expiresAt = issuedAt + lifetime;
  const approval = path.join(work, name + '-' + label + '-approval.json');
  await writeJson(approval, approvalPlan({...receipt, ...roles, issuedAt, expiresAt}));
  const evidence = path.join(work, name + '-' + label);
  const signed = await main(['sign', '--cli', cli, '--prepared', prepared, '--approval', approval,
    '--publisher-key', path.join(work, 'publisher.der'), '--builder-key', path.join(work, 'builder.der'),
    '--output', evidence, '--policy', path.join(work, 'policy.json'),
    '--tenant', name === 'foreign' ? 'foreign' : 'tests']);
  assert.equal(signed.packageDigest, receipt.packageDigest);
  return {packageDigest: signed.packageDigest, issuedAt, expiresAt};
}

export async function prepare(cli, python, font, work) {
  assert.equal(process.platform, 'linux');
  assert.notEqual(process.getuid(), 0);
  await mkdir(work, {mode: 0o700});
  const {roles, policy} = await identity(work, repository);
  policy.tenants = ['foreign', 'tests'].map(tenant => ({tenant, publishers: [roles.publisher.id]}));
  await writeFile(path.join(work, 'policy.json'), jsonBytes(policy), {mode: 0o600});
  await writeJson(path.join(work, 'identities.json'), roles);
  const fontBytes = await readFile(font);
  assert.ok(fontBytes.length <= 128 * 1024 && fontBytes.subarray(0, 4).toString() === 'wOF2');
  const fixtures = {};
  for (const name of ['a', 'b', 'anonymous', 'foreign']) {
    const build = path.join(work, name + '-build');
    await mkdir(build, {mode: 0o700});
    // A and B deliberately have identical script bytes and hence identical
    // representation ETags, but distinct signed package/publication identities.
    const files = new Map([
      ['app.js', Buffer.from('globalThis.lsfCrossOriginLoads = (globalThis.lsfCrossOriginLoads ?? 0) + 1;\n')],
      ['font.woff2', fontBytes],
      ['index.html', Buffer.from('<!doctype html><title>Native CORS ' + name + '</title><p>Signed static ' + name + '</p>')],
      ['style.css', Buffer.from('#sample { color: rgb(20, 50, 80); }\n')],
    ]);
    const inventory = [];
    for (const [file, bytes] of files) {
      await writeBytes(path.join(build, file), bytes);
      inventory.push({path: file, digest: sha256(bytes), size: bytes.length});
    }
    const observations = [];
    for (const [kind, value] of [['source', inventory], ['toolchain', {node: process.version}],
      ['build', {mode: 'maintained-fixture-files', frameworkBuildExecuted: false}]]) {
      const bytes = jsonBytes(value);
      await writeBytes(path.join(build, kind + '.json'), bytes);
      observations.push({kind, source: kind + '.json', digest: sha256(bytes)});
    }
    const input = path.join(work, name + '-inventory.json');
    await writeJson(input, {formatVersion: 1, profile: 'static-site-input-v1',
      name: 'cors-fixture-' + name, version: '1.0.0',
      assets: [...files.keys()].map(file => ({path: '/' + file, source: file})),
      entryDocument: '/index.html', directoryIndex: {mode: 'redirect', document: '/index.html'},
      fallback: {mode: 'spa', document: '/index.html'}, excluded: [], observations});
    await main(['prepare', '--cli', cli, '--python', python, '--build-output', build,
      '--inventory', input, '--repository', repository, '--output', path.join(work, name)]);
    fixtures[name] = await sign(cli, work, name, 'evidence', 900);
  }
  const tls = path.join(work, 'tls');
  await mkdir(tls, {mode: 0o700});
  await run(await realpath('/usr/bin/openssl'), ['req', '-x509', '-newkey', 'ec',
    '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-sha256', '-days', '1', '-subj', '/CN=localhost',
    '-addext', 'subjectAltName=DNS:localhost,DNS:assets.lsf.localhost,DNS:foreign.lsf.localhost,DNS:portal.lsf.localhost,DNS:unrelated.lsf.localhost,IP:127.0.0.1',
    '-keyout', path.join(tls, 'key.pem'), '-out', path.join(tls, 'server.pem')], work, 20);
  await chmod(path.join(tls, 'key.pem'), 0o600);
  await writeJson(path.join(work, 'fixtures.json'), fixtures);
  return {prepared: true, testIdentityOnly: true, fixtures};
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
  const [operation, ...args] = process.argv.slice(2);
  if (operation === 'prepare' && args.length === 4) {
    console.log(JSON.stringify(await prepare(...args)));
  } else if (operation === 'sign' && args.length === 5) {
    console.log(JSON.stringify(await sign(...args.slice(0, 4), Number(args[4]))));
  } else {
    throw new Error('usage: native-fixture.mjs prepare CLI PYTHON WOFF2 NEW_WORK | sign CLI WORK NAME LABEL LIFETIME');
  }
  } catch (error) {
    console.log(JSON.stringify({status: 'failed', failure: {name: error.name, message: String(error.message).slice(0, 500)}}));
    process.exitCode = 1;
  }
}
