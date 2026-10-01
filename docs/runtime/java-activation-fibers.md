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

The pending SDK class-library implementation supplies `Executors.newSingleThreadExecutor`,
`newFixedThreadPool` and `newCachedThreadPool`, including ordinary `ThreadFactory` overloads. Each pool
has its own FIFO queue and honors its requested parallelism with lazy Java worker
fibers. Submissions reserve executor, queued-work and pending-result records;
blocked future and termination waits reserve wait records. A cancelled running
future keeps its pending-result owner until the callable's physical `finally`
finishes. Completed results and returned queued tasks stay inside the accounted
Java heap. All logical ceilings come from the explicit host runtime configuration.

`FutureTask` supports runnable/callable construction, pending get, timed get,
completion/error/cancellation, readable result state, subclass `done` callbacks,
and protected `runAndReset` without completing a successfully reset future.
A callback runs outside the future's monitor, so another thread can read a
completed result while that callback blocks. `AbstractExecutorService` implements
standard submit, ordered `invokeAll` and first-successful-completion `invokeAny`.
Factories and class substitutions apply only to these exact standard classes;
application and library API references remain unchanged. TimeUnit conversions
saturate and finite waits preserve positive submillisecond timeouts. Duration
conversion truncates negative fractions toward zero; ChronoUnit conversion uses
the seven standard TimeUnit units. Cached workers retain their original host
ceilings and retire after an uninterrupted 60-second idle period.

The owned compiler hooks keep TeaVM's actual sleep and monitor continuations.
They reserve a single wait owner and, for a timed wait, a timer owner before
installing its maintained listener. The original callback resumes the Java wait
frame after monitor reacquisition. That frame closes the timer and wait owners
before returning or throwing to application code. Standard wait argument
validation precedes monitor ownership checks; interruption clears the current
thread's flag at the standard throwing boundary. Absolute deadlines saturate
without shortening a large requested timeout.

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
compiler or silently skip a missing fixture. The signed runtime case prepares
the exact admitted publication before its first activation, with a separate
600-second setup bound. It drops the preparation owner and checks idle ownership
and zero created guest Stores before starting the unchanged guest cases. Setup
time is recorded separately; every activation retains its original 120-second,
fuel, memory and runtime-resource ceilings and normal authority checks. This
isolates guest execution from cold native compilation and does not qualify cold
startup latency. Three fresh signed/admitted
activations verify ordinary thread start, a sleeping worker, ThreadLocal
isolation, join, and a volatile flag loop without explicit yield. Prepared additional modes
cover independent pools, future exceptions and interruption/cancellation,
timeouts, a blocking completion callback, ordered batches and first-successful
completion. A root-return mode supplies idle and pending pools without application
shutdown glue. Every invocation checks real Store, broker, activation and cell
reclamation. The unchanged application source runs all four modes in each of
three separate reference-JDK processes; only the reference harness terminates its
ordinary process-owned pools. The fourth mode covers ordinary cached factories,
reset futures, Duration and ChronoUnit conversion, wait validation and interrupted
sleep/join. Three fresh installed-JDK 25.0.3 reference processes passed the four
modes. All selected SDK sources compiled against pinned TeaVM 0.15.0 APIs, and
nine actual maintained/SDK class bodies passed the compiler's transformation
against that pinned class model. These are source and model controls.

TeaVM's maintained classlib supplies `TimeUnit` before the SDK substitution
policy. The compiler therefore installs the 16 reviewed conversion and wait
method bodies onto that actual standard class, preserving its enum constants,
constructor and `values()` identity. An unexpected scale-field layout fails
compilation. A control using nine lock-verified TeaVM 0.15.0 JARs proves the
original missing declarations, installed method bodies and reference closure,
preserved enum owners, layout rejection and unchanged application class identity.
The SDK source also passed 1661 conversion comparisons against the installed
JDK 25.0.3, including signed saturation and Duration/ChronoUnit boundaries.
These controls do not establish C-backend continuation or signed guest behavior.

The four-mode component `e90e1025d36cbacfd57fe6be5938fb4f7140012cf31f8e9cffede3844efd6d3b`
passed pinned component generation and all twelve reference-JDK controls, but
the first normal signed activation failed with `runtime-lifecycle-unproven`.
An independently built private numeric observer replayed those unchanged bytes
with the original 120-second, 10 billion fuel and 64 MiB limits. The guest
returned the expected `42` and both task owners settled, while exactly one wait
owner and one timer owner remained at finalization; the physical timer table
was empty. This is a lifecycle failure, even though the application result is
correct. The observer's outer wrapper later timed out during its final input
hash pass. Its original log and component were subsequently removed by external
worktree cleanup; the completed observation, original identities and wrapper
failure remain recorded separately from the surviving model-control receipts.

The original callback wrapper called the resumable typed lease-close bridge
from an EventQueue callback outside the suspended Java frame. The SDK now keeps
the lease scope in the ordinary high-level sleep or wait frame. Private native
aliases retain TeaVM's actual `@Async` declarations and their matching maintained
callback bodies; the callback resumes that frame, which can suspend correctly
while closing its leases. No callback-return refund, host ownership rule, WIT
change or quota increase is involved. A control against the nine verified
TeaVM 0.15.0 model JARs checks both real native/callback pairs, preserved standard
method identity and throws declarations, unexpected-shape and repeated-port
rejection, and unchanged application class identity. Host JDK 25.0.3 passed this
metadata control. The maintained qualifier repeats it using the pinned compiler
toolchain. A new component and all twelve normal signed invocations are still
required to prove this repair; the complete runtime profile remains unqualified.

The last attempted expanded executor component passed its thread-only mode but
failed in its signed executor mode with a closed host `resource-exhausted` cause
([retained CI run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36811904043)).
Replaying the retained executor component with the corrected resource-free
result lowering removes that immediate admission failure, but reaches its
unchanged 120-second deadline during physical pool retirement before the later pump repair. The cached-mode
attempt stopped at the missing standard TimeUnit declarations before component
generation. The subsequent compiler repair and default-factory/wait changes
have not completed pinned component and signed-node execution; the executor,
root-return and cached modes remain unqualified. Reference-JDK success and successful
component generation do not establish their guest behavior. Complete failed
attempts are retained separately.

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

On the preceding three-mode executor source, the repaired SDK was compiled through the unchanged pinned JDK 25.0.4.1,
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

CompletableFuture, work-stealing/virtual-thread factories, scheduled
executors, recurring callbacks, actual guest qualification of cached factories,
reset futures and duration-based TimeUnit members, full interruption and
wait/notify races, shared I/O readiness, sockets/DNS,
cross-tenant reuse, late wakes and node stop remain open. General generated host
I/O still uses the existing synchronous lowering and does not establish sibling
progress while an accepted socket operation waits. Published library/default
factory qualification, dependency safe-point coverage and measured active/parked
owner plateaus are also required for #741. Issues #741, #736, #695 and the SDK
Library milestone remain open.
