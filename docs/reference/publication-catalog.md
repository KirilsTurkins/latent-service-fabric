# Tenant-scoped publication catalog

Catalog format 2 implements the storage contract in
[RFC-0002](../../rfcs/0002-tenant-scoped-publication-identity.md) and
[ADR-0027](../../adr/0027-separate-publication-authority-from-component-identity.md).
It separates component bytes, complete immutable packages and permission to use
a package in a particular tenant. Obsolete catalog formats are rejected; there
is no offline migration command. [Deployment and runtime propagation](publication-runtime.md) carries
exact selections through guest start. [Public selectors](publication-api.md) in
the RPC, CLI and six SDKs preserve the same publication identity.

[Web publication admission](web-release-admission.md) uses the same exact scoped
reference construction, root owner and combined storage/index quotas. Its
componentless lifecycle has an explicit admission-mode upgrade that older
readers reject before shared-blob recovery or collection.

`ReleaseDigest` remains the SHA-256 of executable bytes. `PackageDigest` remains
the complete immutable package identity. A `PublicationRef` contains an explicit
scope and a `publication:sha256:` ID computed with the RFC's domain-separated,
length-prefixed construction. Trusted local publication derives its
publication from the canonical original COMPLETE record; it invents no package
digest, publisher signature or observed build.

Two packages with unchanged Wasm can coexist, including a package with a
corrected embedded SBOM. Two authorized tenants can independently admit an
identical tenant-neutral package. A manifest with an embedded tenant continues
to restrict admission to that tenant. Admission never rewrites package metadata
to substitute a receiving tenant.

## Selection and authority

`DirectoryArtifactRepository` exposes exact publication selection, metadata,
fetch, lifecycle status, execution eligibility, lifecycle mutation, evidence
renewal and explicit re-verification. Callers authorize the scope before using
these internal interfaces. Possession of an ID is not permission.

Publication catalog reads and mutations accept `PublicationRef` directly.
The obsolete component-or-publication selector and its repository fallback are
removed. A reference must match the authorized scope; a foreign ID in that
scope appears absent. Component bytes do not substitute for publication identity.
Lifecycle status, revocation/retirement, evidence renewal and operation recovery
use this exact publication API. The artifact repository no longer exposes a
parallel component-addressed lifecycle interface. Operation recovery preserves
the captured publication association.
Internal content-addressed reads still reject ambiguous component associations;
revoked and retired publications continue to count toward ambiguity.

Scoped catalog pages use deterministic publication-ID order and version-2 opaque
cursors. Component digests are not a unique row key or a pagination ordering
contract. A repeated page in the same catalog generation preserves its order;
scope changes and stale generations invalidate its cursor.

Generations, lifecycle records, selected evidence and live grants are independent
per publication. A mutation's compare-and-swap precondition belongs to that
publication. A new package starts with expected generation zero. Reusing the
generation of another publication is a conflict.

Retained successful operation receipts preserve their exact publication association.
Replay after coexistence or restart returns that captured publication and the
original historical result, even if fresh component selection is now ambiguous.
Replay does not restore current eligibility to a revoked or retired publication.

## Persistence and resource ownership

The catalog root contains:

| Path | Responsibility |
| --- | --- |
| `publications/<publication hex>/` | Immutable original metadata, component, admission/evidence files and COMPLETE |
| `blobs/<blob hex>` | Shared immutable file content, hard-linked into publications |
| `lifecycle/records/<publication hex>.json` | Independently mutable lifecycle state with monotonic generations |
| `lifecycle/receipts/` | Bounded operation ring with exact publication associations |
| `lifecycle/evidence/` | Independently selected immutable evidence revisions |
| `.tmp/` | Owned publication/reclamation staging |

The node places this catalog root at `<dataDirectory>/releases`. Its publications
use independent publication identities; obsolete component-keyed roots are rejected.
Updates persist the bounded changed row, receipt, intent and HEAD rather than
rewriting the whole catalog. No publication owns a worker, file descriptor,
guest store, execution cell or provider pool.

The shared content budget conservatively charges global blob bytes plus every
publication link's full logical byte size. It is an exposure bound, not a disk
or RSS measurement. Metadata, file counts, publication counts, input sizes and
startup directory scans have independent limits. Incomplete directories retain
their disk and directory charges. Node configuration exposes the content limits
under [`catalogs`](standalone-node.md); lifecycle history has separate finite limits.

`reclaim_uncommitted_content` accepts a batch of 1–1024 entries. It only removes
uncommitted publications and zero-reference blobs. A committed publication,
including revoked/retired history, keeps its content pin. A live preparation
source therefore cannot lose committed bytes through this maintenance operation.
Directory unlink and parent synchronization precede refunds. An indeterminate
write or reclamation failure requires reopening; it cannot refund a live owner.
Unknown incomplete directories require offline inspection and repair. This
implementation does not offer deletion of committed historical payloads.

## Supported storage and fresh state

Current alpha builds accept the publication catalog and lifecycle format 2.
The obsolete format-1 reader, offline migrator, retained migration associations
and `latentd migrate-catalog` command have been removed. Obsolete roots and
interrupted migration fences are rejected before temporary cleanup, publication
indexing or lifecycle grants. Startup preserves their existing bytes.

For an obsolete root, stop the old node and preserve a complete, consistent
backup of its data directory, protected configuration and trust history.
Provision a separate empty data directory with the current configuration,
explicitly publish and admit the intended packages, and apply current deployment
and trigger manifests. Historical operation identities and receipts are not
imported. Do not copy individual rows, remove format markers or point the new
node at an old root to force startup.

Current-format reopen, crash recovery, policy denial and operation receipts
retain their normal semantics. The qualified native upgrade pair uses current
storage formats; it does not convert obsolete catalog formats. Downgrading a
binary does not undo storage changes. Preserve stopped backups independently.

## Validation

Small Linux fixtures cover concurrent publications, scoped selection, independent
revocation/retirement, exact operation replay after coexistence, storage limits,
shared inode retention during orphan reclamation, preservation of rejected obsolete roots,
empty catalogs and current lifecycle interruption recovery. Policy integration uses
real publisher and builder signatures with corrected embedded inventories and
identical packages in two tenants. These are functional tests, with no guest
invocations or 100k load campaign.
