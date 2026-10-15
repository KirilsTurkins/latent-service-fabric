# latent-blobs

Immutable large-value storage with staged writers, ranged readers and explicit transfer ownership. Concrete implementations cover a protected Linux local root and a restricted versioned S3 profile. Public references identify content; capability adapters supply current tenant and publication authority.

Staging, publication, leases and reclamation are separate operations. An abandoned handle remains owned/charged until its physical cleanup boundary; dropping an object is not a background deletion command.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | BlobReference/range/write/lease models and generic storage/transfer ports. |
| [src/local.rs](src/local.rs) | Bounded synchronous immutable storage under one privately owned root. |
| [src/local/fs.rs](src/local/fs.rs) | Descriptor-relative no-follow operations and inode/type checks. |
| [src/provider.rs](src/provider.rs) | Broker integration and owned chunks on bounded blocking/I/O resources. |
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

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-policy](../latent-policy/README.md).

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

Representative source tests (not a complete coverage inventory):

- [`exact_empty_and_ranged_data_survive_reopen`](src/local/tests.rs)
- [`exact_size_and_sequential_writes_reserve_before_staging`](src/local/tests.rs)
- [`duplicate_publication_and_tenant_authority_are_independent`](src/local/tests.rs)
- [`pinned_released_object_is_not_reclaimed_and_drop_does_no_deletion`](src/local/tests.rs)

## Related documentation

- [Blob model](../../docs/architecture/blob-model.md)
- [Durable bounded local immutable blobs](../../docs/runtime/local-blobs.md)
- [S3 immutable blobs](../../docs/runtime/s3-blobs.md)
- [Shared provider pools](../../docs/runtime/provider-pools.md)
- [ADR-0033: Use scoped durable local blobs with owned chunks](../../adr/0033-use-scoped-durable-local-blobs-with-owned-chunks.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
