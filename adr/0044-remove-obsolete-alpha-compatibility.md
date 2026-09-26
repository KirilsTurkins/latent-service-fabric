# ADR-0044: Remove obsolete alpha compatibility

- Status: Accepted; records the maintainer's alpha compatibility policy
- Date: 2026-09-23
- Supersedes: ADR-0019's preservation of obsolete catalog layouts, ADR-0027's
  legacy selectors and offline migration, and ADR-0043's format-v1 HTTP recovery

## Context

LSF is still in alpha. Earlier decisions retained old storage formats, ambiguous
component-based publication selectors and deprecated client entry points while
new contracts were introduced. Maintaining those paths now obscures the current
authority model and makes documentation and qualification cover obsolete APIs.
The maintainer has directed that obsolete alpha compatibility be removed without
a deprecation period.

This changes compatibility policy, not the meaning of existing identities or the
integrity of historical records. A component digest still identifies executable
bytes; it cannot stand in for a tenant-scoped publication or current permission.

## Decision

Maintain one documented current contract for each surface. Remove obsolete
readers, migrators, selectors, aliases and deprecated SDK entry points when their
replacement is implemented and checked. New code and examples use explicit
publication identities and current client profiles. No fallback may guess a
publication, translate an ambiguous request or silently widen authority.

Current catalog recovery accepts only its documented formats. An obsolete root
must be rejected before cleanup or mutation, preserving its bytes for inspection
or restoration with the matching old software. Do not upgrade rejected data by
removing format markers, editing security floors or importing individual rows.
The operator preserves a consistent stopped backup and provisions a separate
empty current data directory when no supported upgrade path exists.

A qualified native binary upgrade is valid only for its tested source and
destination versions and storage contracts. It does not promise conversion of
all earlier alpha formats. Binary downgrade and data restoration remain separate
operations.

Update current repository documents, diagrams and guides when behavior changes.
Keep roadmap phases and implementation gate details in contributor material;
user guides teach the supported task. Remove stale duplicate instructions.
Published version snapshots and signed or measured historical records retain
their original identities and bytes. Label and link them as historical instead
of presenting them as instructions for current development.

The Wiki retirement decision in
[ADR-0041](0041-publish-single-source-version-bound-documentation.md) is unchanged:
after completion and verified site deployment, remove the separate public Wiki.
There is no requirement to preserve its legacy URLs or a stale public archive.

## Consequences

Alpha users may need to recreate local catalogs and adapt applications. Current
reference pages must state supported formats and APIs directly, and error paths
must identify unsupported input without modifying it. Retained operation receipts
continue to describe historical results; they never regain execution authority.

Removing compatibility does not remove current resource, cancellation, trust,
revocation or uncertainty guarantees. Each implementation change still needs
its normal review and relevant checks. A new language toolchain, provider or
storage format is not supported merely because this policy allows old code to
be deleted.

This decision permits neither rewriting historical evidence nor publishing a
runtime release. The separate release approval remains required.

## Current implementation references

- [Publication catalog](../docs/reference/publication-catalog.md)
- [Publication selectors](../docs/reference/publication-api.md)
- [HTTP trigger contract](../docs/reference/http-triggers.md)
- [SDK ownership and profiles](../sdk/README.md)
- [Contribution rules](../CONTRIBUTING.md)
