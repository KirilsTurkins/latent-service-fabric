# latent-local-blobs

Owns Linux local immutable blob storage and its capability adapter. The separate
crate lets the transaction coordinator retain the original verified local payload
without depending on the S3 implementation. `latent-blobs` re-exports the same
`BlobReference`, `BlobRange`, local store and provider types; those names do not
create a second store, reader or retention owner.

Only reference/range models are available on other targets. The filesystem and
provider implementation is Linux-gated and the package is not published to
crates.io. This is a Development source boundary, separate from alpha.5.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Shared immutable reference/range models and target gates. |
| [src/local.rs](src/local.rs) | Protected local store, retained root and bounded native owners. |
| [src/local/fs.rs](src/local/fs.rs) | Descriptor-relative no-follow operations, ownership and inode checks. |
| [src/local/write.rs](src/local/write.rs) | Finite sequential staging, verification and durable publication. |
| [src/local/read.rs](src/local/read.rs) | Exact ranged reads and live file pins. |
| [src/local/reclaim.rs](src/local/reclaim.rs) | Explicit release/reclamation under retained physical ownership. |
| [src/local/recovery.rs](src/local/recovery.rs) | Bounded inventory, durable mode recovery and refusal of unknown/corrupt entries. |
| [src/local/durable.rs](src/local/durable.rs) | Affine `LocalDurablePin`, actual-engine binding and coherent required-blob inventory. |
| [src/provider.rs](src/provider.rs) | Capability-governed adapter on the existing bounded provider pools. |
| [src/provider/durable.rs](src/provider/durable.rs) | `CapturedLocalPayload` tying a verified pin to its original session and provider. |

## Execution and ownership

1. Open one private root with explicit namespace and limits. Retain its lock and
   descriptor/inode checks while any native owner survives.
2. Admit actual provider work, memory and activation budget before staging or
   copying. File work runs on the installed shared blocking owner.
3. Verify digest, size and scope before publishing an immutable reference or
   returning a reader. Returned chunks retain their original lowering and I/O
   owners independently of the reader.
4. Consume/close guest resources without performing deletion in Drop. Only
   explicit eligible release/reclamation synchronizes file removal and refunds
   capacity. Cancellation and a lost response do not prove a mutation failed.

The [local-blob guide](../../docs/runtime/local-blobs.md) owns the exact ABI,
filesystem requirements and independent stage/disk/metadata/work limits.

## Durable payload integration

`open_durable` binds the actual `EmbeddedStore`; `open_durable_for_view` binds its
coherent view. A persisted durable-mode label alone cannot mint a pin. An ordinary
opener preserves that release fence; a trusted host may bind an existing mode
through `bind_existing_durable_for_view` only before sharing the owner and after
checking the exact engine identity and provider configuration.

`capture_reference` performs the existing authorized open on the original
capability session and returns an affine `CapturedLocalPayload`. Its session,
provider, tenant, store binding, verified bytes and native reader travel together.
An encoded reference or digest cannot reconstruct this owner.

`RequiredBlobInventory` walks a coherent required-owner catalogue in bounded
pages, retaining the original local owner and snapshot identity. The host still
owns semantic closure validation, startup capacity/deadline checks and the final
readiness decision. Inventory is an observation, not deletion or read authority.
Release checks take a fresh matching engine view while retaining the original
publication guard; provisional pins prevent racing reclamation.

The [command envelope](../latent-commit/README.md) can attach verified local
payloads through its trusted library API. Standalone startup still rejects
required payload-reference rows because it has not installed the complete
physical inventory; this is not a generally available guest reference-dispatch
path. S3 has no constructor for these local custody types. State, snapshot,
retention and end-to-end acceptance must be qualified at their consuming owners.

## Dependencies and build

Normal dependency: [latent-core](../latent-core/README.md). Linux dependencies:
[latent-capabilities](../latent-capabilities/README.md),
[latent-policy](../latent-policy/README.md), [latent-state](../latent-state/README.md),
Serde, SHA-256 and rustix. See [Cargo.toml](Cargo.toml) for exact edges.
`latent-blobs` consumes this crate directly; `latent-commit` selects it under
the dependency alias `latent-blobs`, preserving one custody implementation.

## Tests and verification

Inspect the registered selection before preparing native inputs:

```sh
python3 tools/test.py explain --suite latent-local-blobs.lib.latent-local-blobs
```

Follow [local tests](../../docs/development/local-tests.md) for the selected
recipe and Linux prerequisites. [Local tests](src/local/tests.rs) and the
[durable cases](src/local/tests/durable.rs) cover restart, tenant separation,
finite capacity, retained pins, engine/view substitution, required-file inventory
and uncertain filesystem boundaries. The facade's type-identity tests live in
[latent-blobs](../latent-blobs/src/lib.rs). Registered cases and source review
are distinct from executed signed-node or storage-device qualification.

## Related documentation

- [Blob architecture](../../docs/architecture/blob-model.md)
- [Local immutable blobs](../../docs/runtime/local-blobs.md)
- [Atomic command envelope](../../docs/development/atomic-command-envelope.md)
- [Protected state owner](../../docs/development/shared-state-store-owner.md)
- [Workspace package index](../README.md)
