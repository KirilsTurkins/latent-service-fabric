# Activation lifecycle protocol

The current node uses one activation owner for stateless calls and the explicitly
installed command/query runtime. [Local activation lifecycle](../activation-lifecycle.md)
owns routing, admission, preparation, scheduling, execution, terminal status and
cleanup. [Host-owned commitment](commit-protocol.md) adds a separate durable
business disposition; it does not replace the ordinary status journal with a
single durable activation/effect state machine.

## Live phases and terminal status

Successful execution follows the current public path:

```text
Received -> Resolved -> Admitted -> Queued -> Materializing -> Running
```

Terminal state is separate from live phase. The final event repeats the last
phase and records Completed, Rejected, Cancelled, DeadlineExceeded,
ResourceExhausted, GuestTrap, StateConflict, DependencyFailed or PlatformFailed.
An ordinary declared guest error is a Completed activation with a distinct
outcome; durable business rejection has its own transaction disposition.

The [domain vocabulary](../../crates/latent-core/src/lifecycle.rs) also declares
Suspended, PreparingCommit, Committed and EffectsPending. Their presence in a
generated enum does not mean the installed node emits those phases or persists
workflow continuations. Provider/descendant waits remain Running and retain the
cell, Store, memory, budget and cancellation owner.

## Separate observations

| Surface | Meaning and retention |
| --- | --- |
| Activation status/events | Bounded node-local observation by activation ID; status absence is no proof the call never ran. |
| Original command/attempt/result | Durable identity and outcome in the protected engine, under current result-read authority; queried without rerunning a guest. |
| Effect/history | Original durable intent and separately owned dispatch attempts, acknowledgement, uncertainty or reconciliation. Command completion does not complete delivery. |
| Cleanup/retirement | Actual release or quarantine of physical execution/provider/native owners. A terminal reply is not reuse proof. |
| Fresh query | Bounded read-only view with its original namespace/history identity; no durable business-command/outbox obligation. |

The [transaction completion owner](../../crates/latent-node/src/transaction_runtime/completion.rs)
retains known durable commitment independently of response, audit or cleanup
failure. Possible commitment remains recovery-required under the original key.
Lookup uses the [transaction recovery protocol](../operations/transaction-recovery.md),
not a new activation ID or an inferred retry from a terminal status.

## Pinning and cancellation

Resolution pins exact publication/component, revision, route generation,
contract/function and execution policy. Queued/readiness pins are not acceptance
to start; current lifecycle/admission is checked again at the final start fence.
Provider operations and transaction completion have their own current decisions.
No authority fence is held across provider I/O or an await.

Cancellation acceptance registers a request; it does not prove cleanup or abort.
Cancellation winning before the transaction's final fence prevents commitment.
After irreversible I/O may have begun, timeout, transport loss or a dropped waiter
requires original-identity recovery. Charges stay with the actual work through
retirement. Only affirmative durable abort evidence and the explicit attempt
contract can authorize a deliberate technical-abort retry.

## Suspension and journal boundaries

An async wait releases the shared compute thread while retaining activation
ownership. Durable workflow suspension would persist an explicit continuation
and release the complete cell/guest Store; that remains Phase 6. The node does
not checkpoint or evict an ordinary active guest stack.

Activation event sequences are monotonic within the bounded status owner.
The optional [audit journal](../phase-2-audit.md), management receipts and durable
command/effect records have independent retention/loss contracts. The node does
not emit a mandatory durable audit event for every ordinary Invoke. Accepted
ADRs and declared phases do not qualify clustering or workflow execution.
