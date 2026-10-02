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

The SDK class-library implementation supplies `Executors.newSingleThreadExecutor`,
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
toolchain. At this checkpoint, a new component and all twelve normal signed
invocations were still required; the complete runtime profile remains unqualified.

The first pinned rebuild from source `e812437c` passed all 70 SDK helper checks
and all twelve unchanged reference-JDK results, then failed at TeaVM's
`generateC` step with `unreviewed-maintained-monitor-handler`. The exact locked
compiler reproduces the cause: its platform plugin changes the native async
declaration into a Fiber bridge before the SDK's native-pair transformer runs.
The SDK plugin now uses TeaVM's public `@Before(PlatformPlugin.class)` ordering
contract. The existing locked platform artifact supplies that annotation's
class reference; no compiler dependency version or application symbol changes.
An expanded control against ten verified model JARs exercises the actual plugin
ordering reader, preserves rejection of the original platform-first shape, and
runs the maintained async processor on both owned pairs. It checks that each
generated Fiber bridge targets its owned callback once while the standard
method retains the Java frame that closes its leases. This control passed on
host JDK 25.0.3. Pinned component compilation and the twelve normal signed
invocations were pending at this ordering checkpoint.

The next pinned rebuild from source `897695ae` passed all 72 SDK helpers and
all twelve original reference-JDK results, then failed in the maintained
coroutine transform while reading its liveness table. Its stack trace and failed
compiler project are retained. The actual locked transform reproduces the same
indexing failure when an SDK wrapper or generated monitor acquisition can
suspend in basic block zero. The SDK now follows the maintained async processor's
empty-entry jump convention: the operation stays in a separate body block,
while monitor acquisition remains outside the protected user body. The model
control runs the unchanged pinned coroutine transform on all six sleep, wait,
raw-hook and join wrappers, both instance/static monitor entries, and both
maintained native async pairs. It verifies one resumption and one original
operation, retains both normal and exceptional monitor releases, and reproduces
the rejected former layout. This metadata control passed on host JDK 25.0.3;
fresh pinned component compilation and all twelve normal signed invocations
were still required at this ownership checkpoint.

The last attempted expanded executor component passed its thread-only mode but
failed in its signed executor mode with a closed host `resource-exhausted` cause
([retained CI run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/36811904043)).
Replaying the retained executor component with the corrected resource-free
result lowering removes that immediate admission failure, but reaches its
unchanged 120-second deadline during physical pool retirement before the later pump repair. The cached-mode
attempt stopped at the missing standard TimeUnit declarations before component
generation. The subsequent compiler repair and default-factory/wait changes
had not completed pinned component and signed-node execution at that checkpoint;
the executor, root-return and cached modes were still unqualified. Reference-JDK success and successful
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
The subsequent component rebuild and all original signed modes were then pending;
the original exception masked by cleanup may still require a separate repair.

Source `896c007cf1400e912b70c236fe3035cb8f426884` subsequently passed the pinned
Linux component preparation, all 73 SDK helper controls, the actual locked TeaVM
model controls, and all twelve original reference-JDK cases. Component
`sha256:9d909ffa9398cafa8b4c02222ec71eea588f308c3e0c8e85568df0c9e8794a12`
contains 11,428,605 bytes. A fresh normal native `local_service` harness built
from that same frozen source passed all twelve original signed/admitted
invocations: three iterations of thread, executor, root-return, and cached-pool
modes, each returning `42` and passing the physical retirement checks. Cold
publication preparation took 297.52 seconds and created zero guest Stores or
activations before the calls. Each invocation retained its original 120-second,
10 billion fuel and 64 MiB limits; measured peak guest memory was 9,439,048 bytes.
The native build, component and all 7,368 frozen source files were independently
hashed, and source/component bytes remained unchanged after execution.

The retained [PR #807 evidence](https://github.com/KirilsTurkins/latent-service-fabric/pull/807)
binds this result to source `896c007c` and the component digest above. Later
development and CI integrations still require their current checks. These small
fixture modes establish their ordinary factory/wait behavior and retirement,
while the complete #741 profile and published-library requirements remain open.

The original thread-only pinned Linux debug experiment measured 9241560 bytes of activation peak
memory in each run under the unchanged 67108864-byte ceiling. The first run
included cold preparation at 14.73 seconds; subsequent runs took 112.9 and 118.4
milliseconds. These measurements describe this small fixture, not general
latency, fairness or physical memory plateaus.

## Remaining profile requirements

CompletableFuture, work-stealing/virtual-thread factories, scheduled
executors, recurring callbacks, broader cached-factory, reset-future and
duration-based TimeUnit qualification, full interruption and
wait/notify races, shared I/O readiness, sockets/DNS,
cross-tenant reuse, late wakes and node stop remain open. General generated host
I/O still uses the existing synchronous lowering and does not establish sibling
progress while an accepted socket operation waits. Published library/default
factory qualification, dependency safe-point coverage and measured active/parked
owner plateaus are also required for #741. Issues #741, #736 and the SDK
Library milestone remain open.

The isolated CompletableFuture candidate supplies pending `CompletableFuture`,
`CompletionStage` and `CompletionException` through their unchanged standard
class identities. It implements the synchronous and asynchronous stage families,
composition, recovery, aggregation, pending `get`/`join`, cancellation and default
factories. Default asynchronous work creates one managed cached pool per activation
when its first callback is dispatched;
applications supply no executor adapter or shutdown hook. Cancellation removes
waiting listeners, while a queued or running callback retains its original
queued-work and result owners until physical callback completion. Timed completion,
delayed executors, obtrusion and minimal-stage conveniences remain unsupported.

Failed unary, compose and either stages preserve the input failure without
dispatching their callbacks. An installed binary listener also propagates a failed
input before dispatch, while an already-ready binary stage keeps the reference
JDK's executor dispatch. Successful exceptional composition relays its input
without dispatching recovery; ordinary exceptional recovery, observation and
handling retain the JDK's dispatch behavior. Reading the default executor or
propagating a failed unary input creates no worker pool.

The maintained compiler preparation first compares 82 standard observables against
the pinned JDK and the SDK port source. A separate strict host ledger checks 419
ownership observables and 32 completion/cancellation races. The ledger and host
executor exist only in those source controls and are excluded from the component.
Ten verified, locked TeaVM model JARs also check 180 actual method bodies,
canonical standard and private helper identities, resolved reference closure,
unsupported-method rejection, and 25 coroutine bodies containing 24 monitor
scopes. The locked lambda emitter generates all 23 port callbacks and checks that
their construction references resolve after runtime normalization. Only the
three declared port helpers retain an SDK identity; emitted callbacks retain
their canonical caller identity. Neither application nor port classes are
initialized during that model inspection. These source and model results still require actual default-pool,
dynamic callback and guest-binding behavior in signed execution. Prepare and select the independent,
ordinary CompletableFuture fixture with the original guest ceilings:

```sh
python3 tools/qualify_java_fibers.py --fixture completable \
  --output /tmp/java-completable-fibers --wasi-sdk /path/to/wasi-sdk-29.0-x86_64-linux
LSF_GUEST_SDK_LANGUAGE=java LSF_JAVA_COMPLETABLE_FIXTURE=/tmp/java-completable-fibers \
  cargo --config .cargo/managed-guest.toml test --locked -p latent-wasmtime \
  --test local_service \
  runtime::signed_java_completable_futures_use_default_activation_executor \
  -- --ignored --exact --nocapture
```

For a completed, immutable Gradle 9.1 dependency cache, add
`--read-only-cache /path/to/caches/modules-2`. This uses Gradle's read-only
dependency input in place, runs offline, retains strict dependency verification,
and keeps locks and transformed artifacts in a fresh compiler directory. The
captured cache joins the compiler's before/after identity checks. It cannot be
combined with `--offline-cache`, which retains the existing private-copy behavior.

The first guest-only candidate preparation at `d1d7b2a7` completed real Java
compilation but failed TeaVM C generation: a broad helper rewrite redirected ten
generated callback references into absent SDK classes. The original failure and
all generated source, class and command records are preserved. The emitted-callback
control reproduces that identity failure and passes after the narrower helper
mapping. The repaired guest-only component at `e58ae4c2` has digest
`sha256:9d619d3a9bea72a83c4af0fb87c3214d8f94a74be974d55803cb1765d28a8841`
and remains a preparation result. Its original `tests:caller` namespace did not
complete the normal example-tenant package/signing path.

At source `8d860547`, a separately captured normal-authoring fixture changed
only the WIT package declaration and selected project world to `examples:caller`.
The original Java source, four modes, three repetitions, imports, and budgets
were preserved. The actual full Java builder completed compilation, contracts,
V5 compatibility, packaging and inspection in 97.467 seconds. All twelve fresh
JDK observations returned 42. The new component has digest
`sha256:a5d9b4778e937581dbc1777f2ea200f15e80e985df838e5f7abc84ea2fe7bd16`
and size 4,239,792 bytes; it has its own completed build observation.

The normal strict signer, release publication, three explicit grants and
deployment succeeded using normal host tools from `acb7988`. The first mode-0
invocation then returned a known `guest-trap`, with 5,771,223 fuel, 9,373,512 bytes
of peak memory and zero effects or outbound calls. The remaining eleven calls
were not run. The bounded audit projection includes accepted host dispatches and
completed host-call paths. The host records completion even when an operation
returns a WIT error; those returned errors are absent from this projection. It is
incomplete and does not establish logical admission or the trap's cause. The
failed node group was physically reaped; a clean node shutdown and guest ownership
retirement were not qualified. The original task limits and guest ceilings of 120 seconds,
10 billion fuel, and 64 MiB were retained.

The [source-bound observation](../testing/evidence/java-activation-authoring-normal-2026-10-02.json)
records the compiler, native producers, input seals, original failures and exact
completion boundaries. The successful full build and signing establish that
authoring path; successful normal CompletableFuture execution, advanced methods,
library behavior and the complete #741 profile remain open.

A separate actual Windows JDK comparison at the same implementation source found
an ordinary executor failure defect. If an executor queues a callback and then
throws, the JDK still runs an accepted `supplyAsync` callback and keeps a
`completeAsync` target pending until its queued callback runs. The port eagerly
fails that work and skips the supplier. Its private source ledger also reports
zero callback and result owners while one callback remains physically queued.
Both `RejectedExecutionException` and a generic exception reproduced the public
difference. These [paired source observations](../testing/evidence/java-completable-executor-throw-2026-10-02.json)
identify an unimplemented repair and preserve all original controls and counts.
They do not explain the normal mode-0 trap, whose application uses the default
executor, or qualify TeaVM lowering or native admission.
