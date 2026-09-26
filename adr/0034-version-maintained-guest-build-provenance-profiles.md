# ADR-0034: Version maintained guest build provenance profiles

- Status: Accepted
- Date: 2026-09-15
- Supersedes: The echo-only recipe ceiling in [ADR-0023](0023-bind-build-attestations-to-observed-inputs-and-builder-trust.md)
- Related: [ADR-0031](0031-version-host-abi-recognition-independently-of-provider-authority.md), [#221](https://github.com/KirilsTurkins/latent-service-fabric/issues/221)

## Context

The Phase 3 guest SDK needs executable examples admitted through publisher and
builder verification. Calling their compilation an echo build would make the
attestation false. Expanding an already approved recipe implicitly would also
expand existing builder authority.

## Decision

Keep `https://latent.dev/build/echo-capsule/v1` and its serialized recipe unchanged.
Add separate closed `https://latent.dev/build/rust-guest/v1` and
`https://latent.dev/build/c-guest/v1` profiles. Builder requirements must approve
the exact profile and source repository. Existing echo approvals authorize
neither new profile. Preserve the exact package/component association, detached
evidence, independent publisher and builder trust, and current revocation checks.

The Rust recipe accepts only the nine maintained `guest-*` examples: HTTP,
streaming HTTP, blob, secrets, events, random, metrics, service and its callee.
It uses the locked workspace release build for `wasm32-unknown-unknown`.
The C recipe accepts only the generated blob conformance fixture, compiled by
pinned Zig in reactor mode with a 64 KiB stack. Its Wasm component has no WASI
imports; use of the compiler's WASI libc does not grant filesystem or network
access. Both use the pinned authoritative WIT generator and component tools.

Guest builds identify explicit input files in the current worktree, including
the lockfile, manifests, toolchain/configuration, WIT, SDK, examples and build
helpers. The canonical inventory digest is both `snapshotDigest` and the guest
profile's 64-digit `revision`; this revision is a content identity, not a Git
commit claim. Observe actual selected tool executable bytes and compare tools
and inputs again after compilation. Publish the completion marker only after
all selected outputs pass these checks. Signing consumes the observed output
and exact inspected package; an incomplete build is not a successful observation.

Use the existing finite subprocess/output supervision, explicit environment
allowlist and separate signing boundary. Reports say `hermetic: false`,
`reproducibility: not-checked` and
`dependencyCompleteness: declared-inputs-incomplete`. The selected source list
does not cover compiler sysroots, every dependency/cache byte or every host file.
Repository ownership remains operator-asserted. No SLSA level is claimed.

## Consequences

Compiled Rust and C examples can exercise real enforced admission without a
development bypass. Their small components, package inputs and observations are
temporary build outputs; only compact binding hashes remain in Git. CI executes
the guests against real provider and node owners, including cancellation,
abandonment, typed errors and reuse.

An approved builder can still lie. These are trusted recipes with bounded
process ownership, not a hostile-build sandbox. They neither authorize arbitrary
application recipes nor change the external SDK or runtime isolation profiles.
Future recipes require explicit versioned contracts and builder approval.

The [guest SDK reference](../docs/component-development/guest-sdk.md) describes
the executable workflow, exact ABI, ownership rules and validation limits.
