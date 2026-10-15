# Continuation-eviction evaluation and promotion gates

This specifies future experiments; no compiler transform, workflow store,
checkpoint harness, failure campaign or benchmark was executed for this review.
Use the [source review](upstream-review.md) and
[handoff model](handoff-model.md), with the research policy and a later ADR.

## Bounded progression

1. Build an explicit state-machine reference with one durable timer/event,
   conditional transitions, durable cancellation and bounded ready claims. Prove
   restart, early-event delivery and stale-owner rejection without a retained
   guest. This establishes the substrate, not compiler capture.
2. Select one exact compiler/runtime profile and one logical task with bounded
   value state. Generate capture/resume code for nested calls and live locals.
   Keep the untransformed implementation and the explicit reference as controls.
   Unsupported state must reject before durable acceptance.
3. Destroy the original guest Store, release its cell only after affirmative
   cleanup, run unrelated work in that cell, then restore into a fresh Store.
   Repeat across process restart, with counters and artifact identities proving
   no hidden heap, native stack or original future remains.
4. Add supported object graphs, exceptions and effect intents incrementally.
   Concurrent tasks, ordinary in-flight provider waits and additional SDKs are
   separate extensions with their own semantic and cleanup proof.

Use disposable local storage and deterministic timer/event/effect doubles first.
An outer supervisor bounds/reaps a hung experiment; killing it is not proof of
successful inner eviction, recovery or node-safe cleanup. No live external
requests, production data or broad load campaign is implied by this plan.

## Compiler and language contract

Capture the logical label, exact code/schema and all live state needed to resume,
including transitive callers. Preserve aliases and cycles under finite limits.
List the handling of globals, GC roots, tables/reference values, closures, runtime
initialization and memory beyond the selected task. Native frames, host pointers,
Store tokens and opaque resources are not ordinary serialized locals.

Persistence-safe points require more than scheduler or GC safety. Test normal
returns, pending exceptions, `catch`/`finally`, constructors and language cleanup.
Capture/unwind must not perform business cleanup prematurely or swallow an
application error. Restore must not repeat an initializer or prefix effect merely
to rebuild a frame. Unsupported indirect/native/library paths need explicit
diagnostics; disabling a checkpoint silently is not a compatible implementation.

| Maintained profile | Additional qualification questions |
| --- | --- |
| Rust | Live borrows, owned graphs, captured future state, pinning and `Drop` behavior; no assumption that an arbitrary future implements a durable codec. |
| C | Pointer aliasing, interior pointers, allocations, globals and non-local control flow; no host-address persistence. |
| TypeScript | Closures, pending reactions, exception state and the activation-owned SpiderMonkey graph; no retained hidden engine heap. |
| Go | Coordinated goroutines, channels, shared state and runnable siblings; capturing one waiter cannot discard other work. |
| Java | TeaVM continuation arrays, GC roots, monitors, TLS and initialization; existing [activation fibers](../../docs/runtime/java-activation-fibers.md) keep state in the original accounted allocation and are not durable snapshots. |
| C#/.NET | Supported async state machines, referenced runtime objects, exception/disposal state and pending callbacks; no retained CLR or arbitrary Task serialization claim. |

These are investigations for the selected
[SDK/runtime profiles](../invocation-concurrency/languages.md), not support claims.
If another task can run or mutate captured data, coordinate and capture it or
reject that boundary. Whole-Store reclamation cannot be established by suspending
the root task alone.

## Failure and semantic matrix

Each row needs positive controls, a deliberate violation/failure schedule and
source-bound observations of durable disposition, actual host effects and physical
owners. A returned timeout, `Suspended` label or low RSS sample alone is insufficient.

| Boundary | Required evidence |
| --- | --- |
| Fresh restoration | Destroy Store A, execute unrelated B in the released cell, restore A in a new Store/process and obtain the reference result without repeating its committed prefix. |
| Compiler coverage | Nested/recursive calls, indirect calls and permitted library boundaries preserve live values and control position; unsupported paths fail explicitly. |
| State fidelity | Aliases/cycles, interior references, globals, closures, captured exceptions and initialized objects behave as declared. Enforce graph/depth/byte limits and reject corrupt/truncated state before effects. |
| Unwinding | Capture in supported handlers/finalizers/constructors preserves original exception/return/object identity; cleanup is neither premature nor duplicated. Exercise Asyncify catch limitations if that pass is selected. |
| Concurrent tasks | A sibling that remains runnable or owns mutable state prevents partial eviction unless coordinated capture is implemented. Hidden GC roots/host borrows cannot retain a retired Store. |
| Atomic checkpoint | Crash before/after payload durability and before/after the conditional checkpoint/wait/state/intent decision. Recovery yields the original committed result or declared unknown, never a missing committed payload or fabricated abort. |
| Commit versus cleanup | Crash or stall after checkpoint commit before Store retirement. Record readiness without starting a second active segment; cleanup failure retains charges/quarantine. |
| Wake delivery | Deliver before registration, during commit/cleanup, after claim and after terminal state; duplicate, reordered and overflowing messages follow the declared durable match/acknowledgement policy. |
| Stale workers | Lease expiry with an old worker still executing, duplicate ready claims and restarted owner identities cannot commit/dispatch as current. Live one-shot continuation checks are not a substitute. |
| Cancellation | Race cancel against commit, event readiness, restore admission and completion. Persistent cancellation prevents resurrection; accepted effects keep their original uncertainty/cleanup owners. |
| Authority | Forged tenant/PC/schema/metadata, copied Store tokens, revoked publication/provider/grant and a full required audit journal deny new execution or dispatch as required. Saved bytes never mint a session or ledger. |
| Budgets and clocks | Suspend/restart without resetting fuel/calls or extending the original invocation deadline. Crash after reserving an attempt and before reporting consumption; unknown work cannot become a refund. Exercise workflow lifetime/retry limits, wall rollback/jump, restart clock continuity and overflow. |
| Effects and transactions | Crash around intent commitment, dispatch and result recording; no blind replay of uncertain remote work. Reject ordinary provider futures and open transaction handles at unsupported capture boundaries. |
| Storage and pressure | Full/unavailable storage, oversized checkpoints, encode/decode overlap, queued restores, quarantine and wake storms stay bounded and fairly admitted. A failed eviction cannot falsely refund its old owners. |
| Versions and retention | Wrong definition/schema/engine, explicit migration failure, revocation, superseded payload GC, late signals and older-history restore follow declared recovery rules; no LRU deletion of required state. |

Retain source/artifact/configuration identities and raw schedules. Existing async,
transaction, generation-fencing and cleanup fixtures are starting points for these
tests, not evidence that a new continuation path passes.

## Benchmark protocol

Compare four clearly labeled cohorts: ordinary retained async wait; explicit
durable state machine; compiler-generated continuation; and, if investigated, a
replay frontend with its deterministic programming contract. Do not call the
explicit reference a completed compiler implementation or compare weaker effect,
authority, lifetime or cleanup guarantees as an equivalent speedup.

Vary wait duration, retained guest memory, reachable live state, graph complexity,
checkpoint size, definition/code-cache warmth, ready concurrency and code churn.
Include no-wait workloads to expose instrumentation regressions, small and large
live heaps, short provider-like waits and long timer/event waits. Keep external
latency controlled. A compiler stack buffer alone is not the complete state size.

Measure capture/encode, durable commit, old-owner retirement, ready-queue delay,
fresh admission, fetch/decode, Store creation and time to first resumed work.
Report end-to-end distributions with request counts, warmups, repetitions and
uncertainty; do not add phase p99 values. Track CPU, code size, storage bytes/I/O,
peak capture/restore overlap, retained host owners and memory-time actually freed.
Separate virtual reservations, guest-accounted memory, allocator retention and RSS:
destroying a Store does not guarantee an equal immediate RSS fall.

For a proposed policy, compare the benefit
`actually released memory * time evicted` against capture/storage/restore and
admission costs. This is a dimensional accounting aid, not an LSF measurement or
a universal threshold. Include storage write amplification, definition retention,
orphan staging collection and wake/restore bursts. Repeat matched work under mixed
tenant pressure only after the finite correctness experiment passes.

Select exact compiler/pass options, runtime/host ABI, component and continuation
schema digests, engine configuration, storage backend/durability and clock model.
Publish negative cases and a justified scope. Larger profiling/soak campaigns need
separate authorization; no scalability claim follows from a small correctness run.

## Promotion decision

Require an ADR defining supported durable boundaries, language/task/state scope,
actual durable transition owners, exclusive-resume/fencing rules, current authority,
effect uncertainty, cancellation, persistent clocks, workflow/segment accounting,
checkpoint secrecy/retention, code migration and storage/restore failure behavior.
Show full old-Store reclamation and fresh restore, including process-restart and
stale-owner schedules, before advertising eviction.

Same-invocation memory eviction needs its own ownership-transfer decision and
original-deadline proof. Keep explicit workflows useful without the compiler
optimization, preserve existing capsule semantics, and do not promote universal
`await` persistence or a required experimental production dependency by implication.
