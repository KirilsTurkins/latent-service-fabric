# Java standard timer qualification

This candidate extends `teavm-activation-fibers-v1` with ordinary
`java.util.Timer` and `java.util.TimerTask`. Application imports and callback
source remain unchanged. The maintained compiler substitutes the exact standard
classes for every caller; it does not recognize approved application packages.

Each timer starts one managed logical Java worker. Its accepted queue entries
hold `queued-work` owners, and the timer holds an executor owner. Timed waits use
the existing activation timer bridge. Fixed-rate scheduling retains intended
scheduled times and catch-up callbacks; fixed-delay scheduling uses actual start
times. Tasks execute sequentially on their timer's worker. Ordinary cancellation
discards queued work without interrupting an already running callback. A task's
logical cancellation retains its queue owner until the worker or `purge`
physically removes the entry.

An empty timer is an idle managed worker. At root closure the existing activation
coordinator may retire it only after all ordinary accepted work and every
managed pool's pending work have drained. The worker wakes and executes its real
`finally` before its original task ownership settles. Accepted one-shot callbacks
continue after root return. An uncancelled recurring task remains accepted work
and is subject to the original activation deadline and resource limits.

## Maintained checks

`tools/qualify_java_fibers.py --fixture timers` executes the unchanged standard
application on the reference JDK three times. Its four modes cover independent
workers and thread locals, fixed-rate and fixed-delay recurrence, accepted work
after root return, and cancellation of running and queued work. Reference-process
cleanup belongs to `Main`; the component's application does not call an LSF
shutdown API.

A separate host source control maps only a private copy's imports to the actual
SDK timer sources. It uses a strict private owner ledger to check queue-admission
rollback, cancelled-task removal and real worker retirement. Those declarations
never enter the component. Three passing source runs establish source behavior;
they do not establish Wasm execution or host cleanup.

The selected signed test
`signed_java_standard_timers_recur_cancel_and_drain_owned_workers` checks exact
application bytes and the compiler receipt, then runs all four modes three times
on the ordinary signed Java runtime fixture. It retains the existing five-task,
three-executor, eight-queued-work, eight-wait, two-timer, eight-result and
two-native-owner ceilings, fuel, memory and 120-second execution deadline. Every
invocation must return 42 and satisfy the existing physical-idle assertions.
Timed recurrence controls run serially within the original two-timer limit.

The Java authoring workflow adds preparation and signed execution to its existing
55-minute job. Earlier commands, limits and security controls remain in place.
The new source and component receipts, exact application, compiler logs and
signed runtime log are retained even on failure.

## Current evidence and remaining scope

Reference JDK 25.0.3 and SDK host source controls passed three times locally on
2026-10-16. Component compilation and signed execution of this candidate are
pending the maintained Linux gate. This page makes no passing guest claim.

This slice does not complete issue #741. Fiber-aware pending host I/O, two
unchanged published libraries that create default workers, the broader
race/cancellation/limit/late-wakeup and tenant matrix, and a paired runtime cost
comparison remain separate acceptance obligations. `ScheduledExecutorService`
is not added by this timer slice.

The API behavior is checked against the reference JDK and the
[Java Timer documentation](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/Timer.html)
and [TimerTask documentation](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/TimerTask.html).
