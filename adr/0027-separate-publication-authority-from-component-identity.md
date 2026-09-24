# ADR-0027: Separate publication authority from component identity

- Status: accepted
- Date: 2026-09-13
- Issue: #264
- RFC: [RFC-0002](../rfcs/0002-tenant-scoped-publication-identity.md)
- Supersedes: ADR-0019's retained one-component/one-publication uniqueness rule
- Partly superseded by: [ADR-0044](0044-remove-obsolete-alpha-compatibility.md),
  which removes obsolete alpha selectors and catalog migration

## Context

Component bytes can legitimately appear in different immutable packages and
tenant admissions. The current component-keyed catalog prevents a corrected
embedded SBOM from coexisting with its original package and couples one
component to one tenant/package association. That compatibility restriction
must not become the authority model used by Phase 3 providers, deployments and
public clients.

## Decision

Keep component digest, immutable package digest, scoped publication/admission
identity and deployment revision separate. The component remains the identity
of executable bytes; it does not identify an authorized publication.

Introduce the strict, domain-separated `PublicationId` and scoped
`PublicationRef` specified by RFC-0002. One scope plus one immutable package
identifies a publication. Trusted-local artifacts use their immutable local
completion identity and never acquire an invented package digest or signature.

Different packages sharing a component coexist. The same tenant-neutral package
may be independently authorized in different tenants; an embedded tenant
restriction still applies. Receiving scope is stored separately from immutable
signed metadata, which is never rewritten. Lifecycle generations, evidence
selection, grants and operation replay remain publication-specific.

Preserve ADR-0019's package/component distinction, ADR-0010's metadata/policy
separation and ADR-0024's package-bound immutable SBOM. Correcting an embedded
inventory produces a new package/publication rather than mutating the old one.

`ReleaseDigest` values remain component identities. Public selection uses explicit
publication references and result fields. Obsolete component-or-publication
fallback is removed under ADR-0044. Captured deployment revisions, route/rollback
targets and operation receipts retain their original publication through
current-format restart and recovery.

Share immutable bytes or code only under independently bounded ownership and
exact compatibility. A cache hit cannot share another tenant's metadata, grants,
lifecycle generation, provider secrets or permission. Each activation retains
fresh guest state and its own current authority.

## Storage and failure boundary

ADR-0044 replaces this decision's original offline migration and legacy mapping
requirements. Current builds reject obsolete or interrupted migration roots
before cleanup or mutation. The [catalog reference](../docs/reference/publication-catalog.md)
describes current-format recovery and provisioning a separate empty data root.

Do not serve mixed layouts, erase security floors or remove format markers to
force startup. Preserve a complete consistent stopped backup before replacing
old data. A binary downgrade does not convert stored state.

## Delivery and consequences

#265, #266 and #267 delivered catalog/lifecycle identity, deployment/runtime
propagation and public selectors across all six client SDKs. Subsequent alpha
cleanup removes migration and legacy-client entry points. Coexistence,
revocation, exact operation recovery and resource ownership remain required.

Dormant publications remain bounded
metadata/artifacts rather than dedicated repositories, processes, file handles,
workers, providers, stores or execution cells. Phase 4 transactions and Phase 5
clustering remain separate work.
