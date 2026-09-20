# Build observations and current builder trust

Phase 2 provides a maintained echo build observer and separate builder-provenance
verification in `latent-signing`. The observer executes selected committed source
and records its component output. A trusted builder signs that observation after
binding it to an independently inspected package. `BuilderVerifier` checks exact
evidence against explicit current builder policy and revocations. This grants no
catalog, tenant, publisher, guest-execution or native AOT authority.

## Observe an actual build

From the configured Python 3.13 environment and pinned toolchain:

```sh
python tools/build_provenance.py --repository https://github.com/KirilsTurkins/latent-service-fabric --output-dir target/capsules/echo-provenance
cargo run -p latent-packaging --example package --locked -- build-with-sbom target/capsules/echo-provenance/package-source.json target/capsules/echo-provenance/sbom-inputs.json target/capsules/echo-provenance target/package-echo-provenance
cargo run -p latent-packaging --example package --locked -- inspect target/package-echo-provenance
```

Output directories must be fresh children of the configured target root.
`--revision` selects an exact 40- or 64-character lowercase Git commit identity;
the default resolves committed `HEAD`. Worktree edits are excluded.
`--verify-reproducible` performs two actual builds and records byte equality only
when their components match; otherwise the default claim is `not-checked`.
This builds a small component and does not run a load campaign.

`--legacy-output-dir` optionally exports the complete unsigned echo fixture from
the same build for existing containment/conformance tools. It must name a distinct
fresh child of the target root. The default export retains only the observation
and exact package-ready inputs, including normalized `sbom-inputs.json`. Neither
export authenticates legacy `build.json`.

`tools/validate_contracts.sh` regenerates its two fixed echo output directories.
Its reset helper checks the expected file inventory, fixture markers and component
hash before removal, and refuses unknown files, links or changed associations.
The standalone observer never replaces an existing output directory.

The observer captures a bounded committed-source allowlist with `git archive`,
checks workspace membership and rejects unsafe paths, links and nonregular files.
It builds in a temporary owned directory. A sorted compact inventory identifies
each selected file's portable path, SHA-256, size and regular-file mode. The source
snapshot digest hashes this inventory, not tar metadata or physical paths.
Inputs, recipe files and selected tool binaries are checked again after the
build. Intermediates are removed before publishing successful small outputs;
failed observations are not published.

Required unique material names are `source-snapshot`, `dependency-lock`,
`build-recipe`, `toolchain-config`, `cargo`, `rustc` and `wasm-tools`. The recipe
material identifies the current driver/helper sources that actually performed
the observation, rather than pretending they came from an older selected commit.
Tool materials hash selected executable bytes. Names are bounded logical labels,
never private filesystem paths.

The maintained observer also records `dependency-inventory`: the exact hash and
size of `sbom-inputs.json`. It reuses Cargo's actual compiler-artifact records,
captured lock/source manifests and bounded observed cache manifests. Guest,
build dependency, procedural macro, build script, WIT, output and tool roles
stay separate. The [SBOM profile](../component-development/sbom.md) documents
available attribution and the conservative producer license vocabulary. The
packager encodes and embeds the inventory before computing the package digest;
the same BOM bytes can subsequently be attached as detached evidence.

The repository URL is explicitly `operator-asserted`; local commits and inventory
do not authenticate remote repository ownership. This profile always reports
`hermetic: false` and `dependencyCompleteness: "lockfile-only"`. Compiler sysroots,
caches and network dependency retrieval are outside a complete isolated input
closure. Two matching outputs do not establish reproducibility on every machine.
No SLSA level or SLSA conformance is claimed.

## Observation and signing authority

`observation.json` and `BuildObservation` are unsigned assertions.
`decode_build_observation` checks their bounded closed format, fixed echo recipe,
required materials and snapshot association. It cannot prove that a compiler ran.
An approved builder remains responsible for the truth of its signed claims; an
approved key holder can lie.

The Python observer accepts no private key and passes no signing key through build
arguments or environment. Children receive an explicit environment allowlist that
removes arbitrary variables, wrappers and caller-supplied build flags. Host tools
and the maintained recipe remain trusted: this is not a sandbox hiding all host
files from malicious compilers or build scripts. `LocalBuilderSigner` uses the
same checked, bounded, zeroizing PKCS#8 v2 import and approved-public-key match as
the [publisher signer](publisher-trust.md), with independent builder approval.

Construct `PackageSigningSubject` from exact manifest/config bytes after the
[packager](../component-development/packaging.md) has inspected content.
`LocalBuilderSigner::sign_build` requires a capsule subject whose config component
digest and size equal the observed output. The statement binds the component and
the exact package: repackaging unchanged Wasm with different metadata requires new
evidence. Browser/SSR build recipes are outside this initial profile.

The [packaging receipt](../component-development/packaging.md#determinism-and-observed-input-identities)
records supplied-artifact packaging rather than compilation. Original input
hashes in a received receipt remain assertions; its presence or a legacy echo
receipt cannot substitute for authenticated build provenance.

## Statement and detached evidence

The profile uses the [in-toto Statement v1 structure](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md)
with exactly one `lsf-package` subject and custom predicate type
`https://latent.dev/provenance/v1`. The predicate contains format version 1,
`packageSubject`, `builderId`, `issuedAt`, `expiresAt` and the observation.
The in-toto subject SHA-256 equals the package digest without its prefix.
Issuance cannot precede build completion; signed lifetime is positive and at most
31 days. The supported build type is `https://latent.dev/build/echo-capsule/v1`.

One strict Ed25519 signature authenticates [DSSE PAE](https://github.com/secure-systems-lab/dsse/blob/master/protocol.md)
of `application/vnd.in-toto+json` and the exact decoded statement bytes.
Verification interprets those bytes without reserializing their identity.
`keyid` is a SHA-256 raw-public-key fingerprint and only a lookup hint among
explicit approved anchors.

The [OCI evidence format](../protocol/package-format.md#evidence-association)
uses artifact type `application/vnd.latent.provenance.v1`, one
`application/vnd.latent.provenance.payload.v1+json` layer and exact empty config
bytes `{}`. Outer subject, config and payload hashes/sizes are checked separately.
Evidence remains detached to avoid hashing it into the package it signs.
`ProvenanceEvidence::from_envelope` and `inspect_provenance` check syntax and
association, not trusted authorship.

## Builder policy and current proofs

`BuilderPolicy` maps approved raw public keys to builder IDs. Requirements are an
OR of explicit builder/build-type/repository combinations, optional exact
`sourceRevision` and `sourceSnapshotDigest`, and the required
`requireReproducible` boolean. Absent pins are omitted, not `null`. Repository
labels are compared exactly without URL normalization. Empty keys or requirements
deny every build. A `PublisherPolicy` anchor alone cannot authorize builders;
approving one key for both roles requires two independent policies.

`BuilderRevocationSnapshot` is mandatory even with empty lists. Its scope and
`policyDigest` bind the exact canonical policy, including source requirements.
Use `policy.digest()` instead of hashing unsorted input JSON. Keys, requirements
and revocations are sorted for identity; duplicates are rejected. Both snapshots
have positive generations and half-open validity. Failed refreshes never create
fresh empty revocations or extend earlier expiry.

`BuilderVerifier::verify_package` privately constructs `VerifiedBuildProvenance`
after checking exact package/component/evidence associations, strict signatures,
builder authorization, source requirements, revocations and time. The proof binds
source identities, builder/key, evidence/payload, both trust identities and its
verification/expiry times. Expiry is the earliest of signature, key, policy,
revocation and configured proof-age bounds; maximum proof age is one hour.
Equality with expiry is expired.

Call `check_current` before reuse, and match expected package/evidence identities.
Changed snapshots, clock rollback, time before original verification and expired
proofs fail. `replace_trust` requires the expected current state, unchanged scope
and monotonic generations. Changed contents at the same generation are rejected;
identical fresh state is idempotent without renewing validity. A policy change
requires a newly bound higher revocation generation. The verifier rechecks
captured state after cryptography and advances its clock high-water mark even on
rejected operations. Contention fails through the bounded API, without a queue,
network discovery or positive verification cache.

The [durable admission owner](package-admission.md) persists clock/generation
floors and atomically compares proof state at final publication and activation
start. Serialized fields, referrer presence
and matching subjects cannot recreate authority. [SBOM content policy](../component-development/sbom.md)
checks presence and selected attribution requirements; it grants no builder or
publisher authority. The implemented [trusted native compiler and cache](../runtime/trusted-aot.md)
use a separate protected host key and exact runtime/compiler compatibility
binding. A builder signature cannot replace that local native-output authority.

## Bounds and validation

| Resource | Default / hard ceiling |
| --- | --- |
| Unsigned observation / decoded statement | 32,768 / 32,768 bytes each |
| DSSE envelope / outer referrer | 49,152 / 49,152 bytes; 4096 bytes for referrer |
| Policy / revocations | 65,536 / 65,536 bytes each |
| Materials | 64 / 64; 256 MiB per material |
| Component / observed build duration | 64 MiB / 3600 seconds |
| Keys / source requirements | 64 / 256 each |
| Revoked keys / revoked builders | 256 / 256; 64 / 256 |
| Captured files / per-file / total source / archive | 4096 / 4 MiB / 32 MiB / 40 MiB |

Configured Rust limits must be positive and within hard ceilings. JSON rejects
unknown fields, duplicate keys, floats, negative integers and `null`, and bounds
depth to 16, nodes to 4096 and decoded statement/policy strings to 1024 bytes
before retaining typed values. Builder IDs/scopes are nonempty ASCII of at most
128 bytes using letters, digits and `._:/@-`. Material names use letters, digits
and `._-`, beginning with a letter or digit, with the same 128-byte limit.
Repository labels are at most 512 ASCII bytes: HTTPS, a DNS-shaped host and
nonempty portable path segments, without credentials, ports, escaping, query,
fragment or `.`/`..` segments. The five
[schemas](../../schemas/README.md) describe wire shapes; raw byte limits, integer
token spelling, cross-field associations, signatures and current authority need
the Rust API.

`run_bounded` is a main-thread trusted-recipe helper with a combined stdout/stderr
cap of at most 64 MiB, no reader threads or log files, a command deadline of at
most 3600 seconds and five seconds for
cleanup. Normal signal handlers record bounded pending cancellation; explicit
checkpoints deliver it after safe acquisition or during protected capture, and
cleanup defers delivery until release. Windows starts hidden and suspended, assigns a
kill-on-close Job before resuming and accounts for descendants. Linux retains the
leader unreaped while terminating and checking its group, avoiding PID reuse.
Linux containment covers ordinary descendants, not deliberate session escape.
Competing reapers, forced asynchronous exception injection, abrupt supervisor
death and uninterruptible OS process creation are outside this boundary. The
caller owns the single active build slot and evidence/proof retention budgets.

Run `cargo test -p latent-signing --locked`,
`python -m unittest tools.tests.test_build_provenance_schemas` and
`python -m unittest tools.tests.test_build_process tools.tests.test_build_provenance`.
Tests cover bounded shapes, independent builder authority, altered claims, expiry,
revocations, state races, committed snapshots, process overflow, cancellation and
cleanup. The existing bounded authenticated OCI test covers evidence transfer
and verification in its disposable registry.

See [ADR-0023](../../adr/0023-bind-build-attestations-to-observed-inputs-and-builder-trust.md).
