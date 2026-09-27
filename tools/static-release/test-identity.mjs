// Disposable qualification identities only. Never imported by operational tools.
import {generateKeyPairSync} from 'node:crypto';
import path from 'node:path';
import {sha256, writeBytes, writeJson} from './files.mjs';
import {ASSEMBLY} from './evidence.mjs';

export async function identity(directory, repository) {
  const now = Math.floor(Date.now() / 1000), from = now - 60, until = now + 7200;
  const roles = {};
  for (const role of ['publisher', 'builder']) {
    const key = generateKeyPairSync('ed25519');
    const bytes = key.privateKey.export({format: 'der', type: 'pkcs8'});
    try { await writeBytes(path.join(directory, role + '.der'), bytes); }
    finally { bytes.fill(0); }
    roles[role] = {id: 'frontend-qualification-' + role,
      publicKey: key.publicKey.export({format: 'der', type: 'spki'}).subarray(12).toString('base64')};
  }
  // Struct field order is part of the published canonical policy identity.
  // One key/requirement avoids any ambiguity in fingerprint/list sorting.
  const base = {formatVersion: 1, scope: 'frontend-qualification', generation: 1, validFrom: from, validUntil: until,
    maxSignatureLifetimeSeconds: 3600, maxProofAgeSeconds: 900};
  const publisher = {...base, keys: [{publisherId: roles.publisher.id, publicKey: roles.publisher.publicKey,
    validFrom: from, validUntil: until}]};
  const builder = {...base, keys: [{builderId: roles.builder.id, publicKey: roles.builder.publicKey,
    validFrom: from, validUntil: until}], requirements: [{builderId: roles.builder.id, buildType: ASSEMBLY,
    sourceRepository: repository, requireReproducible: false}]};
  const revoke = policy => ({formatVersion: 1, scope: base.scope, policyDigest: sha256(Buffer.from(JSON.stringify(policy))),
    generation: 1, validFrom: from, validUntil: until, revokedKeys: []});
  const policy = {formatVersion: 1, generation: 1, scope: base.scope, validFrom: from, validUntil: until,
    tenants: [{tenant: 'tests', publishers: [roles.publisher.id]}], publisher,
    publisherRevocations: {...revoke(publisher), revokedPublishers: []}, builder,
    builderRevocations: {...revoke(builder), revokedBuilders: []},
    sbom: {formatVersion: 1, embedded: 'required', detached: 'optional', requireSource: [], requireLicense: []}};
  await writeJson(path.join(directory, 'policy.json'), policy);
  return {roles, policy};
}
