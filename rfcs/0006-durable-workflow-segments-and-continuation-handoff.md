# RFC-0006: Durable workflow segments and continuation handoff

- **Status:** Draft
- **Authors:** LSF project contributors
- **Created:** 2026-10-15
- **Target milestone:** Phase 6 durable workflows; Phase 7 compiler promotion

## Summary

Propose a durable workflow substrate made of finite, separately admitted execution
segments. An explicit state machine is the first frontend; compiler-generated
continuations may later target the same transition contract. This separates
workflow correctness from universal language-state serialization.

The decision requested is the segment, durable handoff and ownership model below.
This draft implements no engine, changes no current interface and accepts no ADR.
The [continuation research](../research/continuation-eviction/README.md) supplies
the source/literature basis and remaining compiler questions.

## Motivation

Ordinary async waits retain their Store, cell and original activation owners under
[ADR-0028](../adr/0028-retain-activation-ownership-across-asynchronous-waits.md).
The [workflow crate](../crates/latent-workflows/src/lib.rs) supplies descriptive
types and traits, without an atomic transition or exclusive-resume protocol.
Saving locals alone would leave lost-wakeup, duplicate-effect and old-owner races
unresolved. An explicit workflow boundary can be reviewed and implemented before
transparent compiler capture is qualified.

## Detailed contract

### Identities and execution segments

The host binds tenant, workflow instance/recovery domain, exact definition/schema,
transition version, segment attempt, wait identity and physical execution owner.
Saved application bytes cannot choose those owners or recreate credentials,
Store-local tokens, transaction handles, grants or ledgers.

Each segment acquires current publication/provider/grant and required audit
authority, real scheduler capacity, fresh activation state and finite limits.
Workflow identity survives segments; activation identity does not. A pinned code
image is not permanent permission to resume a revoked publication.

### Conditional durable handoff

At an approved boundary, capture bounded state with no unsupported live resources
or runnable sibling task. Commit the checkpoint, wait registration, accepted state
changes and approved deferred intents under one conditional durable decision.
Stage large immutable payloads before publishing their references. The implementation
must identify its actual commit point; the current command port does not already
provide this operation.

The initial reference is single-node, with one authorized application namespace
and host workflow metadata under the same protected storage owner. Cross-namespace,
cross-service and distributed atomic transitions are outside this proposal's
initial scope; no existing transaction restriction is silently relaxed.

Keep durable position, readiness, old-owner retirement, resume claim and terminal
disposition separate. An early result may become ready while cleanup remains
incomplete. Record it durably without starting concurrent guest execution.

```text
finite segment -> approved capture -> conditional durable transition
  -> old guest retired or enforceably fenced
  -> durable readiness + current authorization + fresh admission
  -> restore recorded state/result -> next conditional transition
```

Lease expiry does not prove a previous worker stopped. New transitions and effect
dispatch must reject stale attempts; fresh execution additionally needs affirmative
retirement or an enforceable isolation/recovery boundary for the old guest.
An explicitly transferred cleanup owner stays bounded and charged, with all
Store/cell references severed. A committed checkpoint is not a reusable-cell proof.

### Delivery, cancellation and effects

Use a bounded durable inbox/match protocol for early, repeated and reordered
signals. Acknowledge accepted input only with a recoverable durable disposition.
Keep the recorded result through claim/decode/restore failure until a subsequent
transition commits its consumption. Persistent cancellation competes with readiness
and admission under the same workflow fence; late signals cannot resurrect work.

External operations cross durable boundaries through approved effect identities
and current-authorized dispatch. Immediate provider calls and open transactions
cannot be serialized into a wait. Preserve
[state/outbox/outcome recovery](../docs/architecture/state-and-effects.md);
timeout or cancellation cannot undo remote acceptance. A segment can execute again
after an uncommitted crash, so this contract promises no duplicate committed
transition, not exactly-once instructions or arbitrary effects.

## Compatibility and migration

Existing invocations and activation-runtime timers keep their current lifecycle
and absolute deadline. They are not silently converted into workflows.
Same-invocation memory eviction requires a separate ownership-transfer decision.

Default to exact definition and continuation-schema pins. Migration of saved
positions/state is explicit, bounded and separately authorized; missing or revoked
code cannot trigger an automatic restart of the business operation. The first
compiler frontend supports one task and bounded value state, with no native-stack
capture. Replay may be another frontend only with an explicit deterministic
programming contract. Final WIT/storage encodings require interface review.

## Resource-allocation impact

Bound total workflow lifetime/work, attempts, waits, checkpoint bytes and retained
effects independently of per-segment limits. Reserve durable attempt allowance
before admission; unknown crash consumption cannot become a refund. Persistent
timers need declared restart/clock semantics rather than serialized local monotonic
instants. Capture/restore overlap and recovery headroom must be reserved.

Suspended workflows retain durable records and bounded shared indexes, not a
Store, leased cell, per-workflow worker or sleeping task. Bound ready queues and
restore concurrency fairly. Required recovery state is not an LRU cache entry.

## Security and trust-boundary impact

Keep signalling, cancellation, inspection, migration and resume authority distinct.
Authenticate checkpoint ownership/integrity and bound decoding, graph depth and
size. Treat locals as sensitive tenant data with access, at-rest and retention
policy. A checksum or copied workflow ID grants no authority. Existing node,
engine, storage and host bindings remain trusted under their declared profiles.

## Failure semantics

Unknown commit uses original-identity recovery; no blind retry or fabricated abort.
Failed cleanup withholds reuse and retains charges. Storage outage, unavailable
capacity, invalid state/schema and lost code have explicit recoverable or terminal
dispositions. Cancellation and external-effect disposition remain independently
observable. Older-history restore needs its own recovery-domain/effect policy.

## Alternatives

Retained async waits remain appropriate for ordinary calls. Explicit workflows
without compiler capture are useful on their own. History replay trades saved
control state for deterministic-command constraints. Arbitrary Store/native-stack
snapshots would add a different portability and resource contract.

## Validation plan

Use the [handoff model](../research/continuation-eviction/handoff-model.md) and
[failure/measurement plan](../research/continuation-eviction/evaluation-plan.md).
First demonstrate an explicit timer/event workflow, conditional claims and restart.
Then destroy captured Store A, run unrelated B in its freed cell, and restore A
in a fresh Store/process. Exercise crashes around durable commit and cleanup,
early/duplicate events, stale workers, cancellation, uncertain effects, budgets,
clock restart and schema mismatch. Compare retained waits, explicit workflows and
compiler capture with equivalent guarantees. No such experiment accompanies this RFC.

## Open questions

1. Which protected storage owner supplies the conditional checkpoint/wait/intent
   decision and inbox match, with what encoding and recovery-domain rules?
2. Which principal/delegation policy authorizes later segments after the original
   caller disappears, and what is the operator outcome after publication revocation?
3. What clock and conservative unknown-consumption policy survives restart?
4. Which bounded resume-claim/old-owner fence is enforceable on the first supported
   host, and what additional decision would distributed execution require?
5. Which initial compiler/state subset can preserve handlers and cleanup, and
   which migrations can be supported without replaying committed business work?
