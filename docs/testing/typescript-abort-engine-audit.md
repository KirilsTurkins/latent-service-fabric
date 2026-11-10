# AbortSignal engine and lifetime audit for PR #1852

## Scope and qualification boundary

Agent 2's branch starts at `83c339673b87afabfa06f3a8e818324f46c1ae6f` and targets
`feat/typescript-runtime-745`. Local tests use the retained source archive from
run `42516280360`, synthetic merge `6ab3da5364ac3e7db57c7154f894bc6223ad728b`,
with the Agent 2 delta. The owned TypeScript baseline blobs were checked against
the branch head; the archive is not relabeled as that exact complete Git tree.

Reviewed pins are StarlingMonkey `9dda8ba7fcda2e17c6795d402f0478cf4c1f7f37`,
SpiderMonkey `9dab3d6f643e926a340c391ea30968e940390dec`, and ComponentizeJS
`4b8d6eb465b5cded6b97c67aaf6fdaa8b62001e2`. The actual retained SpiderMonkey
headers were inspected, including `js/RootingAPI.h`, `js/Exception.h`, the
rooted-vector definitions, and construction/object-slot declarations.

**This is not completed engine or signed-component qualification.** The changed
full engine has not been compiled or run. Emitted-C++ controls use finite JS,
GC, allocator, and host doubles. The separate trap witness executes real Wasm
but does not include SpiderMonkey, a native heap allocator, or the LSF Store.
No grant, budget, owner API, signed probe, or qualification flag is expanded.

## Corrected production defects

### Saved exception roots must obey LIFO

The earlier fan-out loop could lazily construct `JS::AutoSaveExceptionState`
inside a per-iteration `RootedObject` lifetime, then destroy that signal root
before the saved exception-stack root. The pinned `Rooted` destructor requires
the top of its per-kind root stack to be the object being destroyed. This was
not merely a missing root: it was incorrect destruction order.

The implementation now declares a reusable signal root before the lazy saved
exception state. The saved value and stack are destroyed first on every exit.
The root-aware control reproduces the defect in the original PR implementation
when the first failure occurs in a dependent; root-first failure and ordinary
heap fan-out are comparison controls. No extra heap container is introduced.

### Native booleans and pending exceptions must agree

`abort` and `run_abort_steps` reject entry with a pending exception. Each native
algorithm, event creation, and dispatch result is checked for both its return
value and pending state. A native `true` cannot hide a pending exception or
allow the next callback to run with that exception pending.

The first catchable abort-step failure is saved with its original value, stack,
and status. Eligible independent dependent signals run after the pending
exception is cleared. Later catchable failures do not replace the first. Tests
include thrown `undefined`, OOM/over-recursion status, nested dependent errors,
and a later refused acknowledgement. A failed signal's own algorithm list
remains retained; subsequent algorithms and event dispatch on that signal are
not claimed to have completed.

A native `false` without a catchable pending exception fences further work and
drops the saved catchable state instead of restoring it over termination.
The finite ForcedReturn control exercises this distinction. Finite controls
called `trap` in the abort fixture simulate a native return; they are not the
separate real Wasm trap witness.

### EventTarget must not swallow native termination

Both original `JS::Call` results in `inner_invoke` were discarded. A native
false/no-pending result could therefore reach subsequent listeners before
AbortSignal learned of any failure. Both callback forms now retain the result,
stop on native termination, restore passive state, and perform once-listener
cleanup. Property lookup also rejects a success-with-pending result.

Ordinary catchable event-listener exceptions retain the original DOM reporting
behavior; they are not converted into newly propagated abort exceptions.
Dispatch completion restores event state before returning failure. The new
controls execute the complete emitted callback dispatcher, not just its cleanup
fragments.

### Default exception construction must check native boundaries

The pinned [DOMException factory](https://github.com/bytecodealliance/StarlingMonkey/blob/9dda8ba7fcda2e17c6795d402f0478cf4c1f7f37/builtins/web/dom-exception.cpp)
uses unchecked string/constructor results and writes reserved slots without
validating a user-constructor result's native class. AbortSignal now uses a
local guarded factory for AbortError and TimeoutError. It roots the string
arguments, checks lookup/construction and pending state, validates the result
class, then writes slots without further allocation or user code.

Constructor lookup and reentry remain observable. No weak-set iterator or
fan-out snapshot is retained across default construction. The reason remains
rooted; after reentry, a completed nested abort wins without reason overwrite
or duplicate callbacks. Factory controls cover allocation, lookup, native
termination, catchable errors, true/pending, null, and wrong-class results.
The general DOMException factory used by other APIs is not changed here.

## Ownership and publication transitions

The [DOM abort algorithm](https://dom.spec.whatwg.org/#abortsignal-signal-abort)
propagates a shared reason to eligible dependents before running the root's
steps, then runs the dependent snapshot. This implementation stages reservation
before those reason writes so a refused resource or backing allocation does
not partially publish the abort graph.

| Boundary | Required behavior and evidence |
| --- | --- |
| Empty, already-aborted, or up to eight pending dependents | No heap fan-out owner; existing reasons and skipped work remain unchanged. Exact zero/eight/nine boundaries are exercised. |
| Heap fan-out | Original-activation native admission precedes reserve. Counting, reserve, and snapshot filling precede all reason writes. No second uncharged heap vector is introduced. |
| Admission or reserve failure | Root/dependent reasons and algorithm lists remain unchanged; no callbacks. An admitted record is retained until normal destruction and safe acknowledgement. |
| Publication | Normalized non-undefined rooted reason is shared by identity. Slot writes do not invoke user code or allocate. All selected dependents are aborted before root callbacks. |
| Callback graph mutation | The rooted snapshot retains selected dependents despite removal from the source graph; later insertion does not grow the current dispatch. Reentrant aborts of already-marked dependents do not repeat work. |
| Nested fan-out | Each heap frame has its own original owner; an inner checkpoint cannot release the outer live backing. Nested refusal leaves the refused graph unchanged. |
| Normal return/unwind | Frame lease is declared before its vector. The vector/backing is destroyed before frame retirement; acknowledgement happens only at a safe checkpoint. |
| Refused acknowledgement | Original custody remains retained, admission stops, and retry does not double-release. These are production retirement-header controls with finite host acknowledgements. |
| GC-owned graph containers | Physical finalization and actual collection completion remain prerequisites for safe release. This audit does not synthesize either event. |
| Wasm trap | C++ frame destruction is not established by ordinary RAII. The real witness proves that a trap skips both body and frame-lease destructors and stops the second callback. Store-lifetime custody is still required. |

The pinned [WeakIndexSet](https://github.com/bytecodealliance/StarlingMonkey/blob/9dda8ba7fcda2e17c6795d402f0478cf4c1f7f37/builtins/web/abort/weak-index-set.h)
strongly traces its edges before weak tracing. This is conservative retention,
not proof of genuinely weak graph collection. The DOM standard specifies weak
source/dependent sets with a separate listener/algorithm liveness rule. Removing
strong tracing without implementing and proving the collector's required weak
processing is not a safe fix. Actual weak collection remains an open audit item;
finite vector mutation is not collector evidence.

## Compiler and sanitizer evidence

Observed locally on 2026-11-09: GCC 14.2.0 and Clang 17.0.0 each pass the same
101-test matrix, with no skips. This is a recorded run result, not a required
future test-count inventory. GCC was run in three groups (27, 54, 20) because
of the local command time limit. Clang ran the matrix in one command.

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

Use `LSF_TYPESCRIPT_RECORD_CXX=g++` for GCC. Native controls compile with
`-std=c++17 -Wall -Wextra -Werror`. The abort cases include strict root-stack
checks, first-error preservation, nested custody/refusal, graph mutation,
default reentry, pending/native-return failures, and capacity boundaries.

The focused event-ownership and AbortSignal.any modules pass 27 tests with
Clang ASan+UBSan, `-fno-omit-frame-pointer -g -O1`,
`ASAN_OPTIONS=detect_leaks=1:halt_on_error=1`, and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`. No allocator-mismatch or leak
suppression is used. The real Wasm witness separately uses Clang's freestanding
wasm32 target and Node v22.16.0; that witness is not ASan-instrumented.

An earlier broader sanitizer run exposed the existing record-retirement test
fixture's missing nothrow-new pairing with its free-based delete override.
Agent 5 fixed that separately in `ddae8e8799f182c2839a83a9e548b615f9267380`
(PR #1928). This branch neither duplicates that fixture change nor claims its
own broader sanitizer run passed. Re-run the combined matrix after integration.

## Remaining integration blockers

**Full pinned-engine compilation and execution:** retained headers/library are
not a rebuild of this patch. The local environment lacks the pinned WASI SDK
and a complete Starling build tree; direct network acquisition was unavailable.
The isolated hash-verified input acquisition run `42697022631` was still queued
at the final evidence check, with no artifact. Its temporary workflow is not
part of the final integration delta. A queued job is not passing evidence.
Fresh native default-reentry, refusal, GC, and signed-component cases remain
required; this audit does not establish the cause of the historical signed
`abort-fanout-refusal` trap.

**Store destruction order:** in the inspected retained checkout,
`crates/vendor/wasmtime/src/runtime/store.rs` drops the Store's user data before
`StoreOpaque` deallocates instances/linear memory. `HostState.runtime` can thus
drop original RuntimeOwner entries before backing containing trap-abandoned
fan-out vectors is destroyed. A fresh Store per invocation alone does not
prove release-after-destruction. This concrete gap was reported to Agent 3;
its #1931 handoff also leaves it open. After-Store custody, pool decommit,
refused cleanup, and any cell reuse need actual host/allocator evidence, not
fabricated guest GC or destructor completion.

**Weak graph and same-signal failure cleanup:** collector liveness/weakness and
retirement of retained failed-signal algorithm lists still need actual engine
validation. Conservative retention is not silently completed work. No generic
engine/native/stack/host byte-accounting claim follows from a native-count
lease or these tests.

Keep PR #1852 and issue #745 acceptance open. Integrate the independent agent
changes, rebuild the exact pinned engine, retain source/compiler/component
identities, and run the unchanged-budget signed programme before promotion.
