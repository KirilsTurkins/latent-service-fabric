# Supply-chain admission evidence boundary

Phase 2 catalog admission must decide from authenticated evidence, not from
caller-supplied descriptor annotations or booleans. The first #146 delivery
adds `latent-signing::verify_current_supply_chain_evidence` as the bounded
publisher/provenance input for that decision.

## What the current helper proves

The helper accepts only `VerifiedPackageSignature` and
`VerifiedBuildProvenance` values produced by the cryptographic verifier APIs. It
rechecks both proofs against their current publisher/builder trust owners, then
requires them to name the same exact OCI package subject and the provenance to
name the package's exact component digest.

The returned `VerifiedSupplyChainEvidence` retains only bounded identities:
package/component, publisher/builder and key fingerprints, signature/provenance
evidence and payload digests, both trust-state identities, and the intersection
of the proof validity windows. It is not serializable into authority and cannot
be reconstructed from persisted display fields. Verification performs no
network access and adds no worker, queue or cache.

Trust is rechecked before and after binding. A trust replacement observed while
binding fails closed. The catalog owner still has to compare the receipt's
publisher and builder trust states at its own atomic publication point; this
helper deliberately does not pretend that two independently locked trust owners
can make a later catalog commit atomic.

## Not yet catalog admission

This slice does **not** make a package routable or preparation-eligible. #146
still needs a higher-level admission owner that, at one durable commit boundary:

- binds the authenticated tenant and configured admission-policy identity;
- combines the current signature/provenance evidence with the exact SBOM policy
  evaluation from `latent-packaging`;
- persists the package, component, evidence, trust and policy identities with an
  admitted/rejected disposition rather than trusting caller metadata;
- defines positive-result reuse and invalidation for policy changes, expiry,
  revocation and offline trust-source unavailability;
- preserves an explicitly distinguishable trusted-local migration path without
  bypassing an enforced signed-admission configuration; and
- rejects before Wasmtime preparation on every failed or stale required proof.

The Phase 1 `DirectoryArtifactRepository` remains the locally trusted catalog
until that integration is delivered. This document therefore describes an
admission **input**, not a compatibility promise that remote packages are
already accepted by `latentd`.

## Resource and security properties

The evidence object owns no guest `Store`, cell, process, connection or
service-specific task. All currentness checks are synchronous and bounded by the
existing verifier limits. Persisted fields must never be deserialized back into
`VerifiedSupplyChainEvidence`; adoption after restart requires fresh
cryptographic/trust verification under the configured policy.

SBOM presence/attribution is deliberately not inferred from a signature or
provenance proof. `latent-packaging::SbomPolicyEvaluation` remains the content
policy result that the future catalog admission commit must bind separately.
