# ADR-0060: Bound invocation-scoped concurrency; defer a universal guest executor

- Status: Proposed for architecture review
- Date: 2026-09-30
- Issue: [#695](https://github.com/KirilsTurkins/latent-service-fabric/issues/695)
- Decision requested: **defer** a new production executor; **reject** transparent
  thread emulation and detached guest work; preserve each qualified SDK profile.
- Builds on [ADR-0028](0028-retain-activation-ownership-across-asynchronous-waits.md),
  [ADR-0031](0031-version-host-abi-recognition-independently-of-provider-authority.md)
  and [ADR-0034](0034-version-maintained-guest-build-provenance-profiles.md).

## Context and evidence boundary

A library can expose a synchronous-looking method while its host import suspends
an activation. That does not establish a guest thread scheduler, parallel CPU
execution, an event loop or durable continuation support. Conversely, Go's
existing cooperative goroutines do not establish the same facility for TeaVM,
NativeAOT, C or ComponentizeJS. Adding one executor abstraction to the host would
not repair these different compiler and language contracts.

The baseline reviewed here is `b40a31aa7e63128698df2be86324657b4d22a590` on
`development`. Its SDK documents and source paths, exact toolchain versions,
standard-library use cases, evidence classifications and semantic gaps are in the
[six-language inventory](../research/invocation-concurrency/languages.md).
The independent [experiment](../research/invocation-concurrency/README.md)
contains real generated Rust components and a Wasmtime embedding, not only a
scheduler model. Its source-bound receipts distinguish measured linear memory,
fuel, pending owners and retirement from unmeasured native allocator/RSS costs
and production-node qualification. A test definition is not a passing result.

[#679](https://github.com/KirilsTurkins/latent-service-fabric/issues/679) was still
open when this investigation read it. Its unsupported/unknown/adapter/authority/
budget/cancellation distinctions are requirements consumed here, not claimed
completed diagnostic evidence. This decision must not block ordinary dependency
integration or explicit HTTP transport adapters in the six SDK workstreams.

## Decision and per-language disposition

Do not add a production scheduler, guest thread import, generic executor API,
background service allocation or timer authority in this change. Keep the
prototype under `research/`; neither production crates nor SDKs depend on it.
Its Cargo examples reuse existing locked toolchain dependencies only.

| Profile | Decision now | Reason and permitted direction |
| --- | --- | --- |
| Rust | Defer an SDK task-scope API; retain current async host bindings. | Stackless futures are a plausible narrow fit. The experiment qualifies only its explicit bounded join, not Tokio, Rayon, OS threads or arbitrary future implementations. Promotion needs the node/accounting gates below. |
| Java | Reject inline/fake `Thread.start`; defer compiler/executor work. | TeaVM C is not a JVM. Synchronous-looking capability calls already suspend on the host. Default pools, virtual threads and monitor waits cannot be inferred from that bridge. Prefer an explicit transport seam. |
| C | Defer C11/POSIX thread support; preserve generated async call ownership. | C callbacks and generated canonical subtasks are not stackful C threads. A pthread ABI or stack-switching library needs separate compiler, stack and cleanup evidence. |
| JavaScript | Defer a general async-export/event-loop promise. | The maintained profile requires ordinary export return values, not Promises; activation-local microtasks do not make Node workers, timer APIs or detached callbacks available. |
| Go | Preserve qualified activation-local goroutines; defer new scope-count and timer promises. | Existing single-threaded scheduling is real, but an independently enforced eight-task limit is not established for arbitrary Go/runtime-created goroutines. Memory/fuel bounds are not a goroutine-count receipt. |
| .NET | Preserve documented activation-local Task behavior; defer scheduler expansion. | NativeAOT's current Task probes and synchronous import projection do not qualify `Task.Run`, ThreadPool, timers or a persistent CLR event loop. |

These are profile decisions, not claims that every library mentioning these APIs
must be rejected at dependency resolution. Reachability and deny-on-use analysis
must distinguish unused code, compile-time incompatibility, actual denied calls
and unknown paths. Unsupported execution must fail explicitly; it must never be
reported as successful scheduling, a successful no-op, or a fabricated result.

## Alternatives evaluated

| Alternative | Semantic fit and cost | Decision |
| --- | --- | --- |
| Explicit sequential execution | Lowest scheduling/queue cost; preserves order for libraries with a documented synchronous path. Independent waits do not overlap. Rendezvous protocols or work expecting a child to start independently may deadlock. | Prefer when the caller/library explicitly selects it. Never silently substitute it for thread creation or asynchronous execution. |
| Explicit transport injection | A library delegates its HTTP/service operation to an installed capability provider. Host suspension can preserve a synchronous API without adding guest CPU workers. Cancellation, headers, stream ownership and error semantics still require an adapter contract. | Prefer a narrow adapter when its library/compiler profile supports the seam. This RFC does not expand networking authority. |
| Cooperative guest scheduling | Overlaps suitable waits, not CPU execution. Adds frame, wake, result and cancellation ownership. One non-yielding poll can starve siblings; host fuel yielding alone does not make that poll a guest scheduling point. | Plausible for explicit Rust futures and the existing Go profile, but not a universal compatibility layer. |
| Supported Component Model task mechanisms | Canonical async calls/subtasks make host/guest progress and cancellation representable. Exact generated ABI/runtime support matters. A synchronous lowering may still block guest progress despite an asynchronous host implementation. | Use only the pinned compiler/bindgen/runtime contract. A Wasmtime host future is not evidence that every guest language exposes a matching task API. |
| Host provider delegation | Shared, bounded host infrastructure can multiplex real I/O without a guest worker per service. It introduces provider permits, buffers, late completions and physical cleanup responsibilities. | Keep existing capability boundaries and ADR-0028 ownership. Never use a shared pool to hide unaccounted activation-owned work. |

No alternative grants CPU parallelism, shared-memory thread semantics or a right
to execute after return. An explicit sequential adapter may also change callback
reentrancy or error timing; even an apparently harmless completed-future path
must be qualified for the named library and version.

## Candidate scope model, not a production API

A future approved scope would be an affine child of one admitted activation:

`admitted -> running/waiting -> admission-closed -> cancelling/draining -> retired`

The public activation remains Running while waiting or draining. The scope is
bound to the activation identity, Store generation, publication and capability
session. It owns its task frames, ready registrations, results and single-shot
wait registrations. A task handle cannot be serialized, stored as durable state,
transferred to another activation or used after scope retirement.

The following are concrete candidate limits for a narrow first qualification,
not newly advertised SDK defaults. Unknown or unaccounted storage is a rejection,
not a reason to mint a second budget or assume zero cost.

| Resource | Candidate bound and accounting owner |
| --- | --- |
| Guest tasks | At most 8 outstanding tasks across the entire activation, including nested scopes; not 8 per nested group. Check before enqueue/allocation/dispatch. |
| Direct stackless task frames | At most 8 KiB per frame and 64 KiB total direct frame storage, reserved before boxing/enqueue. Transitive captures and payload capacity remain charged to the existing activation memory budget. |
| Ready queue / result slots | At most 8 unique ready registrations and 8 results; duplicate wakes coalesce. At most 4 KiB scheduler metadata. Returned errors have a closed, bounded representation. |
| Guest and native stacks | No guest OS-thread stacks. Stackless tasks share the guest execution path. The experiment sets a 256 KiB Wasmtime call-stack limit; a linear stack is part of linear memory. Native async fibers and their stacks must be measured and reserved through existing accounting before any production promise. The call-stack setting is not a native-heap measurement. |
| Heap and lowered buffers | Existing activation memory limit covers aggregate linear memories, guest allocations and already-accounted runtime/provider/lowering ownership. The experiment's 16 MiB linear-memory cap does not establish this complete production total. |
| Timers | Zero new guest timers in this experiment/current denied profiles. A separately approved extension may allow at most 8 single-shot registrations and 1 KiB timer metadata, each no later than the root deadline. A clock-read grant alone does not authorize a new timer ABI. |
| Detached work / recurring timers / durable handles | Zero. No background thread, fire-and-forget task, repeating timer, continuation persistence or cross-activation handle. |
| CPU and deadline | One original Store fuel budget and activation deadline, shared by every task. No per-task reset, deadline extension, hidden retry or detached cleanup allowance. |

The prototype's bounded arrays and eight-child poll round are not a production
admission mechanism for foreign runtimes. In particular, they cannot intercept
compiler-created Go goroutines, Java continuations or NativeAOT runtime work.
Those need explicit runtime integration and measurements before the same bound
can be claimed. The prototype has no timer API and performs no scope promotion.

## Progress, fairness and library compatibility

A cooperative poll round visits each unfinished task at most once, rotates the
starting task and returns Pending until a child wakes it. It does not busy-spin
while waiting for a host operation. Completed children are not polled again.
The bounded join returns results/errors in spawn order only after every child has
completed. A partial error does not silently discard a still-running sibling.

This is a conditional fairness property: each poll must itself return. An
uncontended lock, single-thread atomic or synchronous callback may work, but a
blocking lock/condition-variable wait that needs another guest task can prevent
progress. Holding a lock across an await can create the same dependency cycle.
Atomics alone do not provide workers, preemption or another thread's memory model.
The component's inline-start rendezvous counterexample exhausts shared fuel;
the explicitly cooperative variant makes progress. Real `std::thread::spawn` is
also exercised as an unsupported target API, not replaced by a test stub.

Nested service calls retain the parent activation's cell and reservations.
Children use the existing bounded service admission and conserved child-call
budget. When capacity cannot support progress, admission must reject promptly
with the existing bounded error rather than lend out a live parent's cell,
create hidden workers or release its reservation. Nested calls, saturated cells
and cross-tenant cancellation require real node qualification; the experiment's
controlled host rendezvous is not that qualification.

## Authority, cancellation and physical retirement

Every task sees the same host-derived identity and capability session as its
root. Task creation does not grant sockets, filesystem access, clocks, entropy,
service delegation or more budget. Guest arguments cannot become authority.
The research linker installs only its private test interfaces; production linker
profiles and deny-on-use behavior are unchanged.

A host callback borrows the Store only for bounded synchronous checkpoints and
releases that borrow before awaiting a provider. A pending operation keeps its
actual native owner, memory/buffer charges and provider capacity. A root stop
closes further admission and signals descendants. Cancellation acknowledgement,
a returned timeout, a dropped Rust future and a completed watchdog are **not**
proof that an external effect did not happen or its owner physically retired.

Normal return joins/drains the scope before result publication. A terminal trap
may bypass guest destructors; containment destroys the Store and handles actual
provider retirement through the existing owner path. A provider that cannot
retire promptly must remain charged or enter the already-defined bounded
quarantine path. It cannot yield a reusable cell proof early. Late wakeups must
be fenced by the retired Store/activation generation and may not touch its memory.
External uncertain outcomes remain uncertain; this proposal adds no rollback or
exactly-once claim.

The research cancellation gate deliberately separates observing cancellation
from releasing the host-operation owner. Its witness checks live owners and a
live Store between those events, then checks actual operation drop and Store
destruction. Manual epoch expiry tests root interruption without using sleeps
as a readiness witness. The ten-second experiment watchdog only bounds a broken
run; expiration is failure, never successful cleanup evidence.

## Invocation timers are not workflows

An invocation-local single-shot wait, were it approved, would consume a bounded
registration, share the root deadline and disappear during scope drain. It could
not fire after return or be restored from a stored callback. A recurring or
restart-surviving timer is durable scheduling: it needs a separately designed
workflow/event mechanism, not a sleeping guest or a keep-alive activation.

Do not pull Phase 4/5/6 durable execution, clustering or continuation persistence
into this RFC. Do not implement a second budget ledger, a duplicate executor
admission path or per-service idle workers to obtain timer compatibility.

## Promotion gates and narrowly scoped follow-up criteria

No production implementation is approved here. A future proposal must name the
language, compiler, binding/runtime versions and exact library patterns it will
support, and satisfy the relevant gate below in a separate issue/PR:

1. **Rust bounded scope qualification:** expose only structured join/cancel for
   owned stackless futures; enforce aggregate task/frame/wake limits before work;
   reuse the existing activation budget and capability session; run signed real
   node components through success, partial error, cancellation, fuel, deadline,
   memory exhaustion, late wakeups, full cells and cross-tenant reuse. Retain
   native allocation/stack attribution, not only linear-memory measurements.
2. **C generated-subtask ownership:** qualify generated canonical call/subtask
   cancellation, lowering-buffer lifetime, stack use and repeated fresh-Store
   calls on the pinned toolchain. Do not label that result pthread/C11-thread
   support. Any stackful implementation requires a separate stack/accounting ADR.
3. **Go runtime bounds:** inventory runtime-created and user-created goroutines,
   prove count/stack/heap and timer limits under the patched compiler, and test
   blocked channels, saturated child capacity and root-stop cleanup. Preserve
   the current explicit rejection of unsupported timer/poll paths.
4. **Java/JavaScript/.NET compiler contracts:** demonstrate the exact continuation
   lowering and export contract first. Include `Thread.start`/default-pool,
   Promise export/recurring timer, and `Task.Run`/ThreadPool negative cases as
   applicable. A native-language unit test or a completed-value microbenchmark
   cannot qualify the emitted component. Never weaken rejection into fake success.
5. **Shared conformance and diagnostics:** consume #679's closed classifications;
   distinguish compile failure, denied-on-use, missing provider/grant, budget,
   cancellation and uncertain completion. Run all relevant cases on actual
   components, compare sequential and cooperative work, and gate promotion on
   complete source-bound receipts plus architecture/security review.

Ordinary libraries and explicitly scoped transport adapters do not depend on
these follow-ups. A library that does not require guest scheduling should not
wait for an executor milestone.

## Consequences and review checklist

The benefit is a small, reproducible investigation and an explicit compatibility
boundary instead of a misleading thread abstraction. The cost is that libraries
requiring genuine thread/event-loop semantics remain unsupported until their
own compiler/profile work is justified. The Rust experiment is useful evidence
for a narrow candidate, not a six-language compatibility certification.

Reviewers should inspect the [requirement map](../research/invocation-concurrency/README.md#requirement-map),
[language inventory](../research/invocation-concurrency/languages.md), retained
run receipts and the unmeasured costs before accepting this decision. Accepting
a defer/reject ADR is not a production release or approval of an SDK scheduler.
