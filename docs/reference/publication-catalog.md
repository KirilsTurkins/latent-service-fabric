# Tenant-scoped publication catalog

Catalog format 2 implements the storage contract in
[RFC-0002](../../rfcs/0002-tenant-scoped-publication-identity.md) and
[ADR-0027](../../adr/0027-separate-publication-authority-from-component-identity.md).
It separates component bytes, complete immutable packages and permission to use
a package in a particular tenant. The catalog library and offline migration are
implemented. Runtime/deployment propagation (#266) and public selectors in the
RPC, CLI and six SDKs (#267) remain their own integration steps.

`ReleaseDigest` remains the SHA-256 of executable bytes. `PackageDigest` remains
the complete immutable package identity. A `PublicationRef` contains an explicit
scope and a `publication:sha256:` ID computed with the RFC's domain-separated,
length-prefixed construction. The local trusted compatibility path derives its
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

Fresh legacy component selection within an authorized scope returns no match,
the sole publication, or `StateConflict` with `publication-selector-ambiguous`
and `retryable: false`. Revoked and retired publications still count; revocation
does not silently choose a different package. Non-unique artifact references
also require explicit selection. Invalid selectors never fall back to legacy
selection, and a foreign ID in the authorized scope appears absent.

Scoped catalog pages use deterministic publication-ID order and version-2 opaque
cursors. Component digests are not a unique row key or a pagination ordering
contract. A repeated page in the same catalog generation preserves its order;
scope changes and stale generations invalidate its cursor.

Generations, lifecycle records, selected evidence and live grants are independent
per publication. A mutation's compare-and-swap precondition belongs to that
publication. A new package starts with expected generation zero. Reusing the
generation of another publication is a conflict.

Retained successful legacy operation receipts preserve their original association.
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
| `.publication-migration/` | Migration progress, original lifecycle archive and legacy associations |

The node still places this catalog root at `<dataDirectory>/releases`; the inner
format-1 `releases/<component hex>` directory is historical after migration.
Updates persist the bounded changed row, receipt, intent and HEAD rather than
rewriting the whole catalog. No publication owns a worker, file descriptor,
guest store, execution cell or provider pool.

The shared content budget conservatively charges global blob bytes plus every
publication link's full logical byte size. It is an exposure bound, not a disk
or RSS measurement. Metadata, file counts, publication counts, input sizes and
startup directory scans have independent limits. Incomplete directories retain
their disk and directory charges. Node configuration exposes the content limits
under [`catalogs`](standalone-node.md); lifecycle and archived migration history
have separate finite limits.

`reclaim_uncommitted_content` accepts a batch of 1–1024 entries. It only removes
uncommitted publications and zero-reference blobs. A committed publication,
including revoked/retired history, keeps its content pin. A live preparation
source therefore cannot lose committed bytes through this maintenance operation.
Directory unlink and parent synchronization precede refunds. An indeterminate
write or reclamation failure requires reopening; it cannot refund a live owner.
Unknown incomplete directories require offline inspection and repair. This
implementation does not offer deletion of committed historical payloads.

## Offline upgrade and recovery

Stop the node and preserve a complete, consistent backup of its data directory,
configuration and trust history. Use the same filesystem with working file
locks, hard links, atomic same-filesystem renames and directory synchronization.
Run on a supported Linux host:

```sh
latentd migrate-catalog --config /secure/node.json
```

The command starts no listener, guest engine, compiler or worker pool. It derives
the original node settings, opens the configured trust owner when required, and
acquires the existing exclusive catalog root owner. An already running owner
prevents migration. It prints one bounded JSON receipt after completion.

| Option | Default | Scope |
| --- | --- | --- |
| `--batch-size` | 32 | 1–1024 publication rows or operation receipts per durable progress batch |
| `--max-metadata-bytes` | 268435456 | Retained migration/index planning ceiling, at most 1 GiB |
| `--max-disk-bytes` | 8589934592 | Conservative old/new content and history exposure estimate |
| `--max-files` | 1000000 | Conservative source/destination file and directory bound |
| `--max-work-bytes` | 68719476736 | Conservative bounded verification-work estimate |

Destination catalog, content and migration limits are checked before fencing.
Planning reserves the configured maximum future admission-grant size without
requiring expired historical evidence to become current. If these limits reject
an upgrade before fencing, size the limits for the actual retained catalog and
retry. The estimate is not an OS I/O meter. Small defaults in an operator's
existing catalog configuration can reject a larger retained catalog.

The first durable fence replaces `LIFECYCLE_MODE` with the migration intent.
The old reader rejects that marker before cleanup or adoption. Migration uses a
separate namespace outside its temporary cleanup path. Original COMPLETE,
immutable content and lifecycle archive bytes remain exact. Rows and retained
receipts gain deterministic publication associations; missing, damaged or
ambiguous history fails closed. Selected expired evidence remains history and
does not gain positive authority from the migration.

After interruption, keep the original configuration and all migration options
unchanged and rerun the same command. The intent binds the source, configuration
and limits. Progress resumes verified batches, including interruptions at both
lifecycle directory swaps. Changed inputs or missing history require restoration
of the complete consistent backup and an operator investigation. Do not delete
markers or copy individual rows to force startup.

Completion restores the root marker only after format-2 lifecycle history and
the migration receipt are durable. Old readers then reject the lifecycle format
version. Downgrading in place is unsupported. Restoring the complete offline
backup is the rollback path, and discards any subsequent format-2 operations.
An idempotent invocation validates the current catalog before returning the
historical migration receipt; its publication count describes the migration,
not later admissions.

This storage migration preserves the configured trust mode. Converting local
trusted content into enforced signed admission remains the separate procedure in
[authenticated package admission](package-admission.md).

## Validation

Small Linux fixtures cover concurrent publications, scoped selection, independent
revocation/retirement, successful legacy replay after coexistence, storage limits,
shared inode retention during orphan reclamation, original-byte preservation,
empty catalogs and eight migration interruption points. Policy integration uses
real publisher and builder signatures with corrected embedded inventories and
identical packages in two tenants. These are functional tests, with no guest
invocations or 100k load campaign.
