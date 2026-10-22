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
