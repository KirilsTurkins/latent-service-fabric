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
| [src/local/durable.rs](src/local/durable.rs) | Affine `LocalDurablePin`, actual-engine binding and reference audit. |
| [src/local/durable/required.rs](src/local/durable/required.rs) | Charged, generation-fenced required-blob recovery pages. |
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

Once a staged write reaches physical I/O, an error or an unwinding completion
checkpoint permanently disables that writer: it cannot resume or seal. Its
original stage, descriptors and capacity remain owned until the writer retires;
only explicit reclamation refunds an abandoned stage. A refused pre-write
checkpoint leaves the untouched writer reusable.

The [local-blob guide](../../docs/runtime/local-blobs.md) owns the exact ABI,
filesystem requirements and independent stage/disk/metadata/work limits.

## Recovery and inventory bounds

Release writes the exact versioned `RELEASED` record. Both reopening and live
reclamation validate its contents through protected, bounded reads before
classifying an object as released or unlinking any payload. Empty, truncated,
unknown-version and otherwise malformed markers are corruption, not deletion
permission. A failed live reclamation quarantines the owner and retains its
capacity; reopening still refuses the malformed marker. This is an integrity
check within the private-root trust boundary, not a new guest release authority.
Valid interrupted removals remain recoverable: the marker survives until all
payload/record unlinks have synchronized, and an empty directory can then retire.

`LocalReferenceInventory` and each returned `LocalReferencePage` reserve metadata
in the same `maximum_metadata_bytes` ceiling used by objects, stages and readers.
A cursor reserves 2 KiB; a page reserves 2 KiB plus 2 KiB per requested entry,
before copying, even when the page is empty or tenant filtering returns fewer
entries. These are conservative accounting bounds, not allocator measurements.
A cursor is refused when it cannot leave room for even a one-entry page at
admission. A smaller page can fit when a larger request is refused.

Dropping a cursor does not refund its retained pages. Each page keeps its original
reservation through completion, owner closure and transfer to another caller;
only actual Drop refunds it. Failed or unwound page construction refunds that
page's reservation without advancing the cursor. Work-slot and metadata limits
remain independent, and neither inventory nor a zero-owner observation grants
orphan-deletion authority.

## Durable payload integration

`open_durable` binds the actual `EmbeddedStore`; `open_durable_for_view` binds its
coherent view. A persisted durable-mode label alone cannot mint a pin. An ordinary
opener preserves that release fence; a trusted host may bind an existing mode
through `bind_existing_durable_for_view` only before sharing the owner and after
checking the exact engine identity and provider configuration. A trusted host
can instead use `enable_durable_for_view` to persist the mode on the same unique
owner. Live readers or shared ownership refuse the transition; an uncertain
mode write poisons that owner until the on-disk state is reopened and checked.

`capture_reference` performs the existing authorized open on the original
capability session and returns an affine `CapturedLocalPayload`. Its session,
provider, tenant, store binding, verified bytes and native reader travel together.
An encoded reference or digest cannot reconstruct this owner.

`RequiredBlobInventory` walks a coherent required-owner catalogue in bounded
pages, retaining the original local owner, snapshot identity and local mutation
generation. Its cursor consumes one work slot and 2 KiB of metadata. Each page
reserves conservative scratch before reading any state row: twice its requested
encoded-byte limit, 4 KiB per requested row and 16 KiB of fixed scratch. Native
readers keep their separate handle charge and use a second work slot. A store
with fewer than two work slots or insufficient one-row headroom refuses cursor
admission rather than retaining a cursor that cannot progress.

`begin_with_checkpoint` checks the original admission before and after cursor
construction. Publication, release or physical reclamation invalidates an active
walk; even an empty final page must recheck the local generation, owner, live
snapshot and caller checkpoint. Any failed or panicking page, including capacity
refusal, makes this required-blob cursor terminal. Its scratch retires on return
or unwind; cursor ownership stays charged until actual cursor destruction.
Restart with a fresh cursor and a suitable page size, never a replacement callback
on an invalid cursor. This is stricter than the descriptive local inventory's
unadvanced capacity-retry behavior.

`LocalReferenceAudit` separately reserves 16 KiB for transient state-index
verification. Returned pages retain only their own reference/disposition charge,
not the retired scratch. The host still owns semantic closure validation,
startup capacity/deadline checks and the final readiness decision. These
inventories are observations, not deletion or read authority.
Release checks take a fresh matching engine view while retaining the original
publication guard; provisional pins prevent racing reclamation.

The [command envelope](../latent-commit/README.md) can attach verified local
payloads through its trusted library API. Standalone startup validates required
local payload rows against the matching configured owner and rejects unsupported
or corrupt references. Guest reference attachment is not yet wired to that
envelope. S3 has no constructor for these local custody types. State, snapshot,
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

All `local::` tests, including the
[required-inventory cases](src/local/durable/required/tests.rs),
[write-unwind cases](src/local/write/tests.rs),
[release recovery cases](src/local/recovery/tests.rs) and
[inventory accounting cases](src/local/inventory/tests.rs), are selected by
`tools/qualify_local_payload_recovery.py` before its actual committed-payload
producer and protected-startup consumer. This focused lane rejects zero-match
Cargo success without freezing a test count or name inventory. Its Python
protocol tests exercise output checks and process-result handling, not native
storage behavior or proof of child retirement.

## Related documentation

- [Blob architecture](../../docs/architecture/blob-model.md)
- [Local immutable blobs](../../docs/runtime/local-blobs.md)
- [Atomic command envelope](../../docs/development/atomic-command-envelope.md)
- [Protected state owner](../../docs/development/shared-state-store-owner.md)
- [Workspace package index](../README.md)
