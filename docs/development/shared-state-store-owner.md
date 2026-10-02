# Shared state store ownership

`latent_state::protected_store::ProtectedStoreOwner` owns one node database on
the [selected redb profile](../../adr/0061-select-redb-for-transactional-host-state.md).
It runs protected opening, engine verification, bounded logical-record validation,
ordinary storage jobs, snapshot retirement, the final flush and engine destruction
on the same fixed workers. A future poll does no engine or filesystem I/O.

The supported production constructor uses an existing absolute private Linux
x86-64 root on the operator-selected local ext4 profile. Anchored `statfs` must
report the ext-family discriminator; tmpfs, overlay and network filesystems are
rejected. This discriminator alone does not qualify another ext-family version,
mount policy or storage device. Windows runs exercise the portable owner and
engine substrate; they do not enable this protected production profile.

The root retains every ancestor descriptor, an exclusive private zero-byte
`transaction-owner.lock`, its mutable fence, and the engine fence. The root lock
prevents another owner from choosing a different database filename in the same
root. The upstream file backend also holds its database lock. Opening never
creates parent directories, follows links or truncates an existing file.
Permissions, inode identity and ancestor ownership are checked before and after
each storage job. The root lock stays owned until actual engine destruction.

## Readiness and formats

`start_validated(config, validator_retained_bytes, validator)` returns an owned
startup future. Readiness follows both engine-format verification and validation
of every logical record across all ten closed families. The callback borrows a
bounded key/value row on a fixed worker, must bound decode before allocation,
and must reject unsupported nonempty families. Validation uses one coherent
snapshot and continuation pages of at most 256 rows/4 MiB. It reserves 8 MiB of
scratch space before opening, in addition to captured configuration/codec bytes.
Dropping startup detaches it; accepted initialization keeps its captures and
physical owner until it returns and its engine actually closes.

The default `start` accepts an empty logical store only. Namespace, state,
command, result, outbox, inbox, payload and maintenance codecs belong to their
contract owners and must be registered by the node. Opaque rows never establish
production readiness. Malformed rows, unsupported schemas and engine corruption
fail closed without replacing existing bytes. The first supported engine format
is `latent.transaction-store.v1`; no earlier-format migration pair is supported.
Unknown formats require an explicit operator migration/restore plan. Startup
does not invent a migration, reset state or silently publish an intermediate
format.

## Finite ownership

`ProtectedStoreConfig::bounded_linux(root)` has these explicit bounds. Bootstrap
must select `create_if_missing` when initializing a new deployment; reopening
does not implicitly enable creation.

| Resource | Initial profile |
| --- | --- |
| Fixed workers | 3, each with an explicit 1 MiB stack |
| Active native reads/writes | 2 reads, 1 writer |
| Queued/accepted jobs and native resource reservations | 8 queued, 32 accepted |
| Retained job/result/native-resource bytes | 128 MiB, at most 40 MiB per job |
| Resident engine cache and baseline metadata reservation | 8 MiB + 64 KiB, until engine destruction |
| Engine cache | 8 MiB |
| Logical store | 16,384 rows, 32 MiB |
| Internal encoded keys/values | 4,096 bytes / 2 MiB |
| Checks/mutations per batch | 1,024 each, including atomic envelope records |
| Native read views | 8, 30-second logical lifetime |
| Physical database file | 256 MiB |

The internal record ceilings include namespace/entity framing and value metadata;
they do not change the guest's 1,024-byte key and 1 MiB value limits. Constructors
reject zero, inconsistent or excessive limits. The generic owner caps workers
at 32, queue slots at 4,096, accepted slots at 8,192 and retained bytes at 1 GiB.
The engine separately validates its absolute cache/row/value/view ceilings.

Admission charges declared captured input and possible result bytes plus actual
typed job/completion metadata before queue allocation. Atomic batches also charge
owned vector capacities and intermediate encoded-row space. Trusted host callback
captures/results must declare their full retained payload. Cache residence has a
separate charge; fixed worker stacks have their declared node resource bound.
These quotas account ownership at the storage boundary, not all process RSS.

The bounded file adapter delegates locking and native I/O to redb's upstream
`FileBackend`. It checks every extension and write offset before disk mutation,
refusing lengths beyond the configured ceiling. This is a physical file ceiling;
it is not a disk-free reservation or a power-loss guarantee. Physical quota/I/O
failure gates the owner and preserves the actual commit disposition.

## Worker ports and native views

`with_store(kind, retained_payload_bytes, operation)` runs trusted namespace or
command operations with a borrowed `&EmbeddedStore` on these workers. It returns
bounded owned metadata; an engine `Arc` or borrowed reference cannot escape.
Callbacks must use the correct read/write class, run no guest code, and return
no raw native read view. Engine batches/receipts and publication authority remain
the host contract owners' responsibility.

Guest transactions use `open_view` and `with_view`. `ProtectedStoreView` is affine
and has no native accessor. It retains one actual coherent `ReadView` between
guest calls. `with_view` consumes the host view and operation envelope, borrows
the native snapshot only on a fixed worker, and returns the view together with
the bounded result. The host session keeps logical observations/staging/cursors;
view identity binds those records to the original snapshot.

A view reserves bytes and a native retirement slot before opening. Its drop
queues destruction on the existing workers even after admission closes or the
owner quarantines. A live view keeps the database and last worker alive. Logical
view expiry does not release this physical pin. Foreign owners reject a view.
An admission failure consumes the passed view and schedules its retirement;
the operation never runs.

`apply_fenced` runs the host's short no-I/O authority/attempt/OCC acceptance fence
inside the real abortable writer. Engine conflict, validation and quota failures
remain technical failures. A successful flush followed by loss of the protected
file relationship returns `CommitUncertain`. Engine sync/commit failure likewise
gates later work; recovery must inspect the original command identity after
physical retirement/reopen. No failure grants permission to rerun a guest,
change its command key or report a business abort.

## Cancellation and shutdown

`reserve_operation` installs a bounded affine physical operation pin before
claiming durable work or starting provider I/O. It retains exclusive root
ownership through physical cleanup, without opening another native snapshot.
`ProtectedStoreOperation::retire` and `ProtectedStoreView::retire` return a
preallocated `StoreIoRetirement` receipt. The receipt becomes ready only after
the fixed worker finishes the actual destructor and releases physical ownership.
Command cleanup awaits native view/buffer retirement before retiring its own
operation pin and accepting prior-owner proof. Dropping a receipt detaches
observation without cancelling cleanup. Unexpected operation-pin drop
quarantines and preserves its bounded reservation/root until process loss.

The pin and receipt qualification passed all 73 state tests and strict Linux
all-target/all-feature Clippy. Deterministic schedules prove receipt readiness
waits through a paused destructor, detached waiters retain physical bytes, and
operation pins preserve the real root lock through deadline quarantine while
remaining able to retire after logical close.

Dropping a job waiter detaches its response. An accepted queued or active write
still runs once and keeps its buffers/reservation. Completed result memory stays
charged until delivered or actually destroyed. Native view destruction is always
deferred to the fixed workers. Worker panic gates queued operations as
`NotStarted` and retains uncertainty about the accepted physical operation.

`close` closes admission without blocking. `drain_async(deadline, wait)` permits
one bounded node waiter and uses the node's existing absolute clock/timer future.
Workers wake it on actual retirement. The finalizer runs once after jobs and
native views retire, performs an immediate flush barrier, and observes actual
backend close before publishing physical retirement. Clean drain additionally
requires all accepted result memory to retire and no failure/quarantine.

Deadline expiry reports sticky quarantine with live jobs/views/bytes intact.
It proves neither write abort nor engine closure. A later drain can observe
physical retirement while still reporting unclean. Dropping a drain waiter only
releases its waiter registration; the original shutdown deadline remains bound
and cannot be extended by another waiter. `reap_retired_threads` joins finished OS threads
without waiting for live workers. No per-tenant pool, timer, store or unbounded
blocking-task queue is created.

## Validation and node handoff

`start_validated_view(config, validator_retained_bytes, validator)` runs the
complete registry validator against one coherent borrowed `ReadView` on the
accepted initialization worker. It can check command/result/outbox/payload and
other cross-row links with bounded pages and point reads before Ready. The
validator declares captured memory, bounds temporary decode and page buffers,
and rejects unsupported formats or inconsistent links. It returns no native
view or engine handle. The physical view retires and protected root/lock fences
are checked before readiness. The row-codec port delegates its bounded family
walk to this same coherent path.

The additive view-validator qualification passed all 71 state tests and strict
all-target/all-feature Clippy on the same pinned Linux image. Its schedules pause
validation to prove readiness stays pending, exclusive root ownership persists,
and a one-view native cap is available only after validation retires. A broken
cross-family link rejects readiness while preserving every existing row.

The owner tests exercise actual worker pauses and resource destruction using
shared rendezvous/clock helpers. Production tests use the real protected root
and redb engine on a session-owned Docker Linux ext4 volume. They cover exclusive
root ownership, coherent snapshots/reopen, native view capacity and retirement,
malformed/unsupported records and formats, 300-row validation continuation,
permission and path substitution, real backend sync failure, physical file quota,
atomic original-command recovery and clean-versus-live/quarantined drain.

Measured on 2026-10-01: all 66 `latent-state` tests passed on the pinned Linux
Rust 1.97.1 image, and all 18 `latent-protected-files` cases passed, including the
explicit privileged ownership case. Strict all-target/all-feature Clippy passed
for both crates. The 53 portable state tests passed on Windows; Windows Clippy
uses the existing testkit's `unnecessary_wraps` allowance. Foundation, repository
and UTF-8 CI inventory checks also passed. The state CI inventory lists the 66
discovered test names rather than compiling the former placeholder.

The Linux image was
`sha256:0e2bcaef56d041a486784e54104a81aebe0da44bd03019bd70bc0401e42e4a97`.
Source and the Cargo registry were mounted read-only. The session-owned build
and ext4 fixture volumes were `latent-p4-store-io-target-20260930` and
`latent-p4-store-io-fixtures-20260930`; `LATENT_STATE_TEST_ROOT=/store` selects
that fixture instead of an unsupported container overlay/tmpfs directory.
The validation commands were:

```text
cargo clippy -p latent-state -p latent-protected-files --all-targets --all-features --locked --offline -- -D warnings
cargo test -p latent-state -p latent-protected-files --all-targets --all-features --locked --offline
cargo test -p latent-protected-files --locked --offline tests::unexpected_file_and_directory_owners_are_rejected -- --ignored
cargo test -p latent-state --lib --all-features --locked --offline -- --list
```

The node must retain this owner through its startup/readiness/drain lifecycle,
register the current family codecs, lift native `StoreError` out of logical
session errors, and use these ports for namespace, command and guest operations.
The shared owner is implemented here; standalone activation readiness, complete
command envelopes, retention/restore and six-language runtime conformance remain
their Phase 4 integration tickets. This document makes no packaged-node or
power-loss qualification claim.

The dispatcher obtains one `ProtectedStoreDispatcher` registration from this
same physical store. Cloned readiness handles cannot advance a new dispatch
epoch while that registration remains live. Its bounded physical slot and
protected root pin retire on a fixed storage worker only after provider work
and attempt pins have actually retired. An unexpected registration drop gates
the store and preserves its pin for recovery. This protects against overlapping
dispatcher startup without introducing another engine or process registry.
The actual Linux registration lifecycle test and all 74 state cases passed,
along with strict all-target/all-feature Clippy on the pinned image above.

Before a host moves a view through a cancellable read call, it may capture
`view.retirement_witness()`. One non-clone status witness is issued for the
entire affine view lifetime. `has_retired()` becomes true only after the native
destructor and physical reservation release, including a detached `with_view`
response. It uses the pre-reserved retirement signal and no waiter, so the
existing `retire()` receipt remains the single bounded future observer. The
generic paused-destructor test verifies this distinction; the real Linux test
drops an accepted paused read's response, closes admission, and proves the view
and root remain owned until actual fixed-worker retirement. All 75 state cases
and strict combined state/effects Clippy passed on the pinned Linux image.
