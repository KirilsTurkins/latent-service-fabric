# Durable bounded local immutable blobs

`latent-blobs` implements the Linux `linux-immutable-blobs-v1` provider for
`latent:blob/blob@0.2.0`. The [V4 host profile](host-abi-profile.md) and
[ADR-0033](../../adr/0033-use-scoped-durable-local-blobs-with-owned-chunks.md)
select its exact async ABI. The legacy 0.1 interface remains recognized without
an installed provider. This is Phase 3 immutable large-value storage, with no
transactional key-value state, multi-object transactions, outbox or replication.

## Installation and authority

A trusted embedding opens one `LocalBlobStore` with an absolute root, namespace
and `LocalBlobLimits`. It installs a `LocalBlobProvider` on the node's existing
`ProviderPools` and registers it through
`ActivationCapabilityRuntime::install_blobs`. Installation creates no runtime,
listener or deployment-owned pool. Standalone provider configuration and
management retain their separate Phase 3 delivery scope.

The root must be private to the effective service UID (0700 directories, 0600
files), with trusted ancestors. Root-owned sticky temporary directories are
allowed. Paths are at most 4096 bytes and 64 components. Relative paths, traversal,
symlinks, hard-linked files, unsafe ownership and unexpected file types fail.
Descendant operations use retained directory descriptors with no-follow access
and verify path/inode continuity. Guest strings never select filesystem paths.
An exclusive root lock remains held while any real file/work owner survives.
Processes with the service UID or root remain inside this filesystem trust
boundary; the store is not a defense against a compromised node administrator.

Provider configuration identity binds the root's device/inode, namespace and
limits. Policy binds that exact provider epoch and namespace. The original
sealed session supplies tenant, publication, deadline and budgets. Each accepted
create/open/write/read/seal dispatch checks current authority after queueing.
Retained handles cannot substitute a new session or reuse revoked grants.

A guest reference contains SHA-256 digest, size and media type. The store's key
also includes trusted tenant and namespace. Possessing a digest is insufficient
for another tenant to open it. Equal content may be published independently by
two tenants; one tenant's retention decisions cannot remove the other's object.
This provider does not implement cross-tenant payload deduplication.

## Guest lifecycle

| Operation | Contract |
| --- | --- |
| `create(media-type, expected-size)` | Reserve the exact expected size, or the configured maximum when omitted, before opening a stage. Empty values are supported. |
| `write(handle, offset, bytes)` | Offset must equal bytes written so far. Gaps, overlaps, arithmetic overflow and overlarge chunks fail before I/O. No retry of a partially written stage. |
| `seal(handle)` | Consume the writer on every outcome, require the expected size if supplied, verify the complete payload and publish durably. |
| `open(reference)` | Resolve only the original tenant's exact live reference, pin it and verify payload digest/size and file identity. |
| `read(handle, offset, length)` | Read an exact checked range, including zero bytes at EOF, into one prepaid owned chunk. Short or corrupt reads fail. |
| `chunk-bytes(borrow<chunk>)` | Materialize bytes once. A second attempt returns `invalid-state`; keep the chunk until the bytes have been delivered. |
| `close(handle)` / chunk Drop | Close the activation's actual handle or free the chunk. This does not release a committed durable reference. |

The fresh Store has at most 64 reader/writer/chunk slots. Numeric tokens are
checked for Store, kind and nonreused process generation; exhausted generations
fail closed. Forged, foreign, closed, busy or wrong-kind tokens fail. Seal
consumes its numeric token. Trap/cancellation drops table owners while physical
workers retain their own file and accounting owners until they finish.

## Independent limits and execution ownership

| Local owner limit | Default |
| --- | --- |
| Objects / maximum payload per object | 4096 / 16 MiB |
| Accounted disk bytes | 1 GiB |
| Stages / total reserved stage payload | 16 / 128 MiB |
| Open local handles | 128 |
| Retained metadata allowance | 16 MiB |
| Maximum chunk | 64 KiB |
| Concurrent local operations | 16 |

Limits are validated before opening the root. `accounted_disk_bytes` includes
published payload, reserved stage payload, 4096 bytes for root records and 8256
bytes per stage/object for sidecars and a release marker. Empty blobs therefore
consume disk allowance. `resident_disk_bytes` reports published payload only.
This is an upper bound on regular-file logical bytes, not allocated filesystem
blocks, directory indexes or journal space. Entry counts bound that additional
exposure; use a backing filesystem quota for a hard physical disk ceiling.

Shared I/O and provider limits independently bound queues, wait age, running
requests, blocking jobs, buffers, results and protocol metadata. Each accepted
file job prepays a 16 KiB hashing/record workspace. Metadata and handles retain
separate conservative charges. Every requested read/write byte consumes the
activation's cumulative blob budget; dropping bytes does not refund it. Empty
operations still consume host work and finite call capacity.

Reads prepay both the resident buffer and one canonical copy. A delivered chunk
keeps the original pool/session owner until Drop. Closing its reader releases
the file pin independently; copied bytes can remain charged after the file is
reclaimed. Seal's bounded reference result retains its lowering owner through
Store destruction. Excessive retained results can exhaust finite pool capacity.

Filesystem syscalls and full-payload hashing run on existing shared blocking
workers, never on the guest's async runtime thread. The cancellable waiter
requests stop and returns promptly when it can, while the actual worker retains
its charges. Ordinary filesystem syscalls cannot always be interrupted;
shutdown must report outstanding work until it really retires. This profile
requires a local filesystem with working advisory locks, exclusive creation,
atomic no-replace rename and file/directory fsync semantics. Network filesystems
and power-loss behavior are not qualified by the unit tests.

## Durability, recovery and retention

Seal syncs the data, verifies its complete SHA-256 and size, writes/syncs the
immutable reference, atomically renames the stage and syncs both objects and
staging directories. Only then does it return a durable reference. After rename,
an accepted worker finishes that boundary even if the waiter cancels. A lost
response cannot prove publication failed. There is no automatic replay.

An uncertain mutation poisons the shared owner and retains conservative charges.
After actual workers and handles retire, close/reopen reconciles the bounded
physical inventory and re-establishes directory durability. Published records
must match their scope, key, size and complete digest. Incomplete stages are
abandoned, never resumed, and reserve their observed payload on recovery.
Unknown files, corrupt live records and unsafe replacements are preserved and
reject opening; they are not recursively deleted or silently repaired. An
interrupted initial owner-record creation can require operator reconciliation.

Equal live references converge under serialized publication. A concurrent seal
can reject with `unavailable`; its consumed writer becomes abandoned. A duplicate
stage remains charged until explicit reclamation. This does not authorize hidden
retries of uncertain operations.

Trusted retention control calls `release_reference(tenant, reference)` only when
the application no longer needs that committed reference. It records and syncs
a release marker. New readers are rejected at that cutover; existing pins may
finish. `reclaim(1..64)` removes only released unpinned objects and inactive
stages, syncing deletion before refunding charges. It preserves unknown entries.
Interrupted unlink/sync retains charges and requires reopen reconciliation.
Guest Drop performs no unlink or fsync, and there is no automatic GC task.

## Validation

Run on Linux:

```sh
cargo test -p latent-blobs --lib --locked
cargo test -p latent-capabilities --lib --locked
cargo test -p latent-wasmtime --test local_blobs --locked
```

The [maintained guest fixture](../../examples/local-blobs/README.md) executes
real canonical async imports with a fresh Store. Coverage includes empty/ranged
values, exact byte budgets, stale and wrong-kind handles, tenant separation,
revocation, independent file/chunk ownership, duplicate publication, private
roots, unknown/replaced/corrupt/missing files, finite capacities, interrupted
publication/reclamation and shutdown/reopen. Deterministic fault injection tests
syscall failure handling; barriers pause an actual file owner after its write
and verify retained cancellation charges. Shared worker tests separately verify
a dropped waiter cannot refund a blocked physical job. These are bounded
correctness tests, not a storage throughput or hardware power-loss benchmark.
