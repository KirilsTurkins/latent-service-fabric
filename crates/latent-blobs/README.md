# latent-blobs

Immutable large-value storage with staged writers, ranged readers and explicit transfer ownership. Concrete implementations cover a protected Linux local root and a restricted versioned S3 profile. Public references identify content; capability adapters supply current tenant and publication authority.

Staging, publication, leases and reclamation are separate operations. An abandoned handle remains owned/charged until its physical cleanup boundary; dropping an object is not a background deletion command.

An explicitly selected durable local root retains verified provisional pins and
requires a fresh, matching state-store view before physical reference release.
The durable opener binds the actual live engine, not just its persisted label;
an ordinary opener preserves the release fence but cannot mint durable pins or
approve release until the trusted durable opener binds a store. After restart,
the host must select and validate the intended store before binding it.
The transaction coordinator has a trusted library attachment path for verified
local payloads through [latent-local-blobs](../latent-local-blobs/README.md).
That crate owns the original local implementation and affine captured session;
this facade re-exports its types. S3 references do not acquire the local retention
guarantee, and this does not install a guest reference-dispatch path.
Standalone startup rejects required durable payload references until its
physical blob inventory is installed; logical records alone cannot prove bytes
are present.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | BlobReference/range/write/lease models and generic storage/transfer ports. |
| [src/local.rs](../latent-local-blobs/src/local.rs) | Bounded synchronous immutable storage under one privately owned root. |
| [src/local/durable.rs](../latent-local-blobs/src/local/durable.rs) | Opt-in local retention pins and state-backed release checks. |
| [local filesystem owner](../latent-local-blobs/src/local/fs.rs) | Descriptor-relative no-follow operations and inode/type checks; the private S3 filesystem helper retains a checked identical copy. |
| [src/provider.rs](../latent-local-blobs/src/provider.rs) | Broker integration and owned chunks on bounded blocking/I/O resources. |
| [src/s3.rs](src/s3.rs) | HTTPS, explicit peers, SigV4, versioned bucket and finite multipart staging. |
| [src/s3/inventory.rs](src/s3/inventory.rs) | Durable upload receipts that precede network mutations and survive uncertain replies. |
| [src/s3/provider/recovery.rs](src/s3/provider/recovery.rs) | Explicit bounded operator reconciliation without automatic uncertain completion replay. |

## Execution and ownership

1. Install a protected local root or exact S3 profile and matching broker policy.
2. Reserve bounded writer/storage/transfer capacity before staging; sequential writes remain private until seal/publication.
3. Expose immutable scoped references and owned range chunks. Readers and pins keep underlying objects alive.
4. Close/release through the actual owner, then reclaim only unpinned eligible content; reconcile uncertain S3 state explicitly.

## Integration boundaries

Local primitives are synchronous and belong on an existing bounded blocking owner. S3 uses no ambient credentials or automatic refresh. Multipart network effects do not imply rollback, command atomicity or universal exactly-once delivery. Shared content identity never merges tenant authority.

## Dependencies and build

Direct workspace dependencies: [latent-local-blobs](../latent-local-blobs/README.md), [latent-core](../latent-core/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-policy](../latent-policy/README.md). Linux additionally selects [latent-state](../latent-state/README.md) and the HTTP dependency below.

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Target-specific workspace edges:

| Target / dependency section | Package |
| --- | --- |
| `cfg(target_os = "linux"):dependencies` | [latent-http](../latent-http/README.md) |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-blobs.lib.latent-blobs
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

The local cases below belong to `latent-local-blobs`; prepare and run that
package's registered selection separately from the facade/S3 suite above.
Representative source tests (not a complete coverage inventory):

- [`exact_empty_and_ranged_data_survive_reopen`](../latent-local-blobs/src/local/tests.rs)
- [`exact_size_and_sequential_writes_reserve_before_staging`](../latent-local-blobs/src/local/tests.rs)
- [`duplicate_publication_and_tenant_authority_are_independent`](../latent-local-blobs/src/local/tests.rs)
- [`pinned_released_object_is_not_reclaimed_and_drop_does_no_deletion`](../latent-local-blobs/src/local/tests.rs)

## Related documentation

- [Blob model](../../docs/architecture/blob-model.md)
- [Durable bounded local immutable blobs](../../docs/runtime/local-blobs.md)
- [S3 immutable blobs](../../docs/runtime/s3-blobs.md)
- [Shared provider pools](../../docs/runtime/provider-pools.md)
- [ADR-0033: Use scoped durable local blobs with owned chunks](../../adr/0033-use-scoped-durable-local-blobs-with-owned-chunks.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)

Each local/S3 range read reserves its exact possible lowering-copy capacity before storage or network I/O. The returned chunk binds the original buffer, copy reservation and `PoolCall`; its single affine materialization keeps the original native credit and request alive through guest lowering, even after the source resource closes. Empty ranges remain valid and cannot create a second materialization.

Installed local/S3 writes use borrowed input: after pure bounds and original pool admission, the exact future backing is prepared before the same admission copies bytes into its paid `IoBuffer`. The local blocking job owns the buffer through physical write or cancellation; S3 owns it only through append, before separately scoped ProtocolPages storage. The existing host `write(Vec)` API remains the explicit preallocated-input route.
