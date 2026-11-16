# Abort listener identity audit - Agent 2 continuation, 2026-11-10

This supplements `typescript-abort-engine-audit.md` for PR #1934, targeting
`feat/typescript-runtime-745`. It does not complete #745 or qualify a supported
runtime profile. The continuation starts at `9636f2c26112be311c4bee3353d68688ee1b524c`.

## Actual-engine findings and corrections

Executing the retained native-import engine from run **42704134881** reproduced
three listener bugs, without JavaScript/GC/vector doubles:

- Mutating the original options object's `capture` field after registration made
  abort removal miss the registered listener (one invocation, expected zero).
- Removing and re-adding the same callback under a new signal let the old signal's
  abort algorithm remove the replacement (zero invocations, expected one).
- A duplicate active registration with a different signal attached an additional
  abort algorithm that removed the original (zero invocations, expected one).

The changed `event_engine.py` emits an abort Terminator capturing the exact
`RefPtr<EventListener>`, not the original type/callback/options inputs. Removal
uses pointer identity and performs no JavaScript conversion, option lookup, or
callback. Duplicate active registrations return before admission and cannot
adopt another signal. Re-registration of a removed listener creates a fresh
record; it never reactivates a record retained in an active dispatch snapshot.
All fallible admissions and vector reservation still precede publication.

The captured strong native reference prevents address reuse from confusing old
and new registrations. It also intentionally retains the listener's existing
native lease until the abort algorithm and dispatch snapshots release the
physical record. The Terminator traces the target and retained listener edges.
Destruction is not collection completion and does not authorize a host ACK by
itself. Refused ACKs remain retained. No new owner kind, global accounting API,
grant, resource ceiling, signed probe, or network allowance was introduced.
Agent 3 was notified on #1931, comment 6762655930, of this retention edge.

## Evidence boundaries

| Check | Observed result | Scope |
| --- | --- | --- |
| GCC 14.2.0 matrix | 102 tests passed, no skips | Emitted C++ and adjacent controls |
| Clang 17.0.0 matrix | 102 tests passed, no skips | Same matrix |
| Clang AddressSanitizer + UndefinedBehaviorSanitizer | 28 tests passed | Event/abort and AbortSignal.any controls; leak detection enabled, no suppressions |
| Pinned WASI SDK 30 / Clang 21 | Three translation units compiled, exit 0 | Actual derived abort-signal.cpp, abort-controller.cpp and event-target.cpp against retained pinned SpiderMonkey headers |
| Baseline linked engine | Three identity bugs reproduced | Real engine at the earlier head, not execution of this new identity patch |
| Broader sanitizer attempt including record retirement | 43 tests run, nine failures | Existing nothrow-new/free allocator mismatch in the separate fixture; not a pass |

The five new emitted-Terminator controls execute exact removal/idempotence,
replacement isolation, detached-record tracing and custody, a dispatch snapshot
outliving its abort algorithm, and refused acknowledgement retention using the
production `native_retirement.h`. These controls still use finite JS/container
doubles. Counts describe observed executions, not required test inventories.

The compiler used StarlingMonkey `9dda8ba7fcda2e17c6795d402f0478cf4c1f7f37`,
SpiderMonkey/Firefox `9dab3d6f643e926a340c391ea30968e940390dec`, and the verified
WASI SDK 30 archive from successful input-acquisition run **42697022631**.
The retained library is SHA-256
`f004e2e59f59efcd99fccd132478873642d6b06487514594176da590d631659c`.
The missing `js-confdefs.h` was reconstructed from the retained `config.status`
defines: macro-equivalence is recorded, not original-header byte identity.
The continuation was **not linked into a complete new engine locally**: retained
inputs omit supporting library objects. The three compiled units do not replace
full linked-engine or signed-component execution.

## Refusal and trap observations

Run **42704134881**, head `9636f2c`, synthetic merge
`26060bda5c60599ae9230216a0ff526ecf5420d6`, produced normal CMake engine compile
receipts, but its signed Fetch job still trapped at `abort-fanout-refusal` after
15 completed cases. Artifact **13738632582** retains that failure. No cause or
post-trap cleanup is established by this continuation.

A direct Node WASI harness running the real retained engine with a finite
64-native-owner host reached both admission refusals, observed an unchanged
nine-dependent graph, removed fillers, and retried successfully in root-then-
dependent order. This is a diagnostic distinction, not an LSF host/Store test:
the harness intentionally does not implement the activation-root protocol and
ends with `activation-runtime-root-or-accepted-jobs-still-live`. It is not a
successful activation teardown or evidence that the signed failure is resolved.

Real Wasm traps still bypass C++ destructors. Physical destruction, refused
cleanup, pool decommit/quarantine, and Store-custody ordering remain open. No
frame unwind, GC completion, or safe Store reuse is fabricated. The pinned weak
sets' conservative strong tracing does not prove actual weak collection.
Unresolved source-audit follow-ups include failed-signal algorithm retention,
partial weak-link insertion cleanup, and onabort property-handler bookkeeping;
no complete DOM/runtime qualification is claimed.

## Reproduction

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

Use `g++` for GCC. The focused sanitizer run uses only the first two modules,
with a compiler wrapper adding `-fsanitize=address,undefined
-fno-omit-frame-pointer -g`, `ASAN_OPTIONS=detect_leaks=1:halt_on_error=1`, and
`UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1`. Agent 5's independent allocator
fixture correction in #1928 is an integration dependency, not a suppression.

Local full-tree tests used the retained synthetic-merge source archive plus the
continuation delta. Modified preimage blobs were checked against the isolated
branch; the archive is not relabeled as the exact branch tree. The final
integrated SHA must be rebuilt and rerun under unchanged budgets before any
qualification or draft-readiness claim.
