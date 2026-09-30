# ADR-0060: Provide activation-scoped runtime compatibility for ordinary dependencies

- Status: Proposed for architecture review
- Date: 2026-09-30
- Revised: 2026-09-30 after the dependency-usability review
- Issue: [#695](https://github.com/KirilsTurkins/latent-service-fabric/issues/695)
- Decision requested: **implement the runtime-compatibility direction in separately
  qualified language/runtime workstreams**; do not require per-library developer
  adapters. **Reject** fabricated execution and application-owned work surviving
  activation retirement. This research PR enables no production runtime facility.
- Builds on [ADR-0005](0005-forbid-per-service-idle-execution-allocation.md),
  [ADR-0028](0028-retain-activation-ownership-across-asynchronous-waits.md),
  [ADR-0031](0031-version-host-abi-recognition-independently-of-provider-authority.md)
  and [ADR-0034](0034-version-maintained-guest-build-provenance-profiles.md).

## Decision and developer contract

LSF will target transparent, bounded compatibility for standard language
concurrency and runtime APIs. The compiler and runtime, not application developers,
will map supported threads, executors, waits, timers and I/O onto activation-owned
execution. A developer should add a dependency normally, including its transitive
dependencies, without injecting an LSF executor, supplying a custom transport or
rewriting the library's public API. Ordinary dependency-locking and explicit
operator capability grants still apply.

**Logical concurrency is permitted during an activation; persistent
application-owned execution is not.** A thread, event loop or timer is not rejected
merely because of its API name. It must have real supported behavior, bounded
ownership and the activation's lifetime. A shared node worker is physical capacity,
not a guest-owned worker retained for a dormant service.

This revises the earlier draft's adapter-first/defer-executor recommendation.
The default direction is now platform and language-runtime compatibility. Optional
adapters may offer convenience or narrower operations, but developer-written
adapters and mandatory protocol gateways are not the standard dependency path.
An LSF-specific structured task API may be additive; it is not a prerequisite for
using existing dependencies. A single new public executor API cannot replace the
six languages' different runtime contracts.

The target is **no extra per-library integration work**, not zero engineering or
runtime cost, an unrestricted operating system, or immediate universal binary
compatibility. A selected compiler/runtime profile remains explicit in provenance.
Existing supported profiles remain unchanged until replacement implementations
pass the gates below. This ADR chooses implementation direction, not release
approval or an assertion that currently denied operations now succeed.

## Context, source findings and evidence boundary

The original reviewed LSF baseline is
`b40a31aa7e63128698df2be86324657b4d22a590`. The
[six-language inventory](../research/invocation-concurrency/languages.md)
separates maintained profile behavior, upstream source findings, the executed
Rust experiment and proposed compatibility work. A synchronous-looking host call
can suspend without supplying a guest scheduler. Existing Go goroutines likewise
do not prove Java, C, JavaScript or .NET compatibility.

There is a concrete Java integration point. In TeaVM **0.15.0**, low-level
[`TThread.start`](https://github.com/konsoletyper/teavm/blob/0.15.0/classlib/src/main/java/org/teavm/classlib/java/lang/TThread.java)
queues `Fiber.start`; the upstream
[`Fiber`](https://github.com/konsoletyper/teavm/blob/0.15.0/core/src/main/java/org/teavm/runtime/Fiber.java)
and
[`EventQueue`](https://github.com/konsoletyper/teavm/blob/0.15.0/core/src/main/java/org/teavm/runtime/EventQueue.java)
provide continuation and queued-event machinery. At the reviewed LSF baseline,
[`teavm_platform.py`](../sdk/java-guest/tools/teavm_platform.py)
replaces `teavm_waitFor` and `teavm_interrupt` with traps. Integrating and bounding
these facilities is a more direct starting point than requiring every library
to expose a custom executor. Source presence is **not** evidence of complete
Java concurrency support: entry/resumption, class-library completeness,
synchronization, clock use, host-call progress and cleanup still need work.
Removing the two traps alone is not an implementation.

The [actual-component experiment](../research/invocation-concurrency/README.md)
remains a bounded Rust stackless join, not this compatibility runtime. Its
[retained evidence](../research/invocation-concurrency/evidence/README.md)
records twelve component cases, four native scope tests, eight receipt tests and
seven equal-arithmetic-work sample pairs at their original source identities.
It demonstrates pending host ownership and unsafe inline substitution, not
unchanged third-party-library or six-runtime compatibility. In particular, the
epoch-trap case returned with six host operations still owned; Store destruction
retired them. The documented run's subsequent formatting failure is not erased.

[#679](https://github.com/KirilsTurkins/latent-service-fabric/issues/679)'s diagnostic
classifications remain a dependency to consume, not completed evidence inferred
from this ADR. This documentation revision changes neither executable sources nor
historical receipts. No old measurement is relabelled as a test of the new design.

## Architecture: standard runtime ports over existing activation ownership

The builder links maintained runtime implementations beneath application code and
its complete captured dependency graph. Supported standard entry points select
these implementations regardless of whether the caller is application code or a
transitive library. Runtime/package ports or versioned patches, when needed, are
LSF-owned, automatically applied, source-bound and recorded in build provenance.
They must not silently change library semantics or fall back to ambient host APIs.

Language runtimes retain language-specific scheduling and synchronization semantics.
The shared host boundary owns readiness, authorized I/O, deadlines, cancellation,
resource reservations and retirement through existing LSF infrastructure. Prefer
existing language continuations/fibers; evaluate Component Model task/thread
mechanisms only against exact compiler, binding and engine versions. A proposal,
a host async switch or an available API is not an execution receipt. This ADR
mandates neither an unqualified Wasm feature nor an extra competing host executor.

| Standard operation | Required compatibility implementation |
| --- | --- |
| Thread creation/start | An independently schedulable logical thread with owned execution state and identity; never inline worker execution or a successful no-op. |
| Executor or pool submission | Preserve each executor's queue, ordering, concurrency restrictions, rejection and shutdown semantics while sharing bounded physical capacity. |
| Join, future wait, lock, condition or channel wait | Park the calling logical thread and permit eligible siblings to progress; preserve wakeup, ownership and interruption semantics. |
| Sleep or timer registration | Bounded activation-owned registrations driven by readiness and time, not a host worker sleeping for the guest. |
| Blocking I/O | Suspend the calling logical thread while the authorized host operation owns its buffers and capacity; resume at a valid runtime boundary. |
| Activation completion | Settle accepted work according to an explicit lifecycle contract, retire infrastructure, and retain charges until real cleanup. |

Logical concurrency and CPU parallelism are separate. The initial compatibility
path may interleave logical threads on one guest execution lane. It must preserve
the named language's supported observable synchronization behavior, not promise
multicore speedup or all shared-memory/native-thread semantics. Work that genuinely
requires parallel execution or native thread identity needs separate compiler and
engine qualification. Fixed shared physical workers could be evaluated for that
purpose without allowing dormant per-application workers; no such mode is enabled
or automatically selected here.

## Progress, synchronization and executor semantics

A blocking call must not suspend all guest progress while another guest thread
could satisfy it. Preserve the waiter's stack/continuation and locals, let the
language scheduler run an eligible sibling, and wait on the host only when no
guest work is runnable. Host callbacks borrow Store state for bounded synchronous
checkpoints and release those borrows before awaiting external work. Java's
synchronous import bridge must participate in this fiber-aware protocol; making
only the host callback asynchronous is insufficient.

High compatibility also needs bounded scheduling opportunities in CPU-bound code.
The runtime/compiler must qualify preemption or compiler-inserted scheduling
checkpoints at safe long-running paths, such as loop backedges, throughout the
reachable dependency graph. A synchronized flag loop must not indefinitely starve
the thread that can set the flag merely because the loop lacks an explicit yield.
Host fuel yielding that always resumes the same guest thread does not satisfy
this requirement. The existing stackless prototype does not implement it.

Checkpoint placement must preserve atomic operations, memory ordering,
thread-local state, exception unwinding, garbage-collector roots and regions in
which suspension is unsafe. Every non-suspendable path needs a bounded execution
argument or an explicit unsupported classification. Safe scheduling must not
turn one atomic operation into observable partial updates. CPU fuel/deadline
containment remains the final bound, not proof of sibling progress or fairness.

Specify and test thread start/join ordering, reentrant monitors, condition-wait
release/reacquisition, lost-wakeup prevention, interruption, thread-local storage
and applicable happens-before rules. Separate single-thread executors remain
separate logical executors; sharing CPU capacity must not collapse them into one
queue, introduce concurrent callbacks, or execute callbacks reentrantly in a caller
when their contract does not allow it. Future exceptions, task cancellation and
executor rejection must follow the named API rather than a universal join policy.

The counterexample remains decisive: a worker waits for initialization performed
after `start()` returns. Calling the worker inline deadlocks the initializer.
The old Rust component demonstrates that failure and an explicitly yielding
alternative. It does not prove Java `Thread.start` or an automatically transformed
spin loop. Those are required real-component tests for the new workstream.

Nested service calls keep their original parent cell and conserved descendant
budget. Saturated capacity must produce the existing bounded admission failure
rather than lending a live parent's cell, widening a deadline or creating hidden
workers. Guest-task scheduling does not create additional node execution cells.
Cross-tenant reuse, nested progress and full-cell behavior require real-node tests.

## Bounds: logical concurrency is not physical capacity

All execution state is subordinate to the admitted activation, its Store
generation, publication, identity and capability session. A task or thread handle
cannot be serialized into durable state, used by another activation or resumed
after retirement. Limits apply across runtime-created and user-created work and
nested scopes; creating another executor cannot multiply the activation allowance.

Production profiles must declare independently enforced limits for the following
resources, intersected with operator policy. The limits are runtime-profile
configuration, not per-library adapters or per-library approval lists.

| Resource | Required bound and accounting owner |
| --- | --- |
| Logical threads/tasks and continuations | Finite aggregate counts; reserve execution records and stack/frame capacity before creation, enqueue or dispatch. Count internal runtime work too. |
| Logical executors, queues and results | Bound executor records, queued items, retained result/error capacity and wake registrations; coalesce duplicate readiness without losing required notifications. |
| Guest and native stacks | Charge continuation frames, stack growth, thread-local data and runtime/native async stacks through existing accounting. A parked thread still costs memory. |
| Heap, captures and I/O | Account aggregate linear memory, transitive captures, payload capacities, runtime/provider buffers and lowering ownership without double-spending the parent budget. |
| Timers | Bound live timer registrations, metadata, outstanding callbacks and callback execution. Rescheduling or recurrence cannot reset the original deadline or fuel. |
| Physical execution | Use configured shared node capacity; no per-service dormant thread pool, event loop, initialized guest heap or hidden native worker. |
| Fuel and deadline | One original activation budget and deadline across all logical work; no per-task fuel reset, hidden retry or separate cleanup budget. |
| Cross-activation execution | Zero surviving guest tasks, timers, callbacks, captured handles or authenticated application connections. |

The prototype's **8 tasks**, candidate **8 KiB direct frames / 64 KiB total**,
**4 KiB scheduler metadata**, **256 KiB Wasm call-stack setting** and **16 MiB
linear-memory cap** are experiment/initial qualification bounds, **not universal
production defaults**. Likewise, the earlier candidate of eight single-shot
timers / 1 KiB metadata is not an established library-compatible timer policy.
Select production numbers using unchanged-library workloads and measured stack,
heap, queue and native costs, then test exhaustion before unsafe allocation.
A memory ceiling alone does not prove a task-count or native-stack bound.

Allocate lazily and preserve a low-overhead path when concurrency is unused.
Report cold setup, active and parked costs and the no-concurrency regression;
logical threads need not imply one OS thread each. Pool requests and
available-processor queries must reflect the documented target rather than silently
promise more parallel capacity. Exceeding limits must report a bounded, meaningful
failure, not silently discard a submitted task or pretend a thread started.

## Activation-local helpers, completion and physical retirement

Library-owned workers, event loops and maintenance tasks may run **during** an
activation. They remain activation-owned even when the library calls them
background or daemon work. Detached ownership, fire-and-forget execution beyond
the activation, and dormant per-application allocation remain forbidden.

Define one root lifecycle:

`admitted -> running/waiting -> closing -> draining/cancelling -> retired`

The activation remains Running while waiting or draining. Application result
availability is not physical retirement or permission for early cell/budget refund.
A compatibility profile must define the point at which ordinary result delivery
is finalized and how unfinished work affects that outcome; it must not call a
result successful merely because an opaque thread was destroyed.

Do not implement shutdown by blindly joining every worker. Runtime-managed pools
must distinguish accepted tasks and required completion callbacks from idle worker
infrastructure. On normal root completion, close admission of new independent
work; permit only bounded continuations needed to settle previously accepted work
under the same grants and original deadline. Drain required tasks and apply the
API-specific exception policy before finalizing the root result. Retire idle
managed workers and cancel future maintenance registrations according to the
explicit activation lifecycle. A recurring callback already running must be
settled or cancelled and accounted for, not simply forgotten.

A waiting thread is **not** evidence of harmless infrastructure. An arbitrary
custom worker could be awaiting a flush or another externally meaningful action.
Do not infer its role from sleeping, idleness, a daemon flag or a queue shape.
If the runtime cannot establish the required quiescence, return a bounded
lifecycle/cancellation failure and preserve uncertain effects, rather than report
successful completion after dropping work. Libraries requiring useful work after
activation retirement are outside this lifetime contract. This is an explicit
stateless-target boundary, not full JVM/process-lifetime equivalence and not a
requirement for developers to supply per-library shutdown adapters.

A root stop, including timeout or disconnect, closes new work admission, revokes
execution authority and signals descendants. Interruption/finally semantics should
be preserved where safely executable; cooperation cannot be assumed. A trap may
bypass guest destructors. Destroy the Store and retire actual host/provider owners
through existing containment; late completions must be fenced by activation and
Store generation. Owners that cannot retire promptly remain charged or use the
existing bounded quarantine path. No reusable-cell proof escapes early.

Cancellation acknowledgement, a returned timeout, a dropped future or a watchdog
are not proof of physical cleanup or external rollback. External uncertainty
remains uncertainty. The research watchdog's expiration remains a failed run, not
a successful cancellation receipt. No new exactly-once or rollback claim is made.

## Timers are runtime facilities, not durable workflows

Target ordinary sleep, timeout and scheduling APIs, including bounded recurring
library maintenance within an active invocation. A timer parks logical work; it
must not occupy a sleeping host worker. Time is supplied through explicit,
approved runtime/clock authority, not arbitrary access to host time or an invented
success path. A clock-read grant does not implicitly approve a new timer import.

Keep the requested timer semantics separate from the root deadline. If a requested
wait extends beyond the remaining invocation, the root stop cancels the wait;
it must not appear to have elapsed successfully early. Preserve the supported
API's monotonic/relative versus wall/absolute behavior, cancellation and recurrence
policy; bound any catch-up work and overlapping callbacks. Prevent timer storms
from bypassing the normal task, memory or fuel limits.

Timers cannot fire after retirement or resume from a captured callback in the next
invocation. Restart-surviving schedules and business work after return belong to a
separately designed durable workflow/event mechanism. Phase 4/5/6 durable execution,
clustering and continuation persistence are not pulled into this runtime change.
The current experiment and current denied profiles still enable no new timers.

## Standard I/O compatibility and ADR-0059

Thread compatibility alone does not make ordinary network clients work. Target
standard socket/stream, DNS, read/write and readiness interfaces beneath libraries,
and standard HTTP entry points where their exact semantics can be implemented.
Blocking operations must integrate with the logical-thread scheduler. Developers
should not need a custom transport object or a separately operated gateway solely
to make an otherwise supported dependency usable.

A capability-backed bounded outbound stream substrate is the proposed direction
for clients that genuinely use byte streams. This is **not** automatic protocol
inference: do not guess HTTP or database operations from arbitrary stream bytes,
forge socket handles, silently reconnect/replay, or reuse authenticated guest
connections across activations. Preserve partial I/O, EOF, supported readiness,
TLS/trust behavior and error timing; unsupported transport semantics fail explicitly.

[ADR-0059](0059-defer-general-outbound-streams.md) currently defers production
outbound streams and prefers typed operations/gateways. Its adapter-first
preference is not the default for this compatibility workstream. A separately
scoped outbound follow-up must explicitly reconcile that recommendation and
qualify the standard-runtime stream path before enabling it. This ADR does not
silently supersede its production admission/security boundary or grant sockets.
Typed providers and gateways remain optional products for narrower semantics.

Generated runtime imports and dependency observations are declarations, never
grants. Reuse existing tenant/publication/generation checks and sealed capability
ownership. Bound endpoint/port authority, DNS/address policy, buffers, transfers,
TLS trust, deadlines and revocation. An HTTP method/path grant cannot authorize
arbitrary TCP bytes; unresolved networking needs remain explicit. No application
startup execution on a privileged build host or hidden ambient fallback is allowed.
No extra per-library code does not mean no deployment permissions.

## Alternatives and per-language implementation direction

| Alternative | Decision and tradeoff |
| --- | --- |
| Developer-selected sequential path | Remains an optional optimization with its actual ordering/reentrancy semantics; not a silent substitute for thread creation or required dependency adaptation. |
| Per-library developer executor/transport injection | Reject as the default compatibility requirement. Optional adapters may expose narrower behavior, but custom injection is not a passing unchanged-library compatibility test. |
| New public structured-future scope only | Useful additive SDK facility and experiment; insufficient for transitive libraries that call standard threads, pools, blocking waits or timers internally. |
| Maintained standard runtime/compiler ports | Chosen direction. Higher platform maintenance and measurable activation overhead, but avoids repeating integration work in every application. Preserve language-specific contracts. |
| Component Model scheduling mechanisms | Candidate substrate, not a universal finished implementation. Qualify exact toolchain support, lowering, progress, accounting and cleanup before selecting it. |
| Shared host/provider infrastructure | Reuse for bounded physical execution and real authorized I/O; retain activation-owned charges and identity, not hidden per-service workers. |
| Full resident OS/JVM/Node service per dependency | Reject for dormant execution. More familiar APIs cannot justify abandoning fresh activation state or retaining idle application processes. |

| Profile | Decision and first implementation boundary |
| --- | --- |
| Java | Prioritize integration of existing TeaVM fibers/event queue, completion of required standard threading/executor/synchronization APIs, fiber-aware I/O and timer hooks. Do not equate source inspection with working components or full JVM semantics. |
| Go | Preserve existing goroutines and extend the runtime's polling, timer and standard I/O integration with independently enforced internal/user work bounds. Do not replace Go semantics with a foreign public scheduler API. |
| C | Implement a qualified libc/runtime boundary for logical threads, synchronization, thread-local storage, stacks and I/O. Generated canonical subtasks alone are not pthread/C11 compatibility. |
| Rust | Qualify a runtime target and standard-library/executor integration. The current `wasm32-unknown-unknown` thread trap is a current-profile result, not a ban on a new target; an extra join combinator cannot replace the standard runtime. |
| JavaScript / TypeScript | Implement an invocation-driven async runtime for Promise completion, jobs and timers and a qualified export lifecycle; name any additional Node API subset explicitly. Current ordinary-value exports remain unchanged until qualification. |
| .NET | Integrate at runtime/ThreadPool/waiting layers and preserve Task, thread-local, exception and GC behavior. A custom synchronization context or completed Task does not establish pool/thread compatibility. |

Commonality is the activation and host-operation boundary, not identical guest
schedulers or a blanket claim of shared-memory CPU parallelism. Reflection,
dynamic loading, native ABIs, filesystem assumptions and process-lifetime state
remain separate compatibility dimensions. A threading fix alone cannot certify
those features. Reachability diagnostics must distinguish unused unsupported code,
compile incompatibility, denied-on-use, missing provider/grant, budget exhaustion,
root cancellation and unknown behavior without rejecting every dependency that
mentions a thread API. Do not claim arbitrary indirect/native calls are statically
proven safe or silently remove code that the analysis cannot understand.

## Implementation sequence and conformance gates

Production work belongs in narrowly scoped follow-up issues/PRs, not implicit
promotion of the research join. Preserve ordinary dependency ingestion work;
it need not wait for all six runtime ports or a universal compatibility milestone.
The sequence is Java runtime proof, unchanged-library qualification, then measured
expansion of the other profiles and the separately reviewed standard I/O substrate.

1. **Java runtime integration:** on the pinned TeaVM/compiler/bindgen/engine
   combination, implement invocation entry/resume and event processing; thread
   start/join/identity/locals/interruption; monitor/condition waits; required pool,
   future and timer APIs; and per-fiber host-call suspension. Include a synchronized
   spin-loop sibling-progress test with no application yield, independent executor
   queues, host waits with runnable siblings, and bounded stop of noncooperative
   work. Validate emitted components, not just JVM tests or removal of trap stubs.
2. **Unchanged-library acceptance:** pin at least two representative published
   libraries for each claimed language profile, including a case whose transitive
   dependency creates workers/pools and a case using timers or blocking I/O.
   Exercise ordinary construction and default execution paths with no supplied
   LSF executor, custom transport, user patch or application-level yield. Compare
   supported observable behavior against the reference runtime, including ordering,
   errors, interruption and teardown. Keep any adapter-assisted cases separate;
   neither those cases nor a package allowlist may substitute for standard-runtime
   conformance. Record LSF-owned runtime patches and exact dependency graphs.
3. **Accounting, lifecycle and authority:** use signed real-node components to
   cover normal completion, partial failures, idle pools versus unfinished tasks,
   recurring callback shutdown, opaque-worker non-quiescence, memory/task/queue/
   timer overflow, fuel, deadline, disconnect, late wakeups, nested calls, full
   cells, missing/revoked grants and cross-tenant fresh-Store reuse. Prove actual
   host/provider retirement before capacity refund and preserve uncertain effects.
4. **Language/runtime and transport ports:** specify versioned supported standard
   surfaces per language; qualify Go scheduler-created work, C/Rust stacks and
   target ABI, JavaScript async exports/jobs and .NET pool/GC integration. Reconcile
   ADR-0059 in the outbound follow-up and test actual unchanged clients against
   controlled peers, including partial transfers, trust failure, denial before
   connect, cancellation and effect uncertainty. No new ambient authority or
   automatic protocol inference is an acceptable shortcut.
5. **Cost, diagnostics and promotion:** retain source-bound components, toolchain
   and dependency identities, positive and negative reference comparisons and
   complete receipts. Measure cold initialization, no-concurrency regression,
   scheduling latency/overhead, active/parked stack and heap, native allocation/RSS,
   I/O owners and cleanup; report unmeasured costs explicitly. Consume #679's
   classifications. Establish production limits from these workloads and require
   architecture/security review before enabling a profile. No numerical compatibility
   percentage is claimed without a named corpus and observed results.

## Consequences

LSF takes responsibility for runtime compatibility rather than transferring it to
every dependency consumer. The costs are standard-library/compiler maintenance,
versioned runtime ports, more demanding conformance testing and measured active
memory/CPU overhead. Lazy construction and shared physical capacity must preserve
the no-dormant-allocation property and avoid penalizing the simple synchronous path.

The hard boundary is activation lifetime and explicit authority, not API names.
Useful local concurrency and maintenance are targets; durable background execution,
fake success, hidden native work and early refunds are not. Some native, dynamically
loaded or process-lifetime-dependent libraries will still need separate platform
work or remain incompatible. This is a high-compatibility engineering direction,
not a claim that the prototype already executes every dependency unchanged.

Accepting this revised ADR chooses that direction and its acceptance gates. It
does not publish a runtime release, change grants, approve a production scheduler,
or rewrite the original experiment's limits and measurements.
