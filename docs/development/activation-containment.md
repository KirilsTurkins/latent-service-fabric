# Phase 0 activation containment

This document defines the failure, cancellation, deadline, completion, and cleanup contract implemented by the Phase 0 activation runner and the Wasmtime Component Model backend.

## Ownership boundary

`Phase0ActivationRunner` is the orchestration boundary between `CellPool` and `ExecutionBackend`. For every registered activation it owns:

1. one bounded cancellation registration;
2. at most one affine `CellLease`;
3. one contained backend invocation; and
4. exactly one attempted terminal cell disposition: release or quarantine.

The Wasmtime backend owns all invocation-local runtime state: the component instance, store, host state, temporary input buffer, live cancellation probe, limiter state, and invocation log buffer. Prepared component state remains in the bounded node-owned cache and is not activation-local.

## Cleanup ordering

The normal ordering is:

1. Register cancellation before queueing.
2. Derive the effective deadline as the earlier of the envelope and budget deadlines.
3. Acquire a cell while observing cancellation and the deadline.
4. Recheck cancellation and expiry after accepting the affine lease.
5. Build the execution request from the granted lease.
6. Invoke the backend through `invoke_contained`.
7. Drop the guest instance and its live-instance guard.
8. Drop the Wasmtime store and store guard.
9. Drop host state and its guard.
10. Drop temporary input buffers.
11. Drop the live cancellation probe.
12. Publish bounded logs.
13. Return the backend outcome together with an explicit cleanup proof.
14. Release the lease only for `ExecutionCleanup::Reusable`; otherwise quarantine it.
15. Remove the cancellation registration.

A backend that implements only the legacy `invoke` method receives the conservative default cleanup result and its lease is quarantined. Safe reuse must be proved explicitly.

## Race and error precedence

The runner and backend use the following deterministic precedence rules.

### Queue wait

The queue wait uses a biased selection order:

1. cancellation;
2. effective deadline;
3. cell grant.

If cancellation or the deadline wins, the acquisition future is dropped before the runner asks the pool to remove the waiter. A lease received at the same boundary is checked again before guest execution and is released without invoking the guest when cancellation or expiry is already visible.

### Guest-result handoff

After the backend returns but before its result is accepted, the runner checks:

1. cancellation;
2. effective deadline;
3. the backend outcome.

A cancellation already visible at handoff therefore overrides guest completion, fuel exhaustion, a trap, or a backend error. If cancellation is not visible but the deadline has elapsed, the deadline overrides that outcome. Otherwise the backend outcome is accepted.

The completion handoff is the activation-result linearization point. A cancellation that is accepted after this handoff but before registration removal does not retroactively replace an already accepted result. The registration-removal race therefore permits only linearizable outcomes: cancellation with an accepted cancel request, or the accepted guest result with either a late accepted cancel request or `NotFound` after registration removal.

### Wasmtime stop cause

Wasmtime epoch callbacks record the first observed stop cause in a sticky atomic state. Every checkpoint evaluates cancellation before the monotonic deadline. Cancellation therefore wins when both are first visible at the same checkpoint. Once a stop cause is recorded, later epoch observations cannot replace it.

When no cancellation or deadline cause is recorded, runtime failures are classified in this order:

1. aggregate linear-memory denial;
2. fuel exhaustion;
3. a stable Wasmtime trap category;
4. a bounded generic guest runtime error.

This gives the combined precedence:

`cancellation > deadline > memory > fuel > guest trap > generic runtime failure`.

### Cell disposition failure

Cell disposition occurs after the guest outcome has been mapped. A release or quarantine failure overrides that mapped guest outcome because the platform can no longer assert a safe terminal ownership state. The original `BudgetConsumption` is preserved. The exported error is deterministic:

- `PlatformErrorCode::Internal`;
- terminal state `PlatformFailed`;
- detail kind `cell-disposition.release-failed` or `cell-disposition.quarantine-failed`;
- bounded fields describing the sanitized underlying cause.

Dropping a still-live affine lease remains conservative: the pool quarantines it rather than silently returning it to reusable capacity.

## Stable activation mapping

Cancellation and deadline errors use shared constructors at every execution stage: before acquisition, while queued, immediately after grant, during guest execution, and at guest-result handoff. Their terminal state, code, detail kind, retryability, and bounded message shape do not depend on the stage that observed them.

| Execution result | Activation terminal state | Error code/detail |
| --- | --- | --- |
| Guest return | `Succeeded` | output and consumption preserved |
| Guest trap | `GuestTrap` | `GuestTrap` / `activation.guest-trap` |
| Cancellation | `Cancelled` | `Cancelled` / `activation.cancelled` |
| Deadline | `DeadlineExceeded` | `DeadlineExceeded` / `activation.deadline-exceeded` |
| Fuel exhaustion | `ResourceExhausted` | `ResourceExhausted` / `activation.fuel-exhausted` |
| Memory exhaustion | `ResourceExhausted` | `ResourceExhausted` / `activation.memory-exhausted` |
| Engine or platform failure | mapped from `PlatformErrorCode` | sanitized platform error |
| Release failure | `PlatformFailed` | `Internal` / `cell-disposition.release-failed` |
| Quarantine failure | `PlatformFailed` | `Internal` / `cell-disposition.quarantine-failed` |

Diagnostics are bounded before crossing the activation boundary: messages are limited to 512 bytes, detail kinds and names to 64 bytes, values to 256 bytes, eight details, and sixteen fields per detail. Cell identifiers are truncated to the same 256-byte value limit before entering error details or returned activation metadata. Raw payloads, secrets, guest backtraces, and unbounded Wasmtime context chains are not exposed.

## Runtime interruption and deadline tolerance

The backend enables Wasmtime fuel consumption and epoch interruption. A weak-engine ticker advances the epoch without keeping the engine alive. Each fresh store receives an epoch callback that checks the live cancellation probe and a monotonic deadline derived once from the Unix deadline.

The real infinite-loop acceptance test measures monotonic elapsed time around the invocation. Its upper bound is:

```text
requested deadline duration
+ epoch_tick_interval_millis × epoch_deadline_ticks
+ 500 ms documented CI scheduling allowance
```

The separate five-second timeout is only a deadlock watchdog and is not the acceptance tolerance.

Fuel, peak aggregate linear memory, wall time, and published log bytes are reported through `BudgetConsumption`. The memory fixture asserts that `peak_memory_bytes` never exceeds the granted memory budget. Every invocation receives a fresh store and host state, so failed activations cannot retain guest memory or host capability state for the next activation.

## Test fixtures and observations

The `containment-capsule` test component provides controlled modes for:

- a deterministic guest trap;
- a delayed deterministic trap used to prove mixed-workload overlap;
- an infinite non-cooperative loop;
- delayed healthy echo calls used to prove concurrent isolation; and
- repeated memory growth until the configured aggregate limit denies growth.

The real Component Model tests combine `Phase0WasmtimeBackend`, `Phase0ActivationRunner`, and `FixedCellPool`. They cover:

- deadline interruption within the configured tolerance;
- bounded isolated guest traps;
- fuel exhaustion;
- running cancellation;
- memory exhaustion with `peak_memory_bytes <= granted_memory_bytes`;
- a healthy echo immediately after every required failure class;
- healthy calls executing concurrently with an infinite activation reaching its deadline;
- healthy calls executing concurrently with another activation trapping;
- healthy calls executing concurrently with memory pressure;
- activation-local host context and logs;
- repeated failures with bounded prepared handles and zero live runtime resources; and
- exact pool accounting after every mixed workload.

Barrier-controlled runner integration tests cover cancellation before deadline before cell grant, cancellation and deadline versus guest completion at result handoff, cancellation accepted after handoff but before registration removal, and release/quarantine failure precedence with consumption preservation. Containment unit tests cover first-stop-cause stickiness and memory-before-fuel-before-trap classification.

`ActivationRunnerSnapshot` and `RuntimeResourceSnapshot` expose constant-time counters used by these tests. A completed workload must leave zero live registrations, running invocations, stores, host states, component instances, temporary buffers, and cancellation probes. Prepared cache entries and bytes must remain within configured limits. Pool observations must satisfy:

```text
available + active_leases + quarantined = capacity
queue_depth = 0
```
