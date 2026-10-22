# Selected C timed-wait source

The owned C profile now has source for pthread/C11 mutex deadlines, condition
timeout and reacquisition, `nanosleep` and `thrd_sleep`. This timed branch has
not passed its signed programme and remains unqualified. It requires both
`c-context144-sync-cooperative-v1` and the explicit standard clock/entropy or
combined facilities profile. It does not install ambient clocks or grants.
The untimed profile retains its existing selected behavior; timed methods there
continue to refuse support.

The compiler owns the clock-selection macro and sleep symbol namespace. Nine
additional original libc clock/type/condition-attribute inputs have separate
stable labels and are rechecked after the build. WASI clock IDs are pointers;
the original condition attribute stores their numeric clock ID. Realtime and
monotonic condition clocks use the original libc representation. Mutex and C11
condition deadlines use realtime. Invalid timespecs and arithmetic overflow
are refused before releasing a condition mutex.

A real original Wait is admitted before any waiter is published on the paid C
stack. Its one-shot Timer is a continuation of that Wait; `timer-next` owns its
additional original physical Wait. The actual engine host await parks only its
calling thread. Notification unlinks and installs handoff/state before claiming
and stopping the exact Timer, with no node access after the potentially
awaiting stop. A thread with a live timer host future is never manually promoted.
Timeout unlinks before retirement, and condition wait retains the same Wait
through untimed mutex reacquisition. Global cancellation/deadline cannot be
converted into requested elapsed success.

The pinned actual WASI-header object compiles with warnings as errors. An
initial compile caught the incorrect assumption that WASI clock IDs were
integers; that failed attempt is retained separately. Actual pinned preprocessing
shows all 13,177 untimed C tokens equal the original development source. Twelve
profile controls retain their original cases/guards and add explicit clock
selection and original-input revalidation. These checks establish source/ABI
behavior only. They do not execute canonical timer waiting or the original
ledger, and no guest/native runtime was run locally.

The required next programme is one normally captured signed component retaining
the original twenty lifecycle/synchronization outcomes, with actual timed
mutex success/timeout, condition notify/timeout/reacquisition, independently
runnable siblings, timer/Wait refusal, cancellation/deadline and fresh calls.
It must retain original limits, actual provider/physical retirement and exact
compiler/libc/native identities. Recurring callbacks, ordinary cancellation
unwind, compiled CPU checkpoints, sockets and unchanged published/transitive
library qualification remain separate open requirements of #744 and #736.

The next owning programme is `.github/workflows/c-timed-runtime.yml`. It uses
one newly captured clock-selected component and the exact 163-control native
products for its initial attempts. It preserves the original twenty lifecycle/synchronization outcomes,
then appends twelve pthread/C11 sleep, mutex timeout/handoff and condition
notification/timeout/reacquisition cases, three independent clock/entropy
authority denials and a fresh timed call. The source fixture also checks lazy
zero sleep, invalid duration/remaining output and errno preservation. The
32 MiB / one-billion fuel / five-second envelope and original runtime owner
limits stay fixed. Actual run `39854116727` built and signed the component and
passed all original twenty outcomes, then trapped at the first timed preflight.
Its first entropy result requires canonical allocation. Wasmtime deliberately
clears component context slots during canonical `realloc`; the selected C ABI
incorrectly forwarded this live-root allocation to stack/TLS helpers requiring
that context. Its existing System stack also aliases the root stack, so switching
only the scope flag is unsafe. A distinct bounded original-memory System stack
and rebuilt compiler tooling are required before retrying. This failure is not
a signed timer qualification; all failed artifacts remain retained.

The corrected attempt consumes the verified 172-control native products from
`ce8c04a7d9fdf3be79e16b2f9a26803b97a7e3e1` (run `39859151957`). Their C
transform reserves separate 64 KiB Root and System stacks inside the original
bounded linear memory and rejects live canonical allocators requiring TLS.
The native controls passed. Signed run `39863159247` then passed all 36 outcomes
on `02478e6e4354323d9a30f7fa1b46240b96a8bcff`: one captured 2,078,955-byte
component, 26 successful build commands and all original twenty cases plus
sixteen timer/authority/fresh cases. All 36 calls have complete retirement,
five physical owner counters and eighteen active provider counters at zero,
followed by clean node/peer shutdown. The
[source-bound observation](evidence/c-timed-runtime-signed-2026-10-22.json)
retains actual input, compiler, native and artifact identities. A separate
CI failure exposed cumulative child-budget retention by physically retained
session headers, so these products do not establish complete retirement.

Timer-budget exhaustion, timer-specific cancellation/deadline barriers,
recurring callbacks, cross-tenant reuse and published/transitive libraries
remain required beyond this finite programme.

A separate serialized source regression compiles the actual synchronization
implementation with the pinned public WASI headers and explicit broker/canonical
doubles. During the first timer-stop it expires and poisons a later wait node,
then publishes a new waiter. The broadcaster must reread the live queue and
leave the newer sequence untouched. This source control passed; it does not
claim canonical execution, original-ledger execution or signed qualification.
