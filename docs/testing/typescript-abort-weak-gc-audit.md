# AbortSignal weak collection and callback lookup audit

Agent 2 continuation, 2026-11-10, based on published parent
`cc2d67be0d3606da718fcc4669cc889256171001` on
`fix/1852-agent2-abort-engine-audit` (PR #1934, target
`feat/typescript-runtime-745`). Publication initially lacked write actions;
resumption restored them and reran the controls below. No runtime, grant,
budget, deadline or signed probe is broadened. This is not qualification-ready
regardless of the PR UI draft flag.

## Corrections and custody

The pinned `WeakIndexSet` supplies a GCVector weak-sweep method but does not
register it with the runtime. The former class trace strongly traced both source
and dependent sets and then swept them from the same marking hook. It therefore
retained unobserved graphs and invoked a weak sweep in the wrong collector phase.

Each already-admitted weak-set container now embeds
`Maybe<JS::WeakCache<WeakVec>>`. Runtime registration is intrusive, allocation-free,
and precedes graph publication. The wrapper cannot be copied or moved. Cache
unregistration and vector destruction precede the existing first-member lease's
physical-retirement record. There is no additional staging vector or owner kind.

The marking hook no longer sweeps either set or strongly retains reverse source
edges. A source retains dependents with active abort listeners while non-aborted,
and with native algorithms even after abort: failed/unrun algorithms have not
completed their capture/cancellation obligations. Predicate reads are unbarriered
inside the trace hook, allocation-free, and never invoke JavaScript. Relocation
and nursery tracers update dependent edges before inspecting possibly forwarded
objects; nursery survival is conservative. Runtime caches sweep/update source
edges. These behaviors still need actual collector qualification.

AbortSignal uses `JSCLASS_FOREGROUND_FINALIZE` instead of inherited background
finalization. The runtime intrusive lists and unsynchronized retirement structures
must be mutated by their foreground owner. No new collection-completed callback
is introduced: physical destruction, actual collection-end notification, and the
outside-GC host acknowledgement remain distinct transitions.

Object-listener `handleEvent` lookup is now part of checked invocation reporting.
Catchable getter failure is reported without side effects and later eligible
listeners run with no pending exception. False/no-pending lookup termination,
exception extraction failure, and report failure still fence later callbacks.
Once/passive/dispatch cleanup remains intact. The published parent's emitted
dispatcher fails the new catchable-getter controls. A retained earlier linked
engine also reproduced the defect, but its finite-host shutdown was not a pass.

Agent 5's allocator pairing is reused byte-for-byte from commit
`ddae8e8799f182c2839a83a9e548b615f9267380`, blob
`2c1a882f2bed34704f24aef70f6af39fcee18d01`, for
`sdk/typescript-guest/activation/tests/record_retirement.cpp`. No sanitizer
suppression masks the old nothrow-new/free mismatch. Missing prerequisites in the
new listener control fail explicitly rather than being silently skipped.

## Executed validation

| Execution on restored final source | Result | Scope |
| --- | --- | --- |
| GCC 14.2 | 108 tests passed, no skips; 11.312s | Emitted/source and adjacent native controls |
| Clang 17 | 108 tests passed, no skips; 10.321s | Same selection |
| Clang ASan + UBSan wrapper | 108 tests passed, no skips; 16.424s | Relevant emitted C++ instrumented; leak detection and halt-on-error; no suppressions |
| Pinned WASI SDK 30 / Clang 21 | Three derived translation units compiled, exit 0 | abort-signal.cpp, abort-controller.cpp, event-target.cpp; not a complete link |
| Earlier real-JSAPI embedding attempt | Eight translation units compiled; execution not obtained | Interrupted link, no executable or runtime pass |

These counts and times describe observed runs, not required inventories. The weak
fixture executes the exact emitted set, trace and listener predicate with a finite
collector-phase/relocation double. It covers inline/heap unobserved sets, observed
listeners/algorithms, removed listeners, weak reverse edges, strong captures,
already-aborted failed work, next-collection changes, partial initialization,
relocation-before-inspection, unregister/destruction order and refused ACKs.
Explicit fixture collection-completion calls are GC doubles, not production GC.

```sh
LSF_TYPESCRIPT_RECORD_CXX=clang++ python -B -m unittest \
  tools.tests.test_typescript_event_ownership \
  tools.tests.test_typescript_abort_any_ownership \
  tools.tests.test_typescript_record_retirement \
  tools.tests.test_typescript_runtime_profile \
  tools.tests.test_typescript_native_build \
  tools.tests.test_typescript_native_await \
  tools.tests.test_typescript_native_carrier_scheduling -v
```

Use `g++` for GCC. The sanitizer compiler wrapper adds
`-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer -g`;
`ASAN_OPTIONS=detect_leaks=1:halt_on_error=1` and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`.

## Open proof gaps and handoff

Local tests use a retained synthetic merge source projection plus checked agent
deltas. Every touched preimage was verified; the whole tree is not relabeled as
an authenticated complete branch checkout. Pinned inputs are StarlingMonkey
`9dda8ba7fcda2e17c6795d402f0478cf4c1f7f37`, SpiderMonkey
`9dab3d6f643e926a340c391ea30968e940390dec`, acquisition run `42697022631`, and
library run `42704134881`. The omitted configuration header was reconstructed
from config.status macros, not claimed as original-byte identity.

The new complete engine has not been linked/executed. Retained link inputs omit
normal Mozilla allocator/MFBT/mozglue objects and Rust static libraries. Major,
minor, incremental, and compacting GC and final linked failure injection remain
unverified. Compile receipts and exported-symbol inventories do not close this.

Agent 3: weak caches add in-place bytes to counted containers. Include them in
aggregate byte attribution. Preserve foreground destruction and failed/unrun
custody; weak collection is not cancellation. Actual Wasm traps bypass C++ stack
destruction. Store backing release order, retained lease custody, pool quarantine,
decommit, refused host cleanup and safe reuse remain unproved here.

Agent 5: the allocator blob is already your correction; do not create a competing
fix. Preserve the integration missing-compiler guard when applying the test delta.
Rebuild the combined source before signed qualification. Agent 1's probes remain
untouched. Its prepared-source replay failure happened before guest execution and
is not evidence that the earlier signed refusal trap was fixed. No current full
signed pass is inferred from this continuation.

Semantic references: [DOM AbortSignal collection](https://dom.spec.whatwg.org/#garbage-collection),
[DOM listener invocation](https://dom.spec.whatwg.org/#concept-event-listener-inner-invoke),
and [Web IDL callback operations](https://webidl.spec.whatwg.org/#call-a-user-objects-operation).
Pinned API review includes `js/SweepingAPI.h`, `js/GCVector.h`, `js/RootingAPI.h`,
`js/Class.h`, and `mozilla/LinkedList.h`.
