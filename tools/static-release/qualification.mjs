// Actual released binaries, newly generated test keys and immutable frontend
// outputs in a clean Ubuntu frontend container. No Rust toolchain or fixture.
import assert from 'node:assert/strict';
import {mkdir, mkdtemp, realpath, readFile, access} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {fileURLToPath} from 'node:url';
import {identity} from './test-identity.mjs';
import {approvalPlan} from './evidence.mjs';
import {sha256, jsonBytes, writeBytes, writeJson} from './files.mjs';
import {main} from './release.mjs';
import {native, run} from './process.mjs';

const repository = 'https://example.com/anonymous/frontend';
export async function qualify(cli, destination, node, releasedCli = true) {
  assert.equal(process.platform, 'linux');
  assert.notEqual(process.getuid(), 0);
  assert.equal(typeof releasedCli, 'boolean');
  for (const directory of releasedCli ? ['/usr/bin', '/usr/local/bin', '/home/frontend/.cargo/bin'] : []) {
    for (const name of ['cargo', 'rustc']) await assert.rejects(access(path.join(directory, name)));
  }
  const work = await mkdtemp(path.join(os.tmpdir(), 'lsf-frontend-'));
  const {roles, policy} = await identity(work, repository);
  const identitiesFile = path.join(work, 'identities.json');
  await writeJson(identitiesFile, {publisher: roles.publisher, builder: roles.builder});
  const rows = [];
  for (const name of ['site', 'documentation']) {
    const build = path.join(work, name + '-build'); await mkdir(build, {mode: 0o700});
    const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../examples/static-release', name);
    const names = name === 'site' ? ['index.html', 'app.js', 'site.css'] : ['index.html', 'guide/index.html', 'site.css'];
    const inventory = [];
    for (const item of names) {
      const bytes = await readFile(path.join(root, item));
      await mkdir(path.dirname(path.join(build, item)), {recursive: true, mode: 0o700});
      await writeBytes(path.join(build, item), bytes);
      inventory.push({path: item, digest: sha256(bytes), size: bytes.length});
    }
    const observations = [];
    for (const [kind, value] of [['source', inventory], ['toolchain', {node: process.version}],
      ['build', {mode: 'supplied-maintained-files', frameworkBuildExecuted: false}]]) {
      const bytes = jsonBytes(value); await writeBytes(path.join(build, kind + '.json'), bytes);
      observations.push({kind, source: kind + '.json', digest: sha256(bytes)});
    }
    const input = path.join(work, name + '-inventory.json');
    await writeJson(input, {formatVersion: 1, profile: 'static-site-input-v1', name: 'frontend-' + name, version: '1.0.0',
      assets: names.map(item => ({path: '/' + item, source: item})), entryDocument: '/index.html',
      directoryIndex: {mode: name === 'site' ? 'disabled' : 'redirect', document: '/index.html'},
      fallback: name === 'site' ? {mode: 'spa', document: '/index.html'} : {mode: 'none'}, excluded: [], observations});
    const prepared = path.join(work, name), evidence = path.join(work, name + '-evidence');
    const receipt = await main(['prepare', '--cli', cli, '--python', await realpath('/usr/bin/python3'),
      '--build-output', build, '--inventory', input, '--repository', repository, '--output', prepared]);
    const budget = receipt.captureBudget;
    assert.equal(budget.schemaVersion, 'latent.static-site.budget.v1');
    assert.equal(budget.complete, true);
    assert.equal(budget.captureLimits.publicAssetCount.actual, names.length);
    assert.equal(budget.captureLimits.publicAssetCount.remaining, 252 - names.length);
    assert.equal(budget.captureLimits.logicalPublicBytes.actual, inventory.reduce((sum, row) => sum + row.size, 0));
    const webBytes = await readFile(path.join(prepared, 'inputs/metadata/web-application.json'));
    assert.equal(budget.captureLimits.webManifestBytes.actual, webBytes.length);
    assert.equal(budget.captureLimits.webManifestBytes.remaining, 262144 - webBytes.length);
    const captureBytes = await readFile(path.join(prepared, 'inputs/metadata/static-observation.json'));
    assert.equal(Object.hasOwn(JSON.parse(captureBytes), 'budget'), false);
    const assembly = JSON.parse(await readFile(path.join(prepared, 'observation.json')));
    assert.equal(assembly.materials.find(row => row.name === 'static-capture-observation').digest, sha256(captureBytes));
    assert.equal(assembly.materials.some(row => row.name === 'capture-budget'), false);
    assert.deepEqual(JSON.parse(await readFile(path.join(prepared, 'capture-budget.json'))), budget);
    assert.equal(budget.storageObservation.catalogCapacityObserved, false);
    assert.equal(Object.values(budget.qualification).some(Boolean), false);
    const now = Math.floor(Date.now() / 1000), approval = path.join(work, name + '-approval.json');
    const requested = await main(['request-signing', '--prepared', prepared, '--identities', identitiesFile,
      '--lifetime-seconds', '1800', '--output', approval]);
    assert.equal(requested.approved, false);
    assert.equal(requested.packageDigest, receipt.packageDigest);
    // Only this disposable test harness acts as the approving authority. The
    // operational command requires an external organization's approval.
    const signed = await main(['sign', '--cli', cli, '--prepared', prepared, '--approval', approval,
      '--publisher-key', path.join(work, 'publisher.der'), '--builder-key', path.join(work, 'builder.der'),
      '--output', evidence, '--policy', path.join(work, 'policy.json'), '--tenant', 'tests']);
    assert.equal(signed.packageDigest, receipt.packageDigest);
    await writeJson(path.join(work, name + '-renewal-approval.json'), approvalPlan({packageDigest: receipt.packageDigest,
      observationDigest: receipt.observationDigest, publisher: roles.publisher, builder: roles.builder,
      issuedAt: now, expiresAt: now + 3600}));
    await main(['sign', '--cli', cli, '--prepared', prepared, '--approval', path.join(work, name + '-renewal-approval.json'),
      '--publisher-key', path.join(work, 'publisher.der'), '--builder-key', path.join(work, 'builder.der'),
      '--output', path.join(work, name + '-renewal'), '--policy', path.join(work, 'policy.json'), '--tenant', 'tests']);
    // Current revoked authority cannot pass even though signature bytes match.
    const denied = structuredClone(policy); denied.publisherRevocations.generation = 2;
    denied.publisherRevocations.revokedPublishers = [roles.publisher.id];
    const deniedFile = path.join(work, name + '-revoked-policy.json'); await writeJson(deniedFile, denied);
    await assert.rejects(native(cli, ['--tenant', 'tests', 'package', 'verify', path.join(prepared, 'package'),
      '--evidence-index', path.join(evidence, 'index.json'), '--evidence-root', evidence, '--policy', deniedFile], work));
    rows.push({example: name, packageDigest: signed.packageDigest, verifiedByReleasedCli: releasedCli,
      revokedPublisherRejected: true, assemblyExecuted: true, frameworkBuildExecuted: false,
      captureBudgetVersion: budget.schemaVersion, exactEncodedManifestHeadroom: true,
      diagnosticsExcludedFromSignedCapture: true});
  }
  const live = node ? JSON.parse((await run(await realpath('/usr/bin/python3'),
    [path.join(path.dirname(fileURLToPath(import.meta.url)), 'qualification_native.py'), '--work', work,
      '--cli', cli, '--node', node], work, 120)).toString('utf8')) : null;
  if (node) assert.equal(live?.passed, true, JSON.stringify(live));
  const receipt = {schemaVersion: 'latent.frontend.release-qualification.v1', passed: true, actualReleasedCli: releasedCli,
    rustToolchainAvailable: releasedCli ? false : null, uid: process.getuid(), node: process.version, examples: rows,
    nativeWorkflow: live, testIdentityOnly: true, cloudQualified: false};
  if (destination) await writeJson(destination, receipt);
  return receipt;
}
if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  console.log(JSON.stringify(await qualify(process.argv[2], process.argv[3], process.argv[4])));
}
