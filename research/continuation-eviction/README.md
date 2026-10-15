# Continuation eviction

Investigate compiler-generated safe points that serialize logical program
counters and live locals when an async operation waits. Arbitrary native-stack
capture is excluded. The goal is to release the **complete guest Store** while
preserving durable workflow semantics.

**Status: source/literature review and experiment design only.** There is no LSF
continuation capture/restore compiler, durable workflow engine or measured eviction
result. This review runs no guest, checkpoint, crash or performance experiment.
[ADR-0016](../../adr/0016-keep-paging-continuation-eviction-and-fusion-optional.md)
keeps promotion optional and requires later decisions and conformance evidence.

Read the [primary-source/compiler review](upstream-review.md),
[proposed durable handoff](handoff-model.md) and
[evaluation plan](evaluation-plan.md). The website's
[continuation-eviction guide](../../docs/runtime/continuation-eviction-research.md)
explains current behavior and availability.

[Draft RFC-0006](../../rfcs/0006-durable-workflow-segments-and-continuation-handoff.md)
proposes the durable segment/handoff contract for review. It adopts no compiler
or runtime and leaves implementation/promotion evidence outstanding.

## Reviewed LSF source

Reviewed on 2026-10-15 against documentation-stack parent
[`f193fbe4af98778a0fd72d24832ed2f684d74407`](https://github.com/KirilsTurkins/latent-service-fabric/tree/f193fbe4af98778a0fd72d24832ed2f684d74407).
The workflow scaffold, executor outcomes, activation-runtime WIT and ADR-0028
also match the supplied development snapshot
[`90cf1f4c87ca24e9a64b077dc2eb501dcef22441`](https://github.com/KirilsTurkins/latent-service-fabric/tree/90cf1f4c87ca24e9a64b077dc2eb501dcef22441).
This stack selects Wasmtime 48.0.6; that development snapshot selects 48.0.5.
Engine identities and qualification evidence are not interchangeable.

| Existing element | What it establishes and what remains missing |
| --- | --- |
| [Workflow interfaces](../../crates/latent-workflows/src/lib.rs) | `Continuation` records definition digest, logical program counter, locals, wait, state version and attempt. `WorkflowTransition` groups state/effect/output descriptions. The crate has only this source file, with no storage or runtime implementation. These signatures establish no atomic checkpoint, ownership fence or durable wake protocol. |
| [Execution outcomes and cleanup](../../crates/latent-executor/src/lib.rs) | `GuestOutcome` has returns, declared errors, traps and interruption, with no durable suspension outcome. `ExecutionCleanup` separately proves reusable cleanup or quarantine. Serializing state would not supply that proof. |
| [Activation-runtime WIT](../../wit/platform/activation-runtime/package.wit) | Tokens are Store-local owners, timers are invocation-local and wakes require the original generation. A `continuation` parameter is not a persistent workflow handle. |
| [Async ownership decision](../../adr/0028-retain-activation-ownership-across-asynchronous-waits.md) | Ordinary waits retain the Store, cell, admission, budget, cancellation identity and relevant provider/descendant owners. Yielding releases poller time only; the public lifecycle remains `Running`. |
| [State/effect architecture](../../docs/architecture/state-and-effects.md) | Current command/outbox/outcome recovery provides relevant patterns, not a continuation engine. [Phase 6](../../docs/roadmap.md#phase-6-durable-workflows) explicit workflows and Phase 7 compiler eviction remain separate planned work. |

## What changes representation

An illustrative compiler frontend could lower:

```text
order = validate(request)
approval = await durableApproval(order.id)
return finalize(order, approval)
```

into an exact definition/schema, a logical resume label, the reachable live state
and an original durable wait identity. This is not an available LSF API.
The target suspended form is durable records plus bounded shared metadata, with
no retained guest Store, heap, native stack or leased execution cell.

Saving one local does not imply a small checkpoint: it may reference a large
cyclic object graph. The compiler must identify the transitive live state and
preserve aliasing, initialization, handlers and language-specific cleanup.
Capturable control state does not automatically make that graph serializable.

| Mechanism | Distinction from this track |
| --- | --- |
| Async host wait or language fiber | Suspends scheduling while retaining activation state and physical owners. |
| Wasm stack switching | Supplies typed live control transfer; a one-shot continuation is not durable exclusive ownership after restart. |
| Wasmtime compiled-component serialization | Saves prepared code, not an executing Store or its external resources. |
| Replay-based orchestration | Reconstructs state by executing code against recorded history, with its own deterministic-command contract. |
| Compiler-generated durable continuation | Saves an approved logical control/data representation and later reconstructs it in a fresh environment. This is the charter's target. |

The [source review](upstream-review.md) gives primary evidence and limitations for
these mechanisms. No current backend switch supplies persistent continuation
serialization.

## Keep two execution contracts separate

Evicting memory within one ordinary invocation would preserve its original
deadline, identity, conserved budget and outstanding obligations. Dropping its
future and starting another activation is not a safe transfer. ADR-0028 requires
an affine, bounded transfer severing every Store/cell/guest-memory reference and
retaining charges until actual retirement. Restoration guarantees may themselves
require reserved capacity; freeing bytes does not refund every reservation.

Durable workflows instead span separately admitted finite execution segments.
They need persistent cancellation, workflow-wide limits and explicit timers,
waits and effect identities. A segment boundary cannot silently reset an ordinary
request's fuel or extend its deadline. The recommended first step is an explicit
durable state-machine reference, followed by one compiler frontend targeting the
same [handoff protocol](handoff-model.md). Arbitrary in-flight provider waits are
a separate, harder investigation.

## Required guarantees and portability

Persistence, readiness, exclusive resume and physical cleanup are independent
facts. A committed checkpoint cannot allow another segment to start while its
old owner can still act. Early/duplicate events, cancellation and stale workers
must be resolved against the original workflow generation and wait, without
lost wakeups or duplicate committed transitions. External-effect uncertainty
remains independent; leases and checkpoints do not make remote work exactly once.

Saved bytes cannot recreate broker sessions, Store-local tokens, credentials,
transaction handles or historical grants. Restore must use current host-derived
authority and a bounded checked state decoder. Long-lived definitions and state
schemas need exact pins, explicit migration and retention; a continuation is
recovery data, not a disposable compiled-code cache entry.

One supported language/task/value profile is a useful first scope. A scheduling
safe point or one SDK's async lowering does not qualify the other SDKs, concurrent
tasks, arbitrary dependencies or native frames. Exceptions, `finally`, destructors,
GC roots, closures, monitors, TLS and callbacks need separate evidence. Complete
eviction requires coordinated task quiescence or explicit restrictions.

The [state-pager track](../userfault-pager/README.md) concerns explicit persistent
state materialization; it does not serialize arbitrary unfinished computation.
[Fusion](../call-graph-fusion/README.md) and alternative
[native](../native-sfi/README.md)/[hardware](../hardware-capabilities/README.md)
isolation do not supply durable handoff semantics. Promotion must preserve the
portable core and pass the research policy's semantics, security, portability,
benchmark and ADR gates.
