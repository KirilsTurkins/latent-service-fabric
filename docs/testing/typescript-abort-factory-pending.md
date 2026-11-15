# Abort factory pending-exception fence

Continuation of #1934 on 2026-11-11, after the parent CI repairs.

The separate AbortError/TimeoutError helper checked a null string result but
not a pending exception before looking up the mutable DOMException constructor.
The shared DOMException factory already guards both conditions. The abort helper
now does the same, preserving the original exception before possible reentry.

The emitted-factory fault double supplies a non-null string with a pending
exception. Both AbortError and TimeoutError cases reproduced a forbidden
constructor lookup before the change, and pass after it. This is defensive
native failure-boundary evidence, not a claim that an ordinary string allocation
has been observed to return this combination in the real pinned engine.
The existing factory controls still cover null/OOM, native false/no-pending,
constructor reentry, wrong native class, first failure and slot-write ordering.

GCC and Clang ASan/UBSan each passed the 37-test selection comprising
`test_typescript_event_ownership`, `test_typescript_dom_exception_ownership` and
`test_typescript_abort_any_ownership`. Leak detection and halt-on-error remained
enabled. These are finite JSAPI controls plus the existing real Wasm trap
witness; they are not a linked SpiderMonkey collector or signed LSF execution.

No native owner kind, admission budget, exception identity, signed success
predicate or public support status is changed. Final integrated linked/signed
qualification and failed-decommit custody remain separate open obligations.
