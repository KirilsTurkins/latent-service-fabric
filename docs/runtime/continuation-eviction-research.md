# Continuation-eviction research

Continuation eviction investigates saving an unfinished computation at approved
compiler-generated boundaries, destroying its complete guest Store, then restoring
logical state in a fresh execution environment. The target is resumption at that
saved position; crash recovery may still repeat an uncommitted segment.
**LSF has no implemented continuation capture/restore
compiler or durable workflow engine.** This remains optional research.

## Current waits retain their owners

[Asynchronous host I/O](async-host-io.md) yields shared execution time while retaining
the activation's Store, cell, budget, deadline and outstanding resource owners,
as required by
[ADR-0028](../../adr/0028-retain-activation-ownership-across-asynchronous-waits.md).
[Activation-runtime](activation-runtime.md) `park`/`wake` tokens and timers are
Store-local, not persistent workflow handles. Language fibers and Wasm stack
switching do not themselves provide durable serialization.

The [workflow crate](../../crates/latent-workflows/src/lib.rs) defines continuation
and transition interfaces only. Current execution outcomes expose no durable
suspension result. [Prepared Wasmtime code](trusted-aot.md) can be reused without
retaining an instance, but its serialization is not a live Store checkpoint.

[Phase 6](../roadmap.md#phase-6-durable-workflows) explicit state machines and
durable workflows remain planned, separately from Phase 7 compiler-eviction
promotion. Reclaiming memory within one ordinary invocation would instead need
to preserve its original deadline and conserved budget under a new safe-transfer
contract; it cannot silently become a long-lived workflow.

## Research direction

Start with an explicit durable transition reference, then one compiler frontend
with one task and bounded serializable state. Saving locals is insufficient:
reachable graphs, handlers, globals and host resources need declared treatment.
No raw native-stack capture or universal library-`await` persistence is proposed.

The [research overview](../../research/continuation-eviction/README.md) links
[primary compiler and workflow evidence](../../research/continuation-eviction/upstream-review.md),
including capture versus replay. The
[proposed handoff](../../research/continuation-eviction/handoff-model.md) separates
durable checkpoint commitment, event readiness, old-Store retirement and fresh
resume admission. It covers lost/duplicate wakeups, stale owners, cancellation,
current authority, effect uncertainty, budgets, clocks, versions and retention.

The [evaluation plan](../../research/continuation-eviction/evaluation-plan.md)
requires destroying the original Store, reusing its cell for unrelated work and
restoring from recorded state, including a process-restart variant. Checkpoint
and restore peaks, instrumentation costs, storage and wakeup pressure belong in
the comparison. No new experiment or measured LSF benefit accompanies this review.
