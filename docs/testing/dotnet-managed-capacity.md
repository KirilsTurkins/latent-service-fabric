# Managed owner capacity qualification

The selected managed accepted-work port retains the original pinned CoreLib Task, ThreadPool and Timer algorithms. Its v2 receipt additionally binds five original timer methods: `TimerQueue.UpdateTimer`, `DeleteTimer`, `FireNextTimers`, `TimerQueueTimer.Fire` and `CallCallback`. Admission of each armed TimerQueueTimer happens before original list mutation. Changing an already-owned timer reuses its owner. One-shot deletion does not refund an accepted callback: original scheduled/running fields, accepted and queued callbacks, and required async descendants must all retire first. Original callback exceptions and captured ExecutionContext values remain authoritative.

The extra fixed 32-entry timer table and TimerOwner/Record objects are managed heap metadata under the original guest linear-memory budget. The existing one-Native-owner registry lease spans their lifetime; it is an owner-count escrow, not a claim of prepaid bytes. Every live timer also reserves its own Timer-kind token in the original native ledger, with the existing per-token charges. The coalesced platform clock registration remains separate. No owner ceiling, execution budget, WIT interface, host implementation or product default increases.

`python3 -B tools/dotnet_managed_work_controls.py --dotnet "$(command -v dotnet)" --timers --output "$RUNNER_TEMP/managed-timer-state-controls"` runs eleven controls against the actual production registry source with explicit test ledger/producer ports. They cover admission rollback, repeated/failed Change, deletion before dispatch, multiple queued callbacks, cancellation, required Task lifetime, Closing descendants, throwing callbacks and finite metadata. They are CLR source controls, not signed guest or original-producer execution proof. The original fifteen registry controls remain separate and mandatory in the new owning lane. A bounded actual Cecil rewrite of the pinned original CoreLib checks every original method and field after serialization; the historical v1 receipt remains unchanged.

The explicit default-false `owner_capacity` workflow selector compiles one ordinary managed component and reuses the authenticated historical `6fd19eab2c224fc31481d03de5008de4d3e4429e` five native products. Its 17 signed invocations cover Task and queue refusals, each individual timer birth/return, original periodic/dispose behavior, a real async timer descendant and finally under Closing, a separately labeled public Native-ledger refusal, production table installation with zero Native capacity, and fresh activations. Task/timer ceilings stay eight; queue/native ceilings only narrow to two. The zero-Native installation refusal is paired with two positive/fresh activations at Native capacity one. The zero-cap terminal is a generic guest trap, not a claim that the original managed exception was transported. Direct Native registration does not qualify NativeMemory allocation semantics.

Each accepted main case is followed by a fresh same-budget activation, all 18 physical counters must return to zero, and all three owned nodes and peers must stop cleanly. Original 120-second invocation and 300-second node/peer windows remain. The one finally marker is the sole permitted HTTP contact. Existing HTTP/private-client and 30-case lifecycle evidence is retained under its original source; this programme does not rerun those baselines. Signed execution is pending. Issue #693 remains open until the literal capacity gate is satisfied; no full #746 or post-retired Store callback claim is made.

The first capacity attempt, source `64102bcc65af07a0a4458c83807e86598f0346a9`, run `39577888602` / job `119147870666`, remains failed. Its first six signed outcomes pass Task and queue refusal/fresh controls and eight individual timer births/returns/refusal/reuse/fresh. The periodic case then returns an unreachable guest trap; this does not identify the original managed cause. The bounded artifact `12335198002` retains the successful component and raw results. A fixture-only diagnostic now converts only callback failures into the existing Task's exception and projects a finite closed code/stage. The original successful periodic body and exact oracle remain required; every diagnostic result is rejected. Failures outside that observable callback/task boundary may remain opaque. No production or native change is inferred from this diagnostic.

The diagnostic attempt `03669e56d0927fb60384e8647c9b2c0a3513990e`, run `39580872537`, also remains failed without an observable callback/await cause. A bounded source control subsequently reproduces a separate precise deferred-parent defect using the actual Rust Timer/Owner sources: the lazy `wait_for` future captures its creator Task token, then validates it only on first poll after that Task can retire. The retained Wait owner now supplies the continuation token through actual future/drop lifetime. Initial admission still validates the original parent; invalid generation/currentness and Closing gates remain enforced. Six actual-source controls cover creator return, Closing, a later ambient Task, early drop and invalid parents with explicit test ledger/clock/pump/quota ports. Their old source has three failures at the original readiness assertion; corrected source passes all six. This is causal source evidence, not a substitute for the pending signed periodic/17-case result. The correction changes the guest adapter only; historical native products remain unchanged.


The periodic failure retained at source `1b19f21db44e137b69a9ccf5aca4d58a7653c51a`
reports the original queued-work resource-exhausted result (closed diagnostic
code 61). It remains an unqualified diagnostic and preserves the original trap.

The selected private timer driver now uses the authenticated CoreLib
`NotOnCanceled` continuation option. Original `FireNextTimers` rearms before its
inline callback. If that callback disables the periodic timer, cancellation
previously queued a driver callback whose original body only returned. Together
with the already queued poll check, that consumed both queue slots before the
required disposal continuation could enter. Cancelled driver continuations now
settle without being queued; successful and faulted waits retain their original
callback, scheduler, identity and epoch checks.

Six actual CLR controls copy the five generated driver methods. Their old
test-only projection must reproduce the two-slot refusal; the current form must
run the required continuation, still refuse a genuine third queued item, and
accept fresh work at the same ceiling. Both success and fault paths are tested
on both forms. Queue and native imports are explicit test ports; these controls
give no signed guest qualification. The original seventeen signed outcomes,
100 ms period and all owner and execution limits remain unchanged.
