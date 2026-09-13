# ADR-0022: Bind publisher proofs to current explicit trust

- Status: Accepted
- Date: 2026-09-12
- Related: [ADR-0019](0019-separate-package-identity-from-component-identity.md), [ADR-0021](0021-bound-registry-authority-and-transfer-ownership.md), [#143](https://github.com/KirilsTurkins/latent-service-fabric/issues/143)

## Context

Immutable package distribution now preserves exact bytes, but registry authority
and matching referrer subjects do not authenticate publishers. A successful
signature check is also insufficient after policy rotation, key revocation or
expiry. Existing Phase 1 component identities and locally trusted publication
must retain their meaning while a bounded supply-chain boundary is introduced.

## Decision

Sign exact `PackageSubject` identities checked from original manifest/config
bytes. Use a closed LSF v1 envelope with one Ed25519 signature and the DSSE
pre-authentication encoding. Interpret the same exact decoded claims bytes that
were cryptographically verified. Keep the existing detached signature media
types. A key hint chooses among approved anchors; it cannot create authority.

Use pinned established Ed25519 implementations, strict verification and explicit
canonical encoding checks. Reject weak public anchors. Use bounded PKCS#8 v2
imports with embedded and independently approved public-key matching, OS entropy
for generation and upstream zeroizing private-key containers. Expose no network
discovery, certificates, keyless signing or automatic private-key persistence.

Require explicit immutable operator-approved policy and revocation snapshots.
Policy maps raw public keys to package publishers; an empty key list denies all.
Revocations bind the exact canonical policy identity and scope, including when
their lists are empty. Both snapshots have bounded arrays, bytes, generations and
half-open validity. Canonical content identity sorts unordered input key/list
entries and rejects duplicates; it does not use original JSON formatting.

Only the verifier constructs a publisher proof. Bind the proof to package,
evidence, publisher, key and both snapshot identities/generations. Bound expiry
by every contributing validity interval and the configured maximum proof age.
Keep inspection and transport association explicitly untrusted.

Use atomic expected-state replacement with monotonic generations. A changed
policy requires a freshly bound higher-generation revocation snapshot. Reject
changed contents at the same generation; identical fresh state is idempotent and
does not renew expiry. Advance the trusted clock high-water mark even on failed
operations. Recheck captured state and clock after cryptographic work, and reject
reuse before a proof's verification time or after its expiry. Fail bounded owner
contention instead of adding a queue. Do not create a verification cache.

## Consequences

Offline verification works only while explicit snapshots remain valid. Failed
refreshes cannot extend trust. A durable admission owner must persist generation
and clock floors and atomically compare the captured trust state at final
publication. A library proof is neither catalog admission nor tenant authority,
route eligibility, semantic guest validation or native-load permission.

Future provenance and trusted AOT require distinct signed payloads and explicit
builder/compiler key roles. Publisher keys cannot authorize those roles through
subject matching. SBOM presence, inventory and authenticity remain separate
policy decisions. CLI integration is delivered by its dedicated feature ticket.

Validate through independent RFC 8032 and OpenSSL public vectors, adversarial
bounded format/trust tests and the existing single disposable authenticated Zot
registry. Retain only tiny public fixtures, never private fixture keys or load
reports. The [publisher trust reference](../docs/reference/publisher-trust.md)
specifies exact formats, limits, supported workflows and remaining boundaries.
