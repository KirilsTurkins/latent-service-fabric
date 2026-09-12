# ADR-0023: Bind build attestations to observed inputs and builder trust

- Status: Accepted
- Date: 2026-09-12
- Related: [ADR-0019](0019-separate-package-identity-from-component-identity.md), [ADR-0022](0022-bind-publisher-proofs-to-current-explicit-trust.md), [#144](https://github.com/KirilsTurkins/latent-service-fabric/issues/144)

## Context

Package identity, supplied-artifact receipts and publisher signatures do not
establish how a component was built. A serialized flag cannot prove execution,
and matching detached subjects cannot lend publisher authority to a builder.
Build claims need exact output associations, bounded actual observation and a
separate current operator-approved builder policy.

## Decision

Execute the pinned maintained echo recipe from a bounded committed Git archive
allowlist. Identify source through a canonical file inventory and record actual
tool executable, lockfile and current driver/helper identities. Distinguish the
selected historical source from the observing recipe. Check inputs and tools
again after execution. Publish successful bounded outputs only after cleaning
owned intermediates.

Describe repository ownership as operator-asserted, dependency completeness as
lockfile-only and builds as nonhermetic. Record two-build byte equality only after
executing that check. Existing supplied-artifact and legacy receipts remain
unsigned observations of their own operations, not evidence of compilation.

Treat the Python-to-Rust observation as untrusted serialized input. An approved
builder signs a restricted in-toto Statement v1 with a custom LSF predicate and
one strict Ed25519 signature over exact DSSE PAE bytes. Bind exact package and
checked config component digest/size to observed output. Keep evidence detached
to avoid digest cycles. Claim no generic predicate support or SLSA level.

Use separate builder signer, policy, revocation, verifier and proof types.
Requirements explicitly bind builder, recipe and source repository, optionally
pinning revision/snapshot and requiring observed reproducibility. Publisher-only
anchors never confer builder authority. Apply bounded canonical snapshots,
explicit even-empty revocations, freshness, monotonic generations, clock floors
and expected-state replacement as in ADR-0022. Bind proofs to exact
source/output/evidence and both current trust identities.

Keep signing keys out of child arguments/environment. Execute trusted recipes
with finite command/output/cleanup budgets and no logs or reader threads. Use
suspended Windows Job assignment and an unreaped Linux process-group leader,
deferring normal cancellation until ownership is recoverable. These controls
cover ordinary descendants and do not claim a hostile-build sandbox or Linux
session-escape containment.

## Consequences

Authenticated provenance attests what an approved builder asserts. A compromised
builder can lie; signatures do not prove compiler honesty or remote repository
ownership. Sysroots and dependency caches remain trusted inputs outside a
complete hermetic identity closure.

The initial recipe supports maintained echo capsules. Browser/SSR recipes, SBOM
policy, durable catalog admission and native compiler evidence require separate
implementation. Durable owners must persist clock/generation floors and compare
proof state atomically at publication. Serialized proof fields confer no trust.

Validate with tiny shape/trust/process adversarial tests, an actual observed echo
build and the existing bounded authenticated OCI integration. Retain no private
fixture keys or large load reports. The [reference](../docs/reference/build-provenance.md)
specifies formats, executable workflows, currentness and limits.
