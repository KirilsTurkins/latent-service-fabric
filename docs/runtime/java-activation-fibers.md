# Java activation fibers

The opt-in `teavm-activation-fibers-v1` compiler selection starts ordinary
application code inside TeaVM 0.15.0's maintained C-backend fibers. It keeps the
existing Java compiler installation, component adapter, exact WIT comparison,
closed ambient effects and original 64 MiB Java activation ceiling. The complete
standard concurrency profile remains unqualified; default Java projects retain
their current supported profile.

The SDK-owned TeaVM compiler plugin reserves a shared-runtime task owner before
`Thread.start` queues its event. Actual thread completion settles that owner.
The original TeaVM continuation transformation saves GC roots and restores
current-thread identity. `isAlive` distinguishes an unstarted thread from a live
one; `join` loops after notifications, releases and reacquires the thread monitor,
and retains requested timeout and interruption behavior. Internal event deadlines
use monotonic time while ordinary application wall-clock reads remain wall time.

The activation pump closes when the root callback completes and drains accepted
logical threads before settling its own owner. An empty queue is checked against
accepted work before parking. Sleeping or daemon work still requires completion;
an opaque pending thread cannot produce a successful retirement. Guest Java
objects, continuation arrays and events remain inside the original accounted
linear-memory allocation. Shared runtime task/wait records retain their original
native reservations until actual physical destruction.

The pending SDK class-library implementation supplies `Executors.newSingleThreadExecutor`
and `newFixedThreadPool`, including ordinary `ThreadFactory` overloads. Each pool
has its own FIFO queue and honors its requested parallelism with lazy Java worker
fibers. Submissions reserve executor, queued-work and pending-result records;
blocked future and termination waits reserve wait records. A cancelled running
future keeps its pending-result owner until the callable's physical `finally`
finishes. Completed results and returned queued tasks stay inside the accounted
Java heap. All logical ceilings come from the explicit host runtime configuration.

`FutureTask` supports runnable/callable construction, pending get, timed get,
completion/error/cancellation, readable result state, and subclass `done` callbacks.
A callback runs outside the future's monitor, so another thread can read a
completed result while that callback blocks. `AbstractExecutorService` implements
standard submit, ordered `invokeAll` and first-successful-completion `invokeAny`.
Factories and class substitutions apply only to these exact standard classes;
application and library API references remain unchanged. TimeUnit conversions
saturate and finite waits preserve positive submillisecond timeouts.

Root completion closes independent admission, while accepted application threads
and running callbacks may still submit necessary continuations. Idle pool workers
remain available during that drain. Once no accepted application work remains,
the pump retires idle workers, executes their ordinary finally blocks, and settles
the executor owners. Starting retirement invalidates the queue delay calculated
before interruption, so the pump processes the newly offered worker callbacks
before parking. Explicit `shutdown`/`shutdownNow` and `close` keep their
standard rejection, queue-return, interruption and await-termination behavior.

Compiler checkpoints are selected from actual application class files and the
captured JAR closure, without a package allowlist or loading application classes
in the compiler JVM. The trusted javac parser reads declared packages; input
directory layout does not determine class ownership. Package/SourceFile ambiguity
fails closed. A bounded source-origin index and its digest are retained
with the compilation. SDK plugin services are separate from application compiler
extension services. Loop headers use the maintained Thread context-switch path.
Class initializers and explicitly unmanaged methods are excluded; their fairness
and non-suspendable boundaries still require qualification.

## Executable evidence

Prepare the actual component and unchanged reference JDK controls with the
existing pinned compiler tools:

```sh
python3 tools/qualify_java_fibers.py --output /tmp/java-activation-fibers \
  --wasi-sdk /path/to/wasi-sdk-29.0-x86_64-linux
LSF_GUEST_SDK_LANGUAGE=java LSF_JAVA_FIBER_FIXTURE=/tmp/java-activation-fibers \
  cargo --config .cargo/managed-guest.toml test --locked -p latent-wasmtime \
  --test local_service \
  runtime::signed_java_threads_spin_join_and_thread_local_use_real_activation_fibers \
  -- --ignored --exact --nocapture
```

Selecting the signed case without its prepared component fails. The Java CI lane
prepares and executes it explicitly; normal runtime tests do not install a
compiler or silently skip a missing fixture. Three fresh signed/admitted
activations verify ordinary thread start, a sleeping worker, ThreadLocal
isolation, join, and a volatile flag loop without explicit yield. Prepared additional modes
cover independent pools, future exceptions and interruption/cancellation,
timeouts, a blocking completion callback, ordered batches and first-successful
completion. A root-return mode supplies idle and pending pools without application
shutdown glue. Every invocation checks real Store, broker, activation and cell
reclamation. The unchanged application source runs all three modes in each of
three separate reference-JDK processes; only the reference harness terminates its
ordinary process-owned pools. The expanded executor mode still fails in its
signed guest run and root-return remains unqualified. Reference-JDK success and
successful component generation do not establish their guest behavior. Complete
failed attempts are retained separately.

The retained expanded component `b15ce736` was replayed without changing its
bytes or its original 10 billion fuel, 64 MiB and 120-second limits. A bounded
diagnostic observed the actual TeaVM event queue empty at root completion, then
containing two worker interrupt continuations when the pump parked indefinitely
using its earlier delay. The original deadline and pending physical owners are
retained in the failed receipt. The narrow delay repair passes controls that
execute the SDK pump body and unchanged, digest-verified TeaVM 0.15 EventQueue:
the prior source exposes the queued-work park, while 96 completed model
activations settle their 256 original model owners once, and a busy pool still
parks with its pending owners retained. These controls use synthetic host and
continuation entry seams on JDK 25.0.3; they establish the pump ordering, not
full guest thread or runtime qualification.

The repaired SDK was then compiled through the unchanged pinned JDK 25.0.4.1,
Gradle 9.1.0 and WASI SDK 29 tools. Component `2a541dcf` validates and the same
application passes all nine reference-JDK numeric controls. A normal native
runtime rebuilt from the exact source passes mode 0, but mode 1 traps after
63,498 microseconds with 6,085,988 fuel and 9,373,512 peak bytes under the original
limits. Private bounded numeric stack readers locate a NullPointerException in
Throwable.addSuppressed during dispatch cleanup. The locked TeaVM classlib model
confirms that all five real Throwable constructors omit the suppressed-array
initializer which exists in their unused fakeInit counterparts. The SDK now
initializes that exact maintained field in the real constructors, preserving the
original class, methods and application symbols. Actual locked-model controls
check the prior missing initialization, all five repaired constructor entries,
unchanged method owners, layout drift and repeated-port rejection. These controls
run on host JDK 25.0.3 and also belong to the maintained pinned fiber qualifier.
The subsequent component rebuild and all original signed modes remain pending;
the original exception masked by cleanup may still require a separate repair.

The original thread-only pinned Linux debug experiment measured 9241560 bytes of activation peak
memory in each run under the unchanged 67108864-byte ceiling. The first run
included cold preparation at 14.73 seconds; subsequent runs took 112.9 and 118.4
milliseconds. These measurements describe this small fixture, not general
latency, fairness or physical memory plateaus.

## Remaining profile requirements

CompletableFuture, cached/work-stealing/virtual-thread factories, scheduled
executors, recurring callbacks, FutureTask.runAndReset, duration-based TimeUnit
members, full interruption and wait/notify races, shared I/O readiness, sockets/DNS,
cross-tenant reuse, late wakes and node stop remain open. General generated host
I/O still uses the existing synchronous lowering and does not establish sibling
progress while an accepted socket operation waits. Published library/default
factory qualification, dependency safe-point coverage and measured active/parked
owner plateaus are also required for #741. Issues #741, #736, #695 and the SDK
Library milestone remain open.
