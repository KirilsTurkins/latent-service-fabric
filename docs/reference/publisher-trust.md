# Package publisher signatures and current trust

`latent-signing` signs exact immutable package subjects and verifies publisher
authority against explicit, bounded policy and revocation snapshots. The result
is a point-in-time publisher proof. It does not publish a catalog release,
establish tenant ownership, validate guest semantics, enable routing or authorize
native AOT loading. Those remain separate admission and execution boundaries.

The library supports capsule, browser-assets and SSR package subjects from the
[package format](../protocol/package-format.md). The [packager](../component-development/packaging.md)
checks supplied component semantics separately. Existing locally trusted Phase 1
publication remains unchanged; the operator CLI does not yet expose this signing
workflow. This reference describes the library API.

## Exact subject and signature profile

Construct `PackageSigningSubject::from_package` from the original manifest and
config bytes. It validates their format and association, then hashes the original
manifest bytes. The subject contains the OCI manifest media type, its canonical
SHA-256 package digest and exact size. Config and layer descriptors transitively
bind the component and package metadata. Changing metadata while keeping the same
component produces a different signed package. A legacy `ReleaseDigest` remains
a component identity and cannot substitute for this subject.

The closed LSF v1 profile uses Ed25519 with the
[DSSE 1.0.2 pre-authentication encoding](https://github.com/secure-systems-lab/dsse/blob/v1.0.2/protocol.md).
It does not claim generic DSSE conformance. The envelope has exactly
`payloadType`, `payload`, and a one-element `signatures` array containing exactly
`keyid` and `sig`. Base64 is standard, padded and canonical. The payload type is
`application/vnd.latent.package-signature.v1+json`. There are no certificate,
algorithm-selection or keyless-discovery fields.

Decoded claims contain exactly `formatVersion: 1`, `publisherId`,
`subject: {mediaType, digest, size}`, `issuedAt` and `expiresAt`. Producers use that
field order. Verification authenticates and interprets the same original decoded
claims bytes; it does not verify a reserialized JSON replacement. The PAE lengths
count UTF-8 bytes. The unsigned `keyid` is SHA-256 of the raw public key and serves
only to select an already approved anchor. A claimed publisher or a key hint
cannot introduce authority.

Detached evidence retains the existing artifact type
`application/vnd.latent.signature.v1` and layer media type
`application/vnd.latent.signature.payload.v1+json`. Its config is exactly `{}`.
`SignatureEvidence::from_envelope` checks shape and subject association and
produces the referrer's `evidence/signature.json` layer. Inspection also accepts
other paths permitted by the evidence format. Association alone is untrusted.

## Produce and distribute a signature

Generate a key with `generate_signing_key`, approve its raw 32-byte public key
under a publisher in the operator's policy, and keep the private key outside
guests and package content. `GeneratedSigningKey::into_pkcs8` returns a zeroizing
buffer; the library never writes it to disk. Import it through
`LocalSigner::from_pkcs8(pkcs8, publisher, approved_public_key)`. Import requires
bounded PKCS#8 v2 with its embedded public key and a matching approved identity.
Generated keys and signers redact private material from diagnostics.

Call `LocalSigner::sign_package` with the checked subject, explicit
`SignatureValidity` and `SignatureLimits`. Its output exposes exact manifest,
config and payload bytes for an OCI referrer push. PKCS#8 buffers and signer key
material use the upstream zeroization facilities; callers remain responsible for
their own copies, external persistence and access policy.

The implementation pins `ed25519-dalek` 3.0.0, uses `verify_strict`, rejects weak
and noncanonical public-key encodings, and explicitly requires canonical scalar
encoding even if other dependencies enable upstream compatibility features. It
does not promise that every accepted key is in the prime-order subgroup.

Direct crypto dependencies are pinned: `ed25519-dalek` 3.0.0 for signing/strict
verification, `ed25519` 3.0.0 with PKCS#8 buffer zeroization, `curve25519-dalek`
5.0.0 for the independent canonical-scalar check, `getrandom` 0.4.3 for OS entropy,
and `zeroize` 1.9.0 for owned secret buffers. A dedicated CI check enables the
upstream legacy compatibility feature and verifies that LSF still rejects
noncanonical signatures. Key generation belongs in host provisioning; early OS
entropy initialization can wait even though its memory use is bounded.

Push the package and signature evidence with the [scoped OCI adapter](oci-registry.md).
Resolve mutable tags once, discover referrers for the exact package digest, and
pull evidence by each immutable referrer digest. Discovery descriptors, registry
credentials and a matching outer subject do not authenticate a publisher.

## Approve bounded trust snapshots

`PublisherPolicy::from_json` and `RevocationSnapshot::from_json` parse the closed
camelCase documents described by the [policy](../../schemas/publisher-policy.schema.json)
and [revocation](../../schemas/publisher-revocations.schema.json) schemas. Typed
constructors enforce the same limits. These are operator-approved inputs; the
library does not authenticate the person or service supplying them.

| Policy field | Meaning |
| --- | --- |
| `scope` / `generation` | Explicit policy domain and positive monotonic version. |
| `validFrom` / `validUntil` | Half-open snapshot validity in Unix seconds. |
| `maxSignatureLifetimeSeconds` | Maximum acceptable signed lifetime, at most 31 days. |
| `maxProofAgeSeconds` | Maximum reuse of a positive result, at most one hour. |
| `keys` | Publisher ID, canonical base64 raw public key and half-open key validity. An empty array explicitly denies every publisher. |

Publisher IDs and scopes are nonempty ASCII identifiers of at most 128 bytes,
using letters, digits and `._:/@-`. They do not imply tenant identity. Duplicate
key bindings, conflicting publisher assignments and invalid keys are rejected.
Every key initially authorizes only package-publisher claims.

Canonical policy identity is SHA-256 of the compact encoded policy after sorting
keys by derived fingerprint. JSON member order or input key order cannot change
that identity. Use `policy.digest()` when constructing the revocation snapshot;
do not hash the original unsorted policy JSON as its identity.

A revocation snapshot is mandatory even when both `revokedKeys` and
`revokedPublishers` are empty. It contains its own positive generation and
validity, the same scope, and the exact `policyDigest`. Revoked lists are sorted
for canonical identity; duplicates are rejected. `PublisherTrust::new` requires
that binding. Missing, stale or mismatched snapshots cannot silently become
empty fresh revocations.

## Verify and keep a proof current

Create `PublisherVerifier::new(trust, limits, now)` with trusted host time. It
checks snapshot freshness and the verifier owner's limits, including when a
snapshot was previously constructed under more permissive limits. Call
`verify_package` with the expected checked package subject, exact evidence bytes
and current host time. The verifier checks outer/config/layer hashes and sizes,
all subject associations, the approved key and signed publisher, strict
cryptography, revocation, issuance/key validity and signed lifetime.

`VerifiedPackageSignature` has private construction and no deserializer. It
binds the exact package subject, referrer and payload digests, actual publisher
and key fingerprint, both snapshot identities and generations, verification time
and expiry. Its expiry is the earliest of signature, key, policy, revocation and
configured proof-age bounds. All intervals are half-open; equality with an expiry
is expired. No network fetch or verification cache can renew those bounds.

Use `check_current(proof, now)` before reusing a result. It fails if snapshots
changed, the proof expired, time regressed, or time precedes the proof's original
verification time even in another verifier with identical snapshot identities.
The verifier records the greatest observed time on failed operations as well as
successful ones. Offline verification is allowed only while the explicitly
approved snapshots remain valid; unavailable refresh does not extend them.

Updates use `replace_trust(&expected_state_id, next_trust, now)`. An update is
atomic, requires the expected current state and unchanged scope, and rejects
generation rollback or changed contents at the same generation. Rotating policy
also requires a higher revocation generation because its `policyDigest` changes.
An identical update is idempotent only after freshness and time checks; it cannot
renew validity. Every changed state invalidates prior proofs. Contended ownership
returns a bounded resource error rather than adding an internal wait queue.

The verifier rechecks captured trust and clock state after cryptographic work.
A consumer must still match the proof to its exact package/evidence and compare
the trust state atomically at its final admission or publication commit. Durable
generation and clock floors across restarts belong to the forthcoming admission
owner. Persisting proof fields does not turn them back into authoritative values.

Errors expose fixed reasons without key material, claims or remote responses.
An unknown anchor is `UnapprovedKey`; a signed publisher inconsistent with the
approved key binding is `UntrustedPublisher`. Inspection returns
`UnverifiedSignature`, which cannot be used as a proof.

## Resource limits and validation

| Budget | Default / hard ceiling |
| --- | --- |
| Envelope and referrer, independently | 4096 / 4096 bytes |
| Decoded claims | 2048 / 2048 bytes |
| Policy / revocation JSON, independently | 65,536 / 65,536 bytes |
| Approved keys | 64 / 256 |
| Revoked keys | 256 / 256 |
| Revoked publishers | 64 / 256 |

Configured values must be positive and cannot exceed hard ceilings. Closed JSON
parsing also rejects duplicate keys and bounds nesting and aggregate structure.
Schema checks describe shape; raw byte limits, canonical integer token spelling,
cross-field validity, cryptography and policy currentness require the Rust API.
No task, queue, automatic key discovery or network dependency is created by the
verifier. Caller-held evidence and proof collections need their own retention
budget.

Run `cargo test -p latent-signing --locked` and
`python -m unittest tools.tests.test_publisher_trust_schemas` in the configured
environment. Public tests include an independently produced
[OpenSSL signature vector](../../crates/latent-signing/tests/fixtures/README.md),
same-component/different-package subjects, revoked/unknown publishers, expiry,
clock rollback, owner limits and conflicting concurrent updates. RFC 8032 vectors
and adversarial format/key tests cover the lower-level implementation.
The existing [disposable Zot test](oci-registry.md#run-the-real-registry-check)
adds sign/attach/discover/pull/verify in its single bounded container.

[Builder provenance](build-provenance.md) now provides a distinct signed payload
and explicit builder keys for the maintained echo recipe. SBOM authentication,
admission and trusted AOT output remain separate Phase 2 work; compiler proofs
will require their own key roles. A package-publisher signature does not
authenticate later detached provenance/SBOM merely because their subjects match,
and it never authorizes native compiler output.
