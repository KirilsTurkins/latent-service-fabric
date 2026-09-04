# Phase 1 resource budgets, deadlines, and cancellation

Issue [#6](https://github.com/KirilsTurkins/latent-service-fabric/issues/6)
implements the executable semantics behind the hardened contracts from issue
[#36](https://github.com/KirilsTurkins/latent-service-fabric/issues/36).

## Budget representation

`ResourceBudget` contains hard ceilings. Numeric zero is always an exact grant
of zero; it is never a default or an unlimited sentinel. The only optional
member is `wall_time_limit_millis`:

| Representation | Meaning |
| --- | --- |
| `None` / omitted | This layer contributes no relative wall-time ceiling. |
| `Some(0)` / `0` | The layer grants no wall time. Admission therefore observes an already-expired effective deadline. |
| Positive value | Relative wall time measured from the admission instant. |

Reusable capsule, deployment, and node data contains no absolute deadline.
Consequently, a persisted deployment cannot become invalid merely because wall
clock time passes. A caller absolute deadline remains invocation-scoped.

Phase 1 actively enforces:

- CPU fuel;
- peak linear memory;
- wall deadline; and
- host log bytes.

Child calls, outbound requests, state/blob bytes, and effects retain stable
counter fields for compatibility, but their Phase 1 effective grants and
terminal consumption are always zero. A caller request with non-zero capacity
for one of these dimensions is rejected as `invalid-argument`; a backend that
reports non-zero terminal consumption for one is treated as an internal
accounting failure.

## Effective grant

`EffectiveActivationBudget::admit_at` is the authoritative admission operation.
It validates the request and computes:

```text
effective dimension = min(request, deployment ceiling, node ceiling)

effective deadline = min(
    caller absolute deadline,
    admission wall time + effective relative wall-time ceiling
)
```

The absolute result is retained for API/context reporting. At the same admission
boundary, it is converted once to a `std::time::Instant`. Runtime expiry checks
thereafter use the monotonic value. An absolute deadline that has already
expired, or a duration that cannot be represented by the process monotonic
clock, is rejected before a wrapped activation manager is invoked.

`BudgetedActivationManager` is the node integration seam. It performs admission
before delegating to the wrapped manager, replaces the envelope budget/deadline
with the effective grant, installs activation-keyed accounting and cancellation
registrations, applies cancellation-over-deadline terminal precedence, freezes
terminal consumption, and removes both registrations when invocation handling
terminates.

## Accounting

`ActivationBudget` is cloneable, but every clone refers to one mutex-serialized
activation state. This gives the following invariants:

- checked addition prevents arithmetic overflow;
- a successful consume operation never exceeds the granted dimension;
- peak memory only moves upward and cannot exceed its ceiling;
- reservations consume capacity immediately;
- committing retains the reserved amount;
- explicit refund or drop refunds exactly once;
- finalization freezes a single terminal snapshot;
- repeated finalization returns the same snapshot; and
- mutation after finalization fails deterministically.

A backend terminal report is a total, not a delta. Reconciliation therefore
takes the maximum of direct observations and the backend report for each
Phase 1-enforced dimension. This prevents both double counting and a backend
report from erasing already-observed host consumption.

The activation budget registry exposes the same `ActivationBudget` by
`ActivationId` to Wasmtime and host-capability composition. This avoids ambient
or service-owned accounting objects and preserves the invariant that accounting
exists only while an activation is live.

## Exhaustion and terminal mapping

| Condition | `PlatformErrorCode` | Terminal state | Guest interruption |
| --- | --- | --- | --- |
| CPU fuel exhausted | `resource-exhausted` | `ResourceExhausted` | `FuelExhausted` |
| Peak memory exceeded | `resource-exhausted` | `ResourceExhausted` | `MemoryExhausted` |
| Wall deadline reached | `deadline-exceeded` | `DeadlineExceeded` | `DeadlineExceeded` |
| Log bytes exhausted | `resource-exhausted` or typed host-call budget error | `ResourceExhausted` if terminal | none; cooperative host-call failure |
| Explicit cancellation | `cancelled` | `Cancelled` | `Cancelled` |

Every budget error includes one bounded structured detail. Exhaustion details
identify the dimension, limit, already-consumed value, and attempted amount.
They contain no tenant or cross-activation data.

## Cancellation

`ActivationCancellationRegistry` owns node-local registrations keyed by
`ActivationId`. A registration yields:

- a read-only `CancellationToken`, which implements the executor cancellation
  interfaces and supports asynchronous notification;
- a cloneable `CancellationHandle` for trusted activation orchestration; and
- a non-cloneable registration guard that removes the registry entry on drop.

Cancellation is first-writer-wins. The first bounded reason is retained, later
requests are idempotently accepted, and the token observes the original reason.
Cancellation state is intentionally not durable and is removed when activation
handling terminates.

## Phase boundary

This implementation does not provide tenant billing, a distributed quota
ledger, cluster-wide budgets, durable cancellation, state/effect providers, or
parent-to-child budget delegation. The data model retains the corresponding
counter fields, while descendant delegation remains Phase 3 work.

## Validation

Fast deterministic coverage is part of the normal Rust workspace tests:

```bash
cargo test -p latent-core --all-targets --locked
cargo test -p latent-executor --all-targets --locked
cargo test -p latent-node --all-targets --locked
```

The tests cover deadline boundaries, reusable relative ceilings, deterministic
intersection properties, every Phase 1-enforced dimension, concurrent consume
races, reservation commit/refund/drop behavior, peak memory, exactly-once
finalization, cancellation races, reason propagation, registry cleanup, and
pre-delegation rejection.
