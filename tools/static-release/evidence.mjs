import {createPrivateKey, createPublicKey, sign} from 'node:crypto';
import path from 'node:path';
import {requireValue} from './model.mjs';
import {boundedJson, closed, jsonBytes, privateDirectory, readBytes, sha256, writeJson, writeBytes} from './files.mjs';
import {native} from './process.mjs';

const OCI = 'application/vnd.oci.image.manifest.v1+json';
export const ASSEMBLY = 'https://latent.dev/build/web-package-assembly/v1';
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9._:/@-]{1,128}$/.test(value);
const identity = value => typeof value === 'string' && /^sha256:[a-f0-9]{64}$/.test(value);

export function approvalPlan({packageDigest, observationDigest, publisher, builder, issuedAt, expiresAt}) {
  return {schemaVersion: 'latent.static.signing-approval.v1', packageDigest, observationDigest,
    publisher, builder, issuedAt, expiresAt};
}
export function checkApproval(approval, subject, observationBytes, now = Math.floor(Date.now() / 1000)) {
  closed(approval, ['schemaVersion', 'packageDigest', 'observationDigest', 'publisher', 'builder', 'issuedAt', 'expiresAt']);
  requireValue(approval.schemaVersion === 'latent.static.signing-approval.v1'
    && identity(approval.packageDigest) && approval.packageDigest === subject.digest
    && identity(approval.observationDigest) && approval.observationDigest === sha256(observationBytes), 'signing-approval-association');
  for (const role of ['publisher', 'builder']) {
    closed(approval[role], ['id', 'publicKey']);
    const {id, publicKey} = approval[role];
    requireValue(identifier(id) && typeof publicKey === 'string' && /^[A-Za-z0-9+/]{43}=$/.test(publicKey)
      && Buffer.from(publicKey, 'base64').toString('base64') === publicKey, 'approved-signing-identity-required');
  }
  requireValue(Number.isSafeInteger(approval.issuedAt) && Number.isSafeInteger(approval.expiresAt)
    && approval.issuedAt > 0 && approval.issuedAt <= now && approval.expiresAt > now
    && approval.expiresAt - approval.issuedAt <= 2678400, 'signing-validity-bound');
  const observation = boundedJson(observationBytes, 32768);
  requireValue(observation.buildType === ASSEMBLY && observation.hermetic === false
    && observation.reproducibility === 'not-checked' && observation.dependencyCompleteness === 'declared-inputs-incomplete'
    && observation.source?.repositoryTrust === 'operator-asserted' && observation.source?.capture === 'explicit-input-files'
    && observation.finishedAt <= approval.issuedAt, 'supplied-file-assembly-observation-required');
  return observation;
}
export async function requestApproval({directory, identitiesFile, lifetimeSeconds, output}) {
  await privateDirectory(directory);
  const receipt = boundedJson(await readBytes(path.join(directory, 'PREPARE-COMPLETE.json'), 16384), 16384);
  const identities = boundedJson(await readBytes(identitiesFile, 16384), 16384);
  closed(identities, ['publisher', 'builder']);
  requireValue(Number.isInteger(lifetimeSeconds) && lifetimeSeconds > 0 && lifetimeSeconds <= 2678400, 'signing-validity-bound');
  const bytes = await readBytes(path.join(directory, 'observation.json'), 32768);
  const manifest = await readBytes(path.join(directory, 'package/manifest.json'), 262144);
  requireValue(receipt.schemaVersion === 'latent.static.prepared.v1' && receipt.packageDigest === sha256(manifest)
    && receipt.observationDigest === sha256(bytes), 'prepared-request-association');
  const issuedAt = Math.floor(Date.now() / 1000);
  const request = approvalPlan({...receipt, ...identities, issuedAt, expiresAt: issuedAt + lifetimeSeconds});
  checkApproval(request, {digest: receipt.packageDigest}, bytes, issuedAt);
  await privateDirectory(path.dirname(output));
  await writeJson(output, request);
  return {schemaVersion: 'latent.static.signing-request.v1', packageDigest: receipt.packageDigest,
    observationDigest: receipt.observationDigest, approved: false, requestDigest: sha256(jsonBytes(request))};
}
export function dsse(privateKey, approved, payloadType, value, maximum) {
  const publicKey = createPublicKey(privateKey);
  requireValue(privateKey.asymmetricKeyType === 'ed25519' && publicKey.asymmetricKeyType === 'ed25519', 'ed25519-key-required');
  const spki = publicKey.export({type: 'spki', format: 'der'});
  requireValue(spki.length === 44 && spki.subarray(0, 12).equals(Buffer.from('302a300506032b6570032100', 'hex')),
    'ed25519-public-key-shape');
  const raw = spki.subarray(12);
  requireValue(raw.toString('base64') === approved.publicKey, 'private-key-does-not-match-approved-identity');
  const payload = Buffer.from(JSON.stringify(value));
  requireValue(payload.length <= maximum, 'signed-payload-bound');
  const type = Buffer.from(payloadType);
  const pae = Buffer.concat([Buffer.from(`DSSEv1 ${type.length} `), type, Buffer.from(` ${payload.length} `), payload]);
  return Buffer.from(JSON.stringify({payloadType, payload: payload.toString('base64'), signatures: [{
    keyid: sha256(raw), sig: sign(null, pae, privateKey).toString('base64')}]}));
}
export function referrer(subject, kind, payload) {
  requireValue(['signature', 'provenance'].includes(kind) && payload.length <= (kind === 'signature' ? 4096 : 49152), 'evidence-payload-bound');
  return {schemaVersion: 2, mediaType: OCI, artifactType: `application/vnd.latent.${kind}.v1`,
    config: {mediaType: 'application/vnd.oci.empty.v1+json', digest: sha256(Buffer.from('{}')), size: 2},
    layers: [{mediaType: `application/vnd.latent.${kind}.payload.v1+json`, digest: sha256(payload), size: payload.length,
      annotations: {'org.opencontainers.image.title': `evidence/${kind}.json`, 'dev.latent.layer.role': 'evidence'}}],
    subject, annotations: {}};
}
async function key(name) {
  const bytes = await readBytes(name, 4096, true);
  try { return createPrivateKey({key: bytes, type: 'pkcs8', format: 'der'}); }
  finally { bytes.fill(0); }
}
export async function signEvidence(options) {
  const {cli, directory, approvalFile, publisherKey, builderKey, output, policy, tenant} = options;
  await privateDirectory(directory);
  const inspected = await native(cli, ['package', 'inspect', path.join(directory, 'package')], directory);
  requireValue(inspected.kind === 'browser-assets' && inspected.componentDigest === null && inspected.sbomInventoryDigest,
    'componentless-sbom-package-required');
  const manifest = await readBytes(path.join(directory, 'package/manifest.json'), 262144);
  const subject = {mediaType: OCI, digest: sha256(manifest), size: manifest.length};
  requireValue(inspected.packageDigest === subject.digest, 'inspected-package-changed');
  const observationBytes = await readBytes(path.join(directory, 'observation.json'), 32768);
  const approval = boundedJson(await readBytes(approvalFile, 16384, true), 16384);
  const observation = checkApproval(approval, subject, observationBytes);
  requireValue(observation.outputsDigest === inspected.webBuildOutputs.digest
    && observation.outputsCount === inspected.webBuildOutputs.count
    && String(observation.outputsBytes) === inspected.webBuildOutputs.bytes, 'observed-package-output-mismatch');
  // Signing runs after all build children finish. Each exact role and byte set
  // has external approval; this helper never creates organization trust policy.
  const publisher = await key(publisherKey), builder = await key(builderKey);
  const validity = {issuedAt: approval.issuedAt, expiresAt: approval.expiresAt};
  const signature = dsse(publisher, approval.publisher, 'application/vnd.latent.package-signature.v1+json',
    {formatVersion: 1, publisherId: approval.publisher.id, subject, ...validity}, 2048);
  const provenance = dsse(builder, approval.builder, 'application/vnd.in-toto+json', {
    _type: 'https://in-toto.io/Statement/v1', subject: [{name: 'lsf-package', digest: {sha256: subject.digest.slice(7)}}],
    predicateType: 'https://latent.dev/web-provenance/v1', predicate: {formatVersion: 1, packageSubject: subject,
      builderId: approval.builder.id, ...validity, observation}}, 32768);
  const destination = await privateDirectory(output, true);
  const index = {formatVersion: 1, packageDigest: subject.digest, signatures: [], provenance: [], sboms: []};
  for (const [kind, payload, field] of [['signature', signature, 'signatures'], ['provenance', provenance, 'provenance']]) {
    const files = {manifest: `${kind}-manifest.json`, configuration: `${kind}-config.json`, payload: `${kind}-payload.json`};
    await writeJson(path.join(destination, files.manifest), referrer(subject, kind, payload));
    await writeBytes(path.join(destination, files.configuration), Buffer.from('{}'));
    await writeBytes(path.join(destination, files.payload), payload);
    index[field].push(files);
  }
  await writeJson(path.join(destination, 'index.json'), index);
  const verified = await native(cli, ['--tenant', tenant, 'package', 'verify', path.join(directory, 'package'),
    '--evidence-index', path.join(destination, 'index.json'), '--evidence-root', destination, '--policy', policy], directory);
  const receipt = {schemaVersion: 'latent.static.signed.v1', packageDigest: subject.digest,
    observationDigest: sha256(observationBytes), approvalDigest: sha256(jsonBytes(approval)),
    evidenceIndexDigest: sha256(jsonBytes(index)), verification: verified, ...validity};
  await writeJson(path.join(destination, 'SIGNING-COMPLETE.json'), receipt);
  return receipt;
}
