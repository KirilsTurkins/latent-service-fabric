# ADR-0027: Separate publication authority from component identity

- Status: accepted
- Date: 2026-09-13
- Issue: #264
- RFC: [RFC-0002](../rfcs/0002-tenant-scoped-publication-identity.md)
- Supersedes: ADR-0019's retained one-component/one-publication uniqueness rule

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

Existing `ReleaseDigest` values and wire fields remain component identities.
Add explicit publication selectors and result fields. Fresh legacy resolution
must be unique within the authorized scope or reject ambiguity; it never chooses
first/latest or skips a revoked association to select another package. Captured
deployment revisions, route/rollback targets and operation receipts retain their
original publication through migration and restart.

Share immutable bytes or code only under independently bounded ownership and
exact compatibility. A cache hit cannot share another tenant's metadata, grants,
lifecycle generation, provider secrets or permission. Each activation retains
fresh guest state and its own current authority.

## Migration and failure boundary

Use a bounded, versioned offline migration under the existing catalog-root owner.
Preserve immutable completion/package bytes and historical receipts, record exact
legacy mappings and deterministic durable progress, and fail closed on damaged,
incomplete or ambiguous associations. An existing old-reader-checked format fence
must prevent older binaries from using a migrated or partially migrated root.
Do not rely on a new marker that old code ignores.

Do not serve mixed layouts or erase security floors to satisfy quotas. Downgrade
requires a complete consistent offline restore; rewriting digest meanings or
removing the fence is unsupported. RFC-0002 defines batch/retention bounds,
recovery and the compatibility/owner matrix.

## Delivery and consequences

#265 owns catalog, lifecycle and storage migration; #266 owns deployment/runtime
and native/prepared authority; #267 owns public selectors, all six SDK models and
the integrated operator workflow. Their coexistence, revocation, restart,
legacy-client and resource-ownership evidence is required by #238/#240.

This decision allocates no runtime resource and makes no claim that its
implementation is already delivered. Dormant publications remain bounded
metadata/artifacts rather than dedicated repositories, processes, file handles,
workers, providers, stores or execution cells. Phase 4 transactions and Phase 5
clustering remain separate work.
