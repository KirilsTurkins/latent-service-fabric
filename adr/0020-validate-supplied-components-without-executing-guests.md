# ADR-0020: Validate supplied components without executing guests

- Status: Accepted
- Date: 2026-09-12
- Related: [ADR-0019](0019-separate-package-identity-from-component-identity.md), [#141](https://github.com/KirilsTurkins/latent-service-fabric/issues/141)

## Context

Package identity binds bytes, but cannot establish that a supplied component
implements the accompanying WIT or typed metadata. The maintained Phase 0 echo
builder is a fixture-specific compiler workflow. Packaging must also support
general supplied components and opaque browser/SSR content without creating
runtime execution resources or making unsupported build-provenance claims.

The existing contract descriptors name records and variants without carrying
their complete definitions. Comparing descriptor names or category tags alone
would miss incompatible nested fields and variant payloads.

## Decision

Add `latent-packaging` above the artifact/manifest/contract crates. It has no
Wasmtime, executor or node dependency. Pin `wasmparser` and `wit-parser` to
0.252.0, matching the existing runtime dependency family. Before either full
binary validation or WIT reconstruction can allocate from untrusted structures,
preflight byte extents, vectors, nesting, local/operator counts and embedded
package documentation. Bound transitive type depth and conservative expanded
work, including aliases and flat reference chains, before constructing the
validator. Validate every core body, including unused modules.

Resolve the exact pinned WIT source graph, reject missing/extra/changed
dependencies, and compare complete supported type structures against the
component. Require the current host imports to match repository-authoritative
context/log/clock definitions. Reject unsupported analysis rather than treating
it as successful compatibility. This is a synchronous, bounded structural
check; guest behavior and future release-to-release compatibility are separate.

Preserve the existing typed descriptor wire format as a checked projection.
Exactly one contract/interface descriptor represents each exported interface.
Validate function identity, parameter/result projection and direct interface
dependencies. Preserve documentation, attributes and the existing recursively
sorted JSON digest algorithm. Full named definitions remain in the bound WIT
source graph, not a new incompatible descriptor representation.

Build deterministic package content from supplied bytes. Canonicalize capsule,
contract and lock metadata after validating their original associations. Add a
digest-bound receipt recording raw input identities and resulting output
identities. It records a packaging operation, not a compiler invocation, clean
source state, reproducible compilation or verified publisher provenance.

Use `cap-std` and `cap-fs-ext` 4.0.3 for handle-relative filesystem access. The
caller supplies an approved root. Descendant path segments cannot follow
symlinks; files must be regular and fit individual/aggregate bounds. Recipes
select files explicitly, with no archive extraction or directory discovery.
Exports create a new directory and commit the manifest last; the reader rejects
partial, altered or extra content. Output parents must remain under the
operator's control during export. These client directories are not node catalogs
and do not claim the catalog's crash-durability semantics.

## Consequences

An immutable bundle retains exact package/configuration/layer bytes and a small
checked summary. It contains no caller-set trusted/admitted flag, guest Store,
engine, prepared code, worker, connection or persistent file handle. Inspection
does not authorize tenant access or bypass future trust/eligibility checks.

Identical declared input bytes, logical paths, recipe metadata and packager
version produce identical output identities, independent of physical input
roots or input-file enumeration order. Different raw metadata representations
can produce different receipts even when canonical payloads match. Signatures
and attestations remain detached and may have intentionally variable fields.

Finite parser/work ceilings can reject unusually complex valid components.
Limits may be lowered, never raised above the supported profile; they describe
bounded input and work, not exact process RSS. Browser/SSR packages remain
non-executable content and are never run by packaging or inspection.

## References

- [Packaging workflow](../docs/component-development/packaging.md)
- [Capability filesystem implementation](https://github.com/bytecodealliance/cap-std)
- [No-follow directory API](https://docs.rs/cap-fs-ext/4.0.3/cap_fs_ext/trait.DirExt.html)
