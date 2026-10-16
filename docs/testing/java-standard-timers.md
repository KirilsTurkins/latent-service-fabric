# Java standard timer qualification

This candidate extends `teavm-activation-fibers-v1` with ordinary
`java.util.Timer` and `java.util.TimerTask`. Application imports and callback
source remain unchanged. The maintained compiler installs the owned timer bodies
on TeaVM's existing canonical standard classes for every caller; it does not
recognize approved application packages. It validates the pinned class-library
layout before changing either model and preserves the SDK source models.

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
they do not establish Wasm execution or host cleanup. A further control reads the
actual verified TeaVM models without initializing application or port classes.
It checks standard API and private helper identities, method and field reference
closure, unsupported members, and original-layout and repeated-port negatives.

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
2026-10-16. The actual locked model control also passed with the ten tooling JARs
verified against the existing compiler lock. The [first encoder failure](evidence/java-standard-timer-encoder-failed-2026-10-16.json)
and the [subsequent actual-core inspection and repair](evidence/java-standard-timer-adapter-2026-10-16.json)
passed TeaVM and C compilation, then exposed missing closed descriptor functions.
The adapter now covers the exact compiled module's descriptor imports, returning
`BADF` without changing caller memory or acquiring an ambient resource. The
retained real core successfully encodes as a component and validates with pinned
wasm-tools 1.254.0. The next maintained gate compiled and validated the component,
then exhausted the original 10-billion fuel ceiling in its first signed timer
mode. No timer mode is counted as qualified by that failed run.

The retained component and an isolated run of the actual locked C dependency
analyzer both lacked the worker introduced by a method-reference lambda in the
replacement constructor. The constructor now uses an explicit private worker,
with its captured timer reference normalized to the same standard class. The
new compiler graph regression retains the worker and application callback and
emits C without compiler problems; the identical control rejects the retained
original implementation at its missing-worker assertion. All original model
guards, three reference and SDK source rounds, twelve signed modes, runtime
limits and the 55-minute job remain intact. This source control verifies the
existing 70-JAR compiler lock (33,296,002 bytes) before loading the dependency
analyzer; it executes no Wasm or application initializer. See the
[failure and compiler regression evidence](evidence/java-standard-timer-worker-2026-10-16.json).
Fresh signed execution remains required for the correction.

The next hosted attempt stopped before compilation of the timer fixture: the
model helper demanded every reviewed JAR, while the C compiler had resolved 26
of the 70 reviewed artifacts. The reviewed inventory also includes unused
browser and server configurations. The helper now verifies the actual resolved
cache against the unchanged lock and strict Gradle metadata, still requires all
ten original model JARs, and retains the 96-JAR and 32-MiB bounds before hashing
or loading the closure. Duplicate, altered, unreviewed and missing required JARs
remain errors. Using only the exact 26-coordinate observed closure reproduced
the old missing-JAR failure, then passed the unchanged model and actual C
dependency-analysis controls with the correction. No dependency was acquired
for that host check. The [resolved-closure evidence](evidence/java-standard-timer-resolved-closure-2026-10-16.json)
records the retained inputs and the distinction between reconstruction and the
hosted cache, whose full member inventory was not uploaded. Fresh signed Timer
execution remains pending.

This slice does not complete issue #741. Fiber-aware pending host I/O, two
unchanged published libraries that create default workers, the broader
race/cancellation/limit/late-wakeup and tenant matrix, and a paired runtime cost
comparison remain separate acceptance obligations. `ScheduledExecutorService`
is not added by this timer slice.

The API behavior is checked against the reference JDK and the
[Java Timer documentation](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/Timer.html)
and [TimerTask documentation](https://docs.oracle.com/en/java/javase/17/docs/api/java.base/java/util/TimerTask.html).
