# TypeScript ordinary timer and AbortSignal races

This finite #745/#736 campaign preserves the named Promise/import engine,
compiler-owned standard globals and original 16-task/16-queue/8-timer/64-native
owner profile. It builds one new captured component using authenticated existing
engine/splicer/native products. Their historical0754391 provenance stays explicit;
no current engine/native build or release qualification is attributed to it.

Eleven signed calls comprise bootstrap, seven positive cases, a bootstrap under
the one-second caller deadline, a pending ten-second timer that must terminate
as root deadline-exceeded, and a fresh call under that same caller deadline.
The new cases cover actual AbortSignal.timeout/reason/throwIfAborted, manual abort
winning before a later timeout, already-aborted signals without event replay,
shared timer-handle clearing, microtask clearing of a zero-delay sibling,
checked timeout/iterable refusal followed by a valid timer, and an interval whose
synchronous first callback spans multiple periods through authorized monotonic
performance.now reads. The interval remains bounded/non-reentrant and clears
after three callbacks. This exercises the implemented fixed-rate/coalescing
profile; it does not expose private host queue length or count each missed tick.

Each result must be known and its CLI process reaped, followed by physical owner
and available-zero-provider barriers. Node shutdown and zero real peer contacts,
original source/product/recipe identities and existing limits remain mandatory.
The prior scheduling15, root-lifecycle24, resource-limit15 and late-fetch4 results
keep their own scope and are not rerun by this workflow.

The selected timeout conversion truncates finite milliseconds toward zero and
returns TypeError for out-of-range/nonfinite values or nanosecond overflow,
before timer admission. This explicitly differs from Node's RangeError and
its delay clamping/unref semantics. The source controls refuse successful,
cancelled, fuel-exhausted, unknown and unreaped substitutes for the required root
deadline result. No actual campaign pass is claimed before its exact hosted
result is authenticated. Full cost, snapshot, published-library, cross-tenant,
networking and broader retirement requirements remain separate ticket work.
