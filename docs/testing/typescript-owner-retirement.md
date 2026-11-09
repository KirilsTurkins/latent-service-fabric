# TypeScript activation owner retirement audit

## Scope and status

This is the Agent 3 integration increment for PR #1852 and issue #745, based on
`83c339673b87afabfa06f3a8e818324f46c1ae6f`. It fixes native timer/import retirement
and cancellation fencing using the existing original-activation owners. It is
**not** aggregate byte-accurate runtime qualification or completion of #745.
The published profiles, WIT, budgets, 64-Native-owner limit, source derivations,
AbortSignal transformation and signed Fetch probes are unchanged.

The native controls execute production C++ manager/accounting bodies with finite
JSAPI and canonical-host doubles. They do not execute SpiderMonkey, the signed
component, a real provider, or Wasmtime Store destruction. Model generation tests
are not fresh cross-tenant engine isolation evidence. A callback returning false
without a pending exception is not a real Wasm trap.

## Before/after ownership matrix

| Allocation or owner | Admission and backing budget | Before this increment | After this increment / remaining boundary |
| --- | --- | --- | --- |
| Root and accepted work | Original Task and QueuedWork tokens; host table backing charged before allocation | Root settlement closes new root admission; accepted children retain their original parents | Unchanged; positive timer-after-root control preserves this distinction |
| Promise objects and reaction records | Native tokens before instrumented intrinsic allocation; reactions also reserve Task/QueuedWork; bytes reside in guest linear memory | Weak tracking and collection-completion checkpoints distinguish settlement from physical collection | Unchanged hooks; a live Native reservation slot now refuses readmission, including in compiler-snapshot phase |
| Promise job queue / microtasks | Original accepted task/queue reservations precede C++ queue-node allocation | Callable roots survive the executing JS frame; deletion precedes broker settlement; a stopped queue blocks dispatch | Unchanged; existing physical retirement/refusal controls remain selected |
| Timer callback record and captured arguments | Native owner before record allocation; original Timer owner before host timer creation; captures consume guest linear memory | Host timer was created before allocating captured arguments; capture OOM required fallible timer-stop rollback | Allocate and root captures before timer-start; capture OOM creates zero host timers |
| Timer physical retirement | Native token remains charged after record destruction until broker ACK | A second destruction could overwrite the single retained failed-ACK token | Retry the exact older token first; on refusal do not destroy another record; no extra queue or failure-slot allocation |
| Async import record / lowering / result | Record Native, Task/QueuedWork, lowering Native and Result admission before private WIT-layout buffers | Failed result/lowering/record ACKs occupied scalar slots that were neither drained first nor reliably retained across a second destruction | Drain exact original Result, lowering Native and record Native tokens first; partial ACK flags prevent double refund |
| Returned/importing values during cancellation | Existing ImportLifecycle, stable result/parameter buffers, original borrowed captures | An early cancelAll refusal left later records eligible for turn, lowering or lifting | Manager stop fences all three entry points; diagnostic failure precedes Promise resolution or typed lifting |
| Canonical readiness / pending host return | Lazy Native-backed readiness set and stable intrusive subtask records | Cancellation request did not prove terminal return, unjoin or drop | Unchanged; late-return test retains buffers/roots until the explicit terminal/drop barrier and runs no application callback |
| Uncertain OWN-result disposal / borrow observer completion | Existing disposition and observer quarantine retain original paid records | Disposer is marked non-retryable before entering it; uncertain cleanup is not replayed | Unchanged; failed disposer control retains five original model owners, never reports successful cleanup |
| Captured JS object graphs / GC heap / guest C++ allocations | Aggregate guest linear-memory growth admission through TrackingLimiter | Count ceilings do not measure reachable graph size, allocator slack or GC heap bytes per object | Unchanged aggregate memory protection; no claim of per-owner byte measurement or complete capture instrumentation |
| Native/JS stacks and host structures | Existing native stack and NativeMemory admission, plus original host-memory envelope | Conservative sizes/escrows and separate stack retirement observations | Unchanged; no new stack or host allocation introduced by these fixes; complete physical coverage remains to be proved |
| Store teardown / pool quarantine | Original activation ledger and allocation guards | HostState owner table can drop before guest instance backing; failed runtime finalization need not quarantine the execution report | **Unresolved.** This increment does not provide physical Store custody or a per-Store pool-decommit acknowledgement |

## Budget mapping and lifecycle

`ActivationBudget` is the existing authority. The bridge does not mint a new
activation, deadline, profile or resource ledger. The relevant independent axes
are the original owner-count ceilings, execution fuel/deadline, and shared
memory envelope. An owner-count admission is not a byte reservation for an
arbitrarily large object graph.

`crates/latent-wasmtime/src/host.rs::TrackingLimiter::memory_growing` reserves
aggregate runtime memory before growth, including concurrent memories, and
retains or rolls back pending growth using its existing success/failure paths.
SpiderMonkey GC cells, JS arrays/closures and this guest's C++ heap reside inside
the Wasm linear-memory envelope. This is an aggregate addressable-memory charge,
not live-object attribution, allocator RSS, or a measurement of every external
engine allocation.

`crates/latent-wasmtime/src/host/runtime.rs::Table::new` prepays bounded owner and
timer vector backings and checks their capacities. The table is lazily created.
`native_tables.rs` supplies original-ledger guards for engine allocations using
its existing finite allocator-bookkeeping/owner escrows. `native_stacks.rs`
separately admits stack resources and observes their retirement. These are
existing mechanisms, not new proof supplied by this patch.

For timers, the order is Native admission, record/capture construction, Timer
admission/start, readiness acquisition when needed, callback Task/QueuedWork
admission, native callback return, canonical terminal/unjoin/drop, record/root
destruction, and finally the original Native ACK. Clearing a timer only closes
eligibility; it does not permit early buffer release. A nested clear cannot
retire the currently executing callback's roots.

For imports, record Native admission precedes record allocation. Lifecycle
admission precedes parameter/result buffers and captures. Lowering, parking,
physical return and lifting are separate states. Typed disposition must be
known before cleanup; a disposer is never replayed after an uncertain call.
Only after terminal subtask/drop and record/buffer/root destruction may the
Result/lowering Native/record Native tokens be acknowledged. A refused ACK
retains the exact token even though its physical storage is already gone. The
next record cannot displace that debt.

`cancelAll` closes admission before cleanup starts. After any cleanup refusal,
`turn`, `beginLowering` and `beginLifting` return the respective
`activation-runtime-import-{turn,lower,lift}-after-stop-invalid` diagnostic.
Cleanup retries use `cancelAll`; readiness can record physical terminal events
without reopening application dispatch. Existing pending exceptions are
preserved. Native reservation reuse reports
`activation-runtime-promise-native-readmission-denied` with the original invalid-state
code, without another register call.

## Executed controls and measured model costs

Run the maintained CI entry point:

```sh
python3 -m unittest tools.tests.test_typescript_record_retirement -v
LSF_TYPESCRIPT_RECORD_CXX=clang++ python3 -m unittest tools.tests.test_typescript_record_retirement -v
```

The new `OwnerRetryTests` class is in that existing module. Its C++ source is
under the existing `sdk/typescript-guest/**` filter, and its JSAPI declarations
are under the existing `typescript_record_retirement/**` fixture filter. No
new CI lane, exact-test-count gate, or duplicated test-module discovery is needed.

The 23 new semantic cases cover repeated timer clear/cancel ACK refusal; capture
OOM before host effects; late return after cancellation; nested timer clears;
Native budget exhaustion; each of the three import retirement ACK stages;
post-stop turn/lowering/lifting refusal; partial count and partial buffer
admission; non-retryable disposal quarantine; lazy manager construction; twelve
fresh model generations with stale-token refusal; live reservation readmission
in activation and snapshot phases; accepted work after root settlement; and
callback false/exception paths.

With the three original production headers, twelve cases fail and eleven
controls pass. With this patch all 23 pass under GCC 14.2 and Clang, including
Clang AddressSanitizer plus UndefinedBehaviorSanitizer with leak detection and
halt-on-error enabled. The 15 pre-existing retirement tests also pass. Seventy
adjacent import, scheduling, Promise-library, timer-race and Event/Abort tests
pass. One initial adjacent failure was a missing unchanged workflow input in
the retained source archive; restoring its exact base blob
`042d6615be2c0dbb9b51c16b26e2eb387feae7ef` resolved that environmental failure.

Measured on the x86-64 finite-double build, before and after respectively:

| Measurement | Before | After |
| --- | ---: | ---: |
| `sizeof(Timers)` | 120 bytes | 120 bytes |
| `sizeof(Imports)` | 136 bytes | 136 bytes |
| `sizeof(BrokerPromiseAccounting)` | 32 bytes | 32 bytes |
| Lazy manager construction: Native admissions / lowering-buffer bytes / callbacks | 0 / 0 / 0 | 0 / 0 / 0 |
| Capture allocation refusal: host timers created | 1 | 0 |

These sizes include finite JSAPI substitutes where applicable, not actual
SpiderMonkey/Wasm32 layouts. The two-import model uses 40 actual allocated
parameter/result bytes and a peak of four Native model owners; its fake Promise
creation does not instrument actual Promise GC allocation. Partial buffer
failure retains 16 allocated bytes until cleanup. The deliberate failed-disposer
case retains five original logical owners; its 20-byte buffer remains until the
local manager scope is destroyed. That scope exit is explicitly not evidence
of a real Store's safe physical retirement. No retained-byte/RSS, Wasm fuel,
full-engine latency or signed-component cost claim follows from these numbers.

## Remaining qualification and implementation gaps

The following are unresolved obligations, **not** classes newly disabled at
runtime by this increment:

1. **Store custody and original token lifetime.** At the base commit,
   `crates/vendor/wasmtime/src/runtime/store.rs::Drop for Store<T>` destroys
   user HostState before StoreOpaque/instance backing. Dropping RuntimeOwner
   entries can therefore refund Native counts before captured guest storage
   physically retires. Simply reordering destructors is not an adequate fix:
   cancellation/capability resources can depend on that ordering. A bounded
   original-owner custody design must cover success, trap and abandoned futures.
2. **Failed physical cleanup and reuse.** Pooling decommit failure is not a
   per-Store retirement acknowledgement to the owner table. Cell quarantine
   records identity/reason rather than retaining the Store and all original
   reservations. `backend/input.rs` bases reuse on capability/native-stack
   observers; the separate runtime-finalization error in `backend.rs` can
   produce a lifecycle trap without independently closing cell reuse. This
   requires a trusted fail-closed disposition plus actual physical custody,
   not parsing a guest trap string or calling Store drop a cleanup certificate.
3. **Complete capture/engine accounting.** Generic Promise combinator element
   callbacks retained by custom thenables, engine/native allocations outside
   guest linear memory, reachable passive captures after root settlement,
   JS/native stack peaks, host lowering/provider result backing and allocation
   slack still need complete original-budget attribution and retirement proof.
   The base intrinsic hooks and 64-owner ceiling alone do not establish that.
4. **Actual execution qualification.** Rebuild and run the modified headers
   against the pinned SpiderMonkey and selected signed component. Exercise real
   GC reachability, Wasm trap/abandonment, cleanup refusal, repeated activations
   and fresh cross-tenant execution. Existing downloaded engines were built
   before this patch and cannot validate it. No actual modified-engine run was
   completed for this increment.

The existing `activation-runtime-unselected-native-async-task-denied` and
`activation-runtime-opaque-pending-work-on-close` diagnostics remain in force,
but they do not close these gaps. Keep #745 open and do not promote the current
profile on the strength of these local controls.
