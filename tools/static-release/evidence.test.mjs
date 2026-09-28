import {test} from 'node:test';
import assert from 'node:assert/strict';
import {generateKeyPairSync, verify} from 'node:crypto';
import {approvalPlan, checkApproval, dsse, referrer, ASSEMBLY} from './evidence.mjs';
import {boundedJson, jsonBytes, sha256} from './files.mjs';

function keys() {
  const value = generateKeyPairSync('ed25519');
  return {...value, approved: {id: 'approved-test-only', publicKey: value.publicKey.export({format: 'der', type: 'spki'}).subarray(12).toString('base64')}};
}
test('independent Ed25519 verifier authenticates exact DSSE bytes and matching referrer', () => {
  const key = keys(), subject = {mediaType: 'application/vnd.oci.image.manifest.v1+json', digest: sha256(Buffer.from('package')), size: 7};
  const raw = dsse(key.privateKey, key.approved, 'application/vnd.latent.package-signature.v1+json',
    {formatVersion: 1, publisherId: key.approved.id, subject, issuedAt: 100, expiresAt: 200}, 2048);
  const envelope = JSON.parse(raw), payload = Buffer.from(envelope.payload, 'base64');
  const pae = Buffer.concat([Buffer.from(`DSSEv1 ${Buffer.byteLength(envelope.payloadType)} ${envelope.payloadType} ${payload.length} `), payload]);
  assert.equal(verify(null, pae, key.publicKey, Buffer.from(envelope.signatures[0].sig, 'base64')), true);
  pae[pae.length - 2] ^= 1;
  assert.equal(verify(null, pae, key.publicKey, Buffer.from(envelope.signatures[0].sig, 'base64')), false);
  const outer = referrer(subject, 'signature', raw);
  assert.equal(outer.layers[0].digest, sha256(raw));
  assert.deepEqual(outer.subject, subject);
  assert.throws(() => dsse(key.privateKey, keys().approved, envelope.payloadType, {}, 2048), /approved-identity/);
});
test('approval pins exact observed assembly and refuses expired or upgraded claims', () => {
  const key = keys(), subject = {digest: sha256(Buffer.from('package'))};
  const observation = {buildType: ASSEMBLY, hermetic: false, reproducibility: 'not-checked',
    dependencyCompleteness: 'declared-inputs-incomplete', source: {repositoryTrust: 'operator-asserted', capture: 'explicit-input-files'}, finishedAt: 100};
  const bytes = jsonBytes(observation);
  const approval = approvalPlan({packageDigest: subject.digest, observationDigest: sha256(bytes),
    publisher: key.approved, builder: keys().approved, issuedAt: 100, expiresAt: 200});
  assert.deepEqual(checkApproval(approval, subject, bytes, 150), observation);
  assert.throws(() => checkApproval(approval, subject, bytes, 200), /validity/);
  assert.throws(() => checkApproval(approval, {digest: sha256(Buffer.from('other'))}, bytes, 150), /association/);
  for (const change of [{hermetic: true}, {reproducibility: 'two-build-byte-equality'}, {buildType: 'compiler'}]) {
    const altered = jsonBytes({...observation, ...change});
    assert.throws(() => checkApproval({...approval, observationDigest: sha256(altered)}, subject, altered, 150), /assembly/);
  }
  assert.throws(() => boundedJson(Buffer.from('{"id":1,"id":2}')), /canonical/);
  assert.throws(() => boundedJson(Buffer.from('{"id":9007199254740992}')), /integer/);
});
