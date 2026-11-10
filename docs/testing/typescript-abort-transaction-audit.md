# Abort graph transactions and independent failure draining

Agent 2 continuation of PR #1934 / #1852, 2026-11-10, based on
`72a26d82c7a2e38b642e38cc1a26f264abe3a872`.

This report supersedes the partial-link-publication, `onabort` bookkeeping and
all-record retention observations in the earlier engine and listener-identity
audits. It does **not** qualify the final linked engine, signed LSF execution,
actual weak collection, aggregate bytes, or Store/trap custody.

## Corrected transactions

### Dependent graph construction

The previous `AbortSignal.any()` implementation checked individual insertions,
but published each reciprocal source backlink immediately. A later insertion
failure could leave a source retaining an unreachable, partly constructed
result. This matters especially because the pinned weak-set implementation
conservatively traces its entries strongly before weak tracing.

Construction now stages unique flattened sources in the result's **already
admitted source-set**, reserves space in **every** source backlink vector, and
only then sets the dependent flag and appends backlinks infallibly. No second
heap-backed staging vector or new owner is introduced. The SystemAllocPolicy
reserve operations do not run script or GC. Refusal leaves no published
backlink; already allocated capacity remains covered by the existing container
owner. This remains count/model accounting, not a byte-accurate bound.

Empty inputs, first already-aborted input/reason identity, duplicate sources,
nested dependents, preexisting pending errors, and failure at each of nine
staging/reservation positions are exercised. Previous incremental publication
fails the later-position negative controls.

### Property handler identity and receiver

`onabort` previously never updated its value slot; assignment accumulated
listeners, clearing did not remove them, and callbacks shared identity with
ordinary registrations. The property now holds a separate stable native
invoker. Replacing the value preserves its dispatch position; clearing removes
only that invoker. Function allocation, native admission and publication must
succeed before slot updates. Original values remain rooted through reentry.

The property follows Web IDL's LegacyTreatNonObjectAsNull conversion: primitive
values become null; non-callable objects remain the stored value but invoke as
a no-op, without `handleEvent` lookup. The invoker passes the signal as receiver
and handles a Boolean false return using the Event cancellation operation.
Function listeners also now receive `event.currentTarget`, not the engine
global. Object-listener `handleEvent` receivers are unchanged.

The added JS function/slot uses the actual engine's GC roots; the existing
listener record retains its native lease through dispatch clones and physical
destruction. There is no new global owner kind or accounting-interface change.

### Catchable failures within one signal

`run_abort_steps` previously stopped at the first algorithm failure, suppressing
independent algorithms and the abort event and retaining completed records.
It now preserves the first exception value, stack and status, clears pending
state before each eligible independent step, and drains those steps. A later
catchable error cannot replace the first; false/no-pending native termination
drops the saved catchable state and fences all remaining callbacks.

Completed records are compacted into a prefix **inside the existing vector**.
No extra temporary vector, null trace entry or owner is introduced. All captures
remain physically alive while algorithms run. At the drain boundary, only the
completed prefix is destroyed. Failed and unrun records retain their original
order, leases and trace edges because they can still capture accepted work.
They are not marked completed, silently discarded or retried implicitly.
All persistent event roots precede the lazily engaged exception-state roots.

Finite controls use the production NativeLease/retirement implementation to
check completed destruction, failed-record custody, preserved thrown-undefined
and OOM states, later fatal termination, reentry, later event failure, and
refused ACK retention. Their explicit collection-completed calls are **GC
doubles**, not evidence of real collection or trap unwinding.

### Error reporting cannot conceal termination

The previous event dispatcher used a void engine logger with
`ErrorReportBuilder::WithSideEffects`, then unconditionally cleared pending
state. That could invoke user conversion and discard a reporting failure.
The dispatcher now checks exception extraction and report construction,
uses `NoSideEffects`, and fences subsequent callbacks on native or pending
failure. Once/passive cleanup remains intact. Ordinary successfully reported
listener exceptions still allow later listeners. This does not implement the
full HTML error-event reporting protocol; the carrier continues to log errors.

## Observed validation

| Execution | Result | Scope |
| --- | --- | --- |
| GCC 14.2.0 | 105 tests passed; no skips | Emitted C++ and adjacent native matrix |
| Clang 17.0.0 | 105 tests passed; no skips | Same matrix |
| Clang ASan + UBSan | 31 tests passed; no suppressions | Event/Abort and AbortSignal.any controls; leak detection enabled |
| WASI SDK 30 / Clang 21 | Three translation units compiled, exit 0 | Actual derived abort-signal.cpp, abort-controller.cpp and event-target.cpp against pinned SpiderMonkey headers |
| Retained linked native-import engine at earlier head 9636f2c | Five new mismatches reproduced; ordinary catchable continuation observed | Actual old engine, finite canonical host, not signed LSF |

Counts describe executions, not a required test-count inventory. The first
matrix run exposed a historical source-reversal assertion that expected the
old early-return implementation. It was replaced with untouched-method checks
and transaction/failure assertions; the emitted behavioral controls were
extended rather than weakened.

```sh
LSF_TYPESCRIPT_RECORD_CXX=clang++ python -m unittest \
  tools.tests.test_typescript_event_ownership \
  tools.tests.test_typescript_abort_any_ownership \
  tools.tests.test_typescript_record_retirement \
  tools.tests.test_typescript_runtime_profile \
  tools.tests.test_typescript_native_build \
  tools.tests.test_typescript_native_await \
  tools.tests.test_typescript_native_carrier_scheduling -v
```

Use `g++` for GCC. The focused sanitizer run uses the first two modules with a
compiler wrapper adding `-fsanitize=address,undefined -fno-omit-frame-pointer -g`,
`ASAN_OPTIONS=detect_leaks=1:halt_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`.

Pinned inputs are StarlingMonkey `9dda8ba7fcda2e17c6795d402f0478cf4c1f7f37`,
SpiderMonkey `9dab3d6f643e926a340c391ea30968e940390dec`, acquisition run
42697022631, and retained library/native-engine run 42704134881. The missing
`js-confdefs.h` was reconstructed from config.status definitions; this is
macro-equivalence, **not** original-header byte identity.

The old-engine diagnostic observed an incorrect onabort getter, accumulated
replacement listeners, failure to clear, wrong function receiver, and user
conversion during exception reporting. It subsequently failed the finite
host's incomplete activation-root protocol with
`activation-runtime-root-or-accepted-jobs-still-live` (17 owners; no refusal).
It is a negative reproduction, not a new-engine or successful-teardown result.

## Remaining proof gaps

A focused real-JSAPI embedding compiled the actual derived sources, but linking
against the retained `libjs_static.a` requires omitted normal Mozilla allocator,
MFBT and mozglue objects. No substitute allocator/glue was fabricated to claim a
linked-engine pass. The new complete StarlingMonkey engine has not been linked
and executed locally; rebuild and run the final integrated SHA normally.

Real Wasm traps still bypass C++ destructors. This change does not prove Store
owner-release ordering, backing deallocation, pool quarantine, refused host
cleanup or safe reuse. Failed algorithms deliberately retain custody; their
host cancellation/retry and eventual Store-lifetime obligations remain open.
Weak-graph collection and byte-accurate aggregate costs also remain unqualified.
The earlier signed refusal trap is not resolved by these local controls.
Agent 5's separate broader sanitizer-fixture correction remains an integration
dependency; only the scoped sanitizer pass above is claimed here.

Local whole-tree tests used the retained synthetic merge source archive
`26060bda5c60599ae9230216a0ff526ecf5420d6` plus the published 72a26d82 delta
and this continuation. Touched preimage blobs match the isolated branch;
the complete archive is not relabeled as that branch's exact tree. No signed
guest probe, workflow, runtime grant, owner ceiling or qualification flag is
changed. PR #1934 remains draft and issue #745 remains open.

## Semantic references

- [DOM: creating dependent abort signals](https://dom.spec.whatwg.org/#create-a-dependent-abort-signal)
- [HTML: event handlers](https://html.spec.whatwg.org/multipage/webappapis.html#event-handlers)
- [Web IDL: LegacyTreatNonObjectAsNull](https://webidl.spec.whatwg.org/#LegacyTreatNonObjectAsNull)
- Pinned `js/ErrorReport.h`: NoSideEffects forbids observable conversions;
  `init` follows ordinary JSAPI boolean error semantics.
