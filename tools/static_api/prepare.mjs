// Disposable keys and real build observations. This is a qualification harness,
// never an organization signing service or an application build substitute.
import assert from 'node:assert/strict';
import {createPrivateKey} from 'node:crypto';
import {cp, mkdir, readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {identity} from '../static-release/test-identity.mjs';
import {dsse, referrer} from '../static-release/evidence.mjs';
import {sha256, jsonBytes, writeBytes, writeJson} from '../static-release/files.mjs';
import {main} from '../static-release/release.mjs';
import {native, run} from '../static-release/process.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const repository = 'https://example.com/anonymous/frontend';

export async function prepare(cli, signer, build, work) {
  assert.equal(process.platform, 'linux'); assert.notEqual(process.getuid(), 0);
  await mkdir(work, {mode: 0o700});
  // The released signer validates the completed SDK build and supplies its
  // embedded SBOM. No build observation is invented by this harness.
  await run(signer, ['demo-sign', path.join(work, 'demo'), build], work, 60);
  await cp(path.join(work, 'demo/status-api'), path.join(work, 'api'), {recursive: true});
  const observation = JSON.parse(await readFile(path.join(build, 'build-observation.json')));
  const {roles, policy} = await identity(work, repository);
  policy.tenants = [{tenant: 'examples', publishers: [roles.publisher.id]}];
  policy.builder.requirements.push({builderId: roles.builder.id, buildType: observation.buildType,
    sourceRepository: observation.source.repository, sourceRevision: observation.source.revision,
    sourceSnapshotDigest: observation.source.snapshotDigest, requireReproducible: false});
  // Same builder, distinct build types: Rust's canonical requirement order.
  policy.builder.requirements.sort((a, b) => a.buildType < b.buildType ? -1 : a.buildType > b.buildType ? 1 : 0);
  policy.builderRevocations.policyDigest = sha256(Buffer.from(JSON.stringify(policy.builder)));
  await writeFile(path.join(work, 'policy.json'), jsonBytes(policy), {mode: 0o600});
  const manifest = await readFile(path.join(work, 'api/package/manifest.json'));
  const subject = {mediaType: 'application/vnd.oci.image.manifest.v1+json', digest: sha256(manifest), size: manifest.length};
  const issuedAt = Math.floor(Date.now() / 1000), validity = {issuedAt, expiresAt: issuedAt + 1800};
  const key = async name => createPrivateKey({key: await readFile(path.join(work, name + '.der')), format: 'der', type: 'pkcs8'});
  const payloads = {
    signature: dsse(await key('publisher'), roles.publisher, 'application/vnd.latent.package-signature.v1+json',
      {formatVersion: 1, publisherId: roles.publisher.id, subject, ...validity}, 2048),
    provenance: dsse(await key('builder'), roles.builder, 'application/vnd.in-toto+json', {
      _type: 'https://in-toto.io/Statement/v1', subject: [{name: 'lsf-package', digest: {sha256: subject.digest.slice(7)}}],
      predicateType: 'https://latent.dev/provenance/v1', predicate: {formatVersion: 1, packageSubject: subject,
        builderId: roles.builder.id, ...validity, observation}}, 32768),
  };
  const evidence = path.join(work, 'api-evidence'); await mkdir(evidence, {mode: 0o700});
  const index = {formatVersion: 1, packageDigest: subject.digest, signatures: [], provenance: [], sboms: []};
  for (const [kind, payload] of Object.entries(payloads)) {
    const files = {manifest: kind + '-manifest.json', configuration: kind + '-config.json', payload: kind + '-payload.json'};
    await writeJson(path.join(evidence, files.manifest), referrer(subject, kind, payload));
    await writeBytes(path.join(evidence, files.configuration), Buffer.from('{}'));
    await writeBytes(path.join(evidence, files.payload), payload);
    index[kind === 'signature' ? 'signatures' : 'provenance'].push(files);
  }
  await writeJson(path.join(evidence, 'index.json'), index);
  await native(cli, ['--tenant', 'examples', 'package', 'verify', path.join(work, 'api/package'),
    '--evidence-index', path.join(evidence, 'index.json'), '--evidence-root', evidence, '--policy', path.join(work, 'policy.json')], work);

  const site = path.join(work, 'site-build'); await mkdir(site, {mode: 0o700});
  const names = ['index.html', 'style.css', 'status.js'], inventory = [];
  for (const name of names) {
    const bytes = await readFile(path.join(root, 'examples/static-api/site', name));
    await writeBytes(path.join(site, name), bytes); inventory.push({path: name, digest: sha256(bytes), size: bytes.length});
  }
  const observations = [];
  for (const [kind, value] of [['source', inventory], ['toolchain', {node: process.version}],
    ['build', {mode: 'maintained-supplied-files', frameworkBuildExecuted: false}]]) {
    const bytes = jsonBytes(value); await writeBytes(path.join(site, kind + '.json'), bytes);
    observations.push({kind, source: kind + '.json', digest: sha256(bytes)});
  }
  const input = path.join(work, 'site-inventory.json'), prepared = path.join(work, 'site');
  await writeJson(input, {formatVersion: 1, profile: 'static-site-input-v1', name: 'status-site', version: '1.0.0',
    assets: names.map(name => ({path: '/' + name, source: name})), entryDocument: '/index.html',
    directoryIndex: {mode: 'disabled', document: '/index.html'}, fallback: {mode: 'spa', document: '/index.html'},
    excluded: [], observations});
  await main(['prepare', '--cli', cli, '--python', '/usr/bin/python3', '--build-output', site,
    '--inventory', input, '--repository', repository, '--output', prepared]);
  await writeJson(path.join(work, 'identities.json'), roles);
  await main(['request-signing', '--prepared', prepared, '--identities', path.join(work, 'identities.json'),
    '--lifetime-seconds', '1800', '--output', path.join(work, 'site-approval.json')]);
  await main(['sign', '--cli', cli, '--prepared', prepared, '--approval', path.join(work, 'site-approval.json'),
    '--publisher-key', path.join(work, 'publisher.der'), '--builder-key', path.join(work, 'builder.der'),
    '--output', path.join(work, 'site-evidence'), '--policy', path.join(work, 'policy.json'), '--tenant', 'examples']);
  return {prepared: true, testKeysOnly: true, capsuleSourceObservation: sha256(jsonBytes(observation))};
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  console.log(JSON.stringify(await prepare(...process.argv.slice(2))));
}
