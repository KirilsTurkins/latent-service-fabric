# ADR-0033: Use scoped durable local blobs with owned chunks

- **Status:** Accepted
- **Date:** 2026-09-14
- **Delivery:** [#213](https://github.com/KirilsTurkins/latent-service-fabric/issues/213)
- **Extends:** [ADR-0031](0031-version-host-abi-recognition-independently-of-provider-authority.md) and [ADR-0032](0032-use-bounded-owned-resources-for-streaming-http.md)

## Context

Large immutable values need explicit storage authority, durable publication and
finite staging, file and memory ownership. An artifact cache key grants no
storage permission. A returned byte list alone cannot retain the original
provider charge through a guest's use of an incremental range.

## Decision

Select `lsf-host-abi-phase3-v4` as the current generic profile, preserving all
V1/V2/V3 sources and identities. Add exactly `latent:blob/blob@0.2.0` with
freestanding async calls, activation-local numeric reader/writer handles and an
owned chunk resource. This supersedes ADR-0032's current-profile selection and
extends its exact resource whitelist only to that interface. Application exports
remain bounded values; arbitrary resources and WASI filesystem imports remain
unsupported. See the [local blob contract](../docs/runtime/local-blobs.md).

Use a configured Linux root with descriptor-relative no-follow access, private
ownership and bounded inventory. Reserve the expected or maximum object size
before staging. Writes are sequential. Seal verifies size and digest, syncs the
payload and record, atomically renames the stage and syncs both parents before
returning a reference. A post-publication error is uncertain and requires owner
reconciliation; cancellation is not rollback or permission to replay.

Scope each reference to the configured namespace and original trusted tenant.
Every new physical capability operation rechecks current authority through its
original session. Matching bytes or a public digest cannot cross tenant scope.
Read pins and durable references separately prevent reclamation. Only explicit
trusted retention control releases a committed reference. Bounded reclamation
removes abandoned stages and released, unpinned objects; guest handle Drop does
no deletion or fsync.

Move actual file operations and hashing onto shared bounded blocking workers.
A cancelled response waiter requests stop but cannot refund a physical worker,
file, buffer or original activation. Prepay resident chunks and their single
canonical copy; retain charges until actual Drop. Cumulative read/write budgets
are independent of resident bytes and never reset when a chunk is dropped.

## Consequences

- Local immutable large-value storage is available through explicit trusted
  composition without deployment-owned threads, pools or listeners.
- Disk reservations include bounded sidecars even for empty blobs. Physical
  block/inode overhead still requires a suitable backing filesystem quota.
- A failed filesystem operation can require operator reconciliation or reopen;
  shutdown reports retained work instead of claiming an uninterruptible syscall
  was killed.
- Prepared/native identities change with V4, and node/compiler profiles remain
  paired. The legacy blob 0.1 contract is preserved but has no concrete binding.
- This adds no transactional keyed state, multi-object commit, durable outbox or
  replication. Those semantics retain their separate phase gates.
