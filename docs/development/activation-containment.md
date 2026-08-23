# Phase 0 activation containment

This document defines the failure, cancellation, deadline, and cleanup contract implemented by the Phase 0 activation runner and Wasmtime Component Model backend.

## Ownership boundary

`Phase0ActivationRunner` is the orchestration boundary between `CellPool` and `ExecutionBackend`.

For every activation it owns:

1. one cancellation registration;
2. at most one affine `CellLease`;
3. one contained backend invocation; and
4. exactly one terminal cell disposition: release or quarantine.

The Wasmtime backend owns all invocation-local runtime state: the component instance, store, host state, temporary input buffer, live cancellation probe, limiter state, and invocation log buffer. Prepared component state remains in the existing bounded node-owned cache and is not activation-local.

## Ordering

The normal ordering is:

1. Register cancellation before queueing.
2. Derive the effective deadline as the earlier of the envelope and budget deadlines.
3. Acquire a cell while observing cancellation and the deadline.
4. Build the execution request from the granted lease.
5. Invoke the backend through `invoke_contained`.
6. Drop the guest instance, Wasmtime store, host state, temporary buffers, and cancellation probe.
7. Publish bounded logs.
8. Return an explicit cleanup proof.
9. Release the lease only for `ExecutionCleanup::Reusable`; otherwise quarantine it.
10. Remove the cancellation registration.

A backend that implements only the legacy `invoke` method receives the conservative default cleanup result and its lease is quarantined. Safe reuse must be proved explicitly.

## Race precedence

The runner and backend use deterministic precedence rules.

### Before execution

The queue wait uses a biased selection order:

1. cancellation;
2. effective deadline;
3. cell grant.

If cancellation or the deadline wins, the acquisition future is dropped before the runner asks the pool to remove the waiter. A lease received at the boundary is checked again before execution and is released without invoking the guest when cancellation or expiry is already visible.

### During execution

Wasmtime epoch callbacks record the first observed stop cause in a sticky atomic state. Each checkpoint evaluates cancellation before the monotonic deadline. Therefore cancellation wins only when both conditions first become visible at the same checkpoint; an already-recorded cause never changes.

When no cancellation or deadline cause was recorded, runtime failures are classified in this order:

1. aggregate linear-memory denial;
2. fuel exhaustion;
3. a stable Wasmtime trap category;
4. a bounded generic guest runtime error.

Engine construction, preparation, request validation, and other host-side failures remain typed `PlatformError` values.

## Stable activation mapping

| Execution result | Activation terminal state | Error code/detail |
| --- | --- | --- |
| Guest return | `Succeeded` | output and consumption preserved |
| Guest trap | `GuestTrap` | `GuestTrap` / `activation.guest-trap` |
| Cancellation | `Cancelled` | `Cancelled` / `activation.cancelled` |
| Deadline | `DeadlineExceeded` | `DeadlineExceeded` / `activation.deadline-exceeded` |
| Fuel exhaustion | `ResourceExhausted` | `ResourceExhausted` / `activation.fuel-exhausted` |
| Memory exhaustion | `ResourceExhausted` | `ResourceExhausted` / `activation.memory-exhausted` |
| Engine or platform failure | mapped from `PlatformErrorCode` | sanitized platform error |

Diagnostics are bounded before crossing the activation boundary: messages are limited to 512 bytes, detail kinds and names to 64 bytes, values to 256 bytes, eight details, and sixteen fields per detail. Guest backtraces and raw runtime context chains are not exposed.

## Runtime interruption

The backend enables Wasmtime fuel consumption and epoch interruption. A weak-engine ticker advances the epoch without keeping the engine alive. Each fresh store receives an epoch callback that checks the live cancellation probe and a monotonic deadline derived once from the Unix deadline.

Fuel, peak linear memory, wall time, and published log bytes are reported through `BudgetConsumption`. Every invocation receives a fresh store and host state, so failed activations cannot retain guest memory or host capability state for the next activation.

## Test fixtures and observations

The `containment-capsule` test component provides controlled modes for:

- a deterministic guest trap;
- an infinite non-cooperative loop; and
- repeated memory growth until the configured aggregate limit denies growth.

The Wasmtime integration test covers trap, fuel, deadline, running cancellation, memory exhaustion, repeated failures, a healthy echo after each failure class, and concurrent healthy calls. The runner tests additionally cover queued cancellation, exact lease disposition, conservative quarantine, bounded diagnostics, and repeated resource reclamation.

`ActivationRunnerSnapshot` and `RuntimeResourceSnapshot` expose constant-time counters used by the tests. A completed activation must leave zero live registrations, running invocations, stores, host states, temporary buffers, and cancellation probes. Pool observations must show no active lease or queued waiter unless the cell was intentionally quarantined.
