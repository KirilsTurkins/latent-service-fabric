# Phase 0 fixed execution-cell pool

Issue #20 introduces one node-owned `FixedCellPool` implementation for the Phase 0 spike. The pool is deliberately narrower than a production scheduler: one configured `CellClass`, one fixed capacity established at construction, FIFO admission, and a bounded wait queue.

## Resource model

Each idle slot contains only a stable `CellId` and a reuse generation. It does not contain a capsule, service, release, tenant, activation, Wasmtime engine, store, linear memory, listener, connection, queue, or operating-system thread. Capsule compilation, loading, and registration therefore cannot change pool capacity.

Queued acquisition and deadline handling use the repository's shared Tokio runtime. The pool creates no runtime, worker, listener, service process, or per-cell task of its own.

The spike harness can read a constant-time `CellPoolSnapshot` containing:

- configured capacity;
- currently available slots;
- bounded queue depth;
- active lease count; and
- quarantined slot count.

For the configured class, every stable state maintains:

```text
available + active_leases + quarantined = capacity
```

## Open pool seam and affine leases

`CellPool` remains an open architectural seam. Its original `acquire`, `release`, `capacity`, and `available` methods remain required. The Phase 0 `cancel_waiting`, `quarantine`, and `observations` additions have conservative defaults, so an independent implementation does not become source-broken merely because it does not yet expose those extensions.

`CellLease` is intentionally no longer cloneable, and external implementations now use `CellLease::new` instead of a struct literal because the lifecycle control remains hidden. These are explicit source-level compatibility changes: duplicate lease values and uncontrolled lease construction are incompatible with exactly-once release or quarantine. They do not seal the `CellPool` trait.

Independent pool implementations mint affine leases through `CellLease::new` and retain the matching `Arc<dyn CellLeaseLifecycle>`. After atomically recording a successful release or quarantine, the implementation calls `CellLease::disarm_lifecycle` with that exact capability. A consumer cannot disarm a lease without possessing the issuer-retained `Arc`. Dropping an armed lease invokes `on_abandoned`; an implementation should conservatively quarantine or otherwise remove that slot from reusable capacity.

`FixedCellPool` uses an internal lifecycle implementation containing the hidden lease token, generation, tenant, and pool identity. External implementations do not depend on those internals.

## Waiting and cancellation

When no slot is available, acquisition enters a bounded FIFO queue. A full queue rejects new work with `resource-exhausted`. An activation deadline is checked before admission and while queued. Explicit cancellation, future drop, and deadline expiry remove the waiter so it cannot receive a later lease.

Lease handoff uses an unaccepted-grant guard. If a task disappears after the pool reserves a cell but before the task accepts the lease, the guard returns the slot without exposing it to another activation concurrently.

The pool receives a wall-clock abstraction at construction. Production uses `SystemTime`; tests inject a manual wall clock and advance it together with Tokio's paused timer. Deadline tests therefore do not mix virtual timer progress with unrelated real wall time.

## Lease disposition

A successful acquisition has exactly three terminal paths:

1. `CellPool::release` returns the generic slot after successful backend cleanup;
2. `CellPool::quarantine` removes it from reusable capacity when cleanup cannot prove safe reuse; or
3. dropping a live lease conservatively quarantines the slot.

Release validates the pool owner and immutable lease identity recorded by `ActivationId`, cell, node, class, generation, tenant, budget, expiry, and internal lease token. A stale, forged, duplicated, or cross-pool return cannot increase available capacity.

Sequence exhaustion is fail-closed. If the internal lease-token sequence is exhausted, the affected cell is quarantined and every queued acquisition is failed instead of leaving requests stranded behind apparently available capacity.

Quarantine is intentionally one-way in Phase 0. Repair, replacement, multiple classes, fairness, priorities, autoscaling, and cluster placement remain later work.

## Validation

The scheduler tests exercise fixed capacity under concurrency, queue overflow, duplicate activation rejection, explicit cancellation, deterministic deadline expiry, release handoff, queued-future drop before release, lease drop, explicit quarantine, identity mismatch, duplicate return, token exhaustion, and barrier-controlled multi-threaded release/cancellation and release/task-abort races. An integration test implements `CellPool` outside the library module, mints leases through the public lifecycle capability, and verifies explicit release and abandonment.

From a clean checkout with the pinned toolchain:

```bash
cargo fmt --all --check
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked
cargo test -p latent-scheduler --all-targets --locked
cargo test --workspace --all-targets --locked
```
