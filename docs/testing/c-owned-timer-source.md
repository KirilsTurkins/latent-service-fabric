# Selected C timed-wait source

The owned C profile now has source for pthread/C11 mutex deadlines, condition
timeout and reacquisition, `nanosleep` and `thrd_sleep`. This timed branch has
not executed as a signed component and remains unqualified. It requires both
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
one newly captured clock-selected component and the exact 146-control native
products. It preserves the original twenty lifecycle/synchronization outcomes,
then appends twelve pthread/C11 sleep, mutex timeout/handoff and condition
notification/timeout/reacquisition cases, three independent clock/entropy
authority denials and a fresh timed call. The source fixture also checks lazy
zero sleep, invalid duration/remaining output and errno preservation. The
32 MiB / one-billion fuel / five-second envelope and original runtime owner
limits stay fixed. This programme is pending actual execution; source checks
and a zero-warning fixture object compile do not qualify those outcomes.

Timer-budget exhaustion, timer-specific cancellation/deadline barriers,
recurring callbacks, cross-tenant reuse and published/transitive libraries
remain required beyond this finite programme.

A separate serialized source regression compiles the actual synchronization
implementation with the pinned public WASI headers and explicit broker/canonical
doubles. During the first timer-stop it expires and poisons a later wait node,
then publishes a new waiter. The broadcaster must reread the live queue and
leave the newer sequence untouched. This source control passed; it does not
claim canonical execution, original-ledger execution or signed qualification.
