# Java activation fibers

The opt-in `teavm-activation-fibers-v1` compiler selection starts ordinary
application code inside TeaVM 0.15.0's maintained C-backend fibers. It keeps the
existing Java compiler installation, component adapter, exact WIT comparison,
closed ambient effects and original 64 MiB Java activation ceiling. The complete
standard concurrency profile remains unqualified; default Java projects retain
their current supported profile.

The October 10 [PR #807 reconciliation](https://github.com/KirilsTurkins/latent-service-fabric/blob/200c17c26b24d6bf06d8d28102362ea714c1f4eb/docs/development/phase4-handoffs/2026-10-10/pr807-reconciliation.md)
records fresh signed local-service fixture execution: four ordinary-thread modes
and four default-CompletableFuture modes, each repeated three times. All 24 calls
return 42 under the original limits and pass the bounded physical idle checks.
The complete unchanged-library matrix and ordinary installed-node qualification
remain open in #741 and #736; earlier observations below retain their source and
completion boundaries.

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

Internal managed-thread startup rolls back its reservation only before the
maintained start hook accepts the worker and after host settlement confirms it.
Failures after that hook or denied settlement keep the original owner charged.
Private source-ledger controls establish those failure paths, separately from
signed component execution. Custom factory threads overriding public `start()`
remain unqualified: the pinned JDK 25 pool starts through its internal thread
container, bypassing that override, while this port currently invokes it.
The ordinary four-mode reference fixture preserves its qualified source paths;
this internal rollback does not establish custom-factory equivalence for #741.

The activation-owned default `CompletableFuture` facility grows workers lazily
under those same task and queue ceilings. Its idle workers use untimed waits
and retire during root drain, leaving finite timer slots for application waits.
Explicit cached executors retain their standard 60-second idle expiration.

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

Each timed Java frame holds one host timer created through `timer-start`. Its
captured monotonic deadline also controls the maintained TeaVM queue entry.
The pump uses `timer-next` only for an exact queue-deadline match and keeps the
timer charged until the resumed frame confirms `timer-stop`. Unmatched queue
waits retain their separately charged `wait-for` path. The pump pairs a queue
delay with its first clock sample; the second sample still checks whether an
event is due.

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

As of 21 October 2026, later finite signed programmes qualify selected
ordinary APIs beyond the historical failures above. [#1237](https://github.com/KirilsTurkins/latent-service-fabric/pull/1237)
and [#1306](https://github.com/KirilsTurkins/latent-service-fabric/pull/1306)
retain [joined resource/Timer work](../testing/java-resource-runtime.md) and
[entered late Timer callbacks](../testing/java-dotnet-late-facilities.md), including
fresh tenant invocations. [#1268](https://github.com/KirilsTurkins/latent-service-fabric/pull/1268)
qualifies [mixed ordinary HTTP bodies](../testing/java-http-mixed-bodies.md).
[#1273](https://github.com/KirilsTurkins/latent-service-fabric/pull/1273) qualifies
[accepted HTTP completion after logical cancellation](../testing/java-http-late-completion.md)
through an ordinary executor and default `CompletableFuture.supplyAsync`, before
activation retirement. The selected fiber-I/O bridge supports sibling progress
while a typed HTTP operation is genuinely pending; this is distinct from a
standard raw socket port. [#1032](https://github.com/KirilsTurkins/latent-service-fabric/pull/1032)
retains the [unchanged published Commons Lang/Hutool default-worker programmes](../testing/java-published-worker-libraries.md).
Each linked receipt keeps its actual source, component, native tuple and finite
limits; none requalifies every later integration or the whole runtime profile.

Work-stealing/virtual-thread factories and scheduled executors remain explicitly
outside the selected supported subset; #741 does not require universal JVM
coverage. Remaining acceptance concerns all observables and combinations of the
named supported subset: full interruption and wait/notify races, broader
cached/reset/duration behavior, dependency checkpoint coverage and
non-suspendable initialization/CPU boundaries, measured active/parked ownership
costs, supported stream integration with distinct authority, and lifecycle or
node-stop races. The qualified finite late-callback and tenant observations do
not prove arbitrary post-retirement wakes or opaque worker quiescence.
Issues #741, #736 and the SDK Library milestone remain open.

The following earlier CompletableFuture candidate history retains its original
source-specific failures and then-pending requirements; it does not replace the
later finite signed observations linked above.

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
`completeAsync` target pending until its queued callback runs. The port at that source eagerly
fails that work and skips the supplier. Its private source ledger also reports
zero callback and result owners while one callback remains physically queued.
Both `RejectedExecutionException` and a generic exception reproduced the public
difference. These [paired source observations](../testing/evidence/java-completable-executor-throw-2026-10-02.json)
record the defect at that source and preserve the original observed counts.
They do not explain the normal mode-0 trap, whose application uses the default
executor, or qualify TeaVM lowering or native admission.

Source `c8ccba41` repairs uncertain executor acceptance. A queued producer can
still run after its submission throws, and a `completeAsync` target remains
pending as on the JDK. Logical cancellation retains its callback and result
leases until physical execution retires them. Immediate retirement requires an
absence witness from the SDK-managed queue. The private rejection fixture now
uses that witness while preserving all original assertions.

All six fresh JDK executor cases match the port. The maintained source helper
passes its original 82 behavior and 419 ownership assertions, 32 race rounds,
49 new acceptance assertions and 30 bounded uncertainty assertions. Eight
uncertain producers retain the original eight queued and eight result leases;
a ninth is denied, cancellation retains the leases, and activation cleanup
correctly remains unqualified. The enclosing bounded JVM is physically retired.

The actual locked TeaVM model resolves the callback closure and retains its
original negatives, 24 coroutine monitors, 25 owned callback bodies and 23
generated callbacks. The rejection witness adds one method body, yielding 181.
The historical maintained guard expects 180 and rejects this result. This
[source repair observation](../testing/evidence/java-completable-executor-acceptance-2026-10-02.json)
preserves that failure and the source-bound input seals.

The [callable review](../testing/evidence/java-completable-executor-model-review-2026-10-03.json)
retains all 180 original callable identities. It compares 177 unchanged canonical
IR bodies, three intentional ownership changes, and the sole added SDK rejection
witness. Fingerprint version 2 requires exactly 181 bodies with the original
24/25/23 monitor, owner and callback counts and all closed negatives. The fresh
[maintained-helper observation](../testing/evidence/java-completable-executor-model-fingerprint-2026-10-03.json)
passes that strict fingerprint at source `6cc9a42c` with the same ten locked
TeaVM jars and Windows Temurin 25.0.3+9. Both JVM Jobs physically retire within
the original 90/30-second, one-CPU, 512-MiB and 8-MiB bounds, and every input seal
matches. The 33 focused qualification controls, CI inventory and foundation
checks pass; the unchanged documentation validator reaches its original
240-second limit and remains a retained timeout.

A fresh full build and signed normal execution remain required. The source
repair does not explain the earlier mode-0 trap or complete #741.


## Compiler diagnostics and measured construction

These historical observations retain the source, limits and completion status of
each cited run. Later measurements do not turn an earlier failure into a pass.

The [normal checkpoint compiler repair evidence](../testing/java-checkpoint-normal-source-evidence.json)
binds the original and corrected JVM controls and the actual CTarget build.
The pinned private `Fiber.start()` baseline now receives TeaVM's original
reference-resolution and class-initialization passes before exact comparison;
unknown instructions and changed class identities still refuse. The actual
normal authoring build passed CTarget generation and core compilation, then
refused component assembly at the unchanged function-body size limit of
7,654,321 bytes. A later [retained normal build](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40097935402)
identified `meth_dla_Capsule_pools` at 15,264,587 bytes; the closed runtime adapter
had no oversized function. These are compiler boundary results, not Java runtime,
GC, signed-execution or complete standard-library qualification.

For this exact public source/WIT only, a failed component assembly also attempts
to retain its generated `c/d/l/a/Capsule.c` Clang input under an independent
4-MiB ceiling. `generated-c.json` records its identity or a closed unavailable
status. Missing, oversized or unsafe C never removes the two existing bounded
Wasm captures or changes the original compiler failure. This separates the
available C input from final Wasm growth without accepting an oversized function.
The existing Java authoring workflow's default-false `public_fiber_assembly`
manual selector runs only the original public fiber preparation command and its
JDK/compiler controls; it refuses combinations with either other optional mode
before acquisition. Default authoring CI coverage remains intact. This path
provides compiler evidence, not component execution or runtime qualification.

The compiler retains the current development defaults: TeaVM C `FULL` and
Clang `-O2`. Earlier [BALANCED](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40101238993)
and [activation `Oz`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40109009991)
experiments did not repair the size boundary: the same public `pools` body was
13,993,280 and 14,367,528 bytes respectively. Those policy and provenance-value
experiments are withdrawn. Their failed histories remain separately attributed;
the retained capture programme does not establish a compiler or runtime fix.

Only that manual public-fiber job additionally selects `--observe-public-wineh`.
The optional observer snapshots the admitted generated C, headers, bindings,
SDK, tools and the maintained observer/filter/qualifier files before the unchanged
normal Clang command. After an authenticated
component-assembly failure, it rechecks those inputs and the original command
receipt, then requests LLVM's before/after `win-eh-prepare` prints for only
`meth_dla_Capsule_pools`, using a separate output path. A sealed fixed-public
ticket permits only that exact Clang command, environment and working directory.
The private count-only filter launches it in the existing owner's process group;
the original owner still accounts every compiler/linker descendant before a
summary is returned. Existing process owners, the 600-second outer command bound,
35-minute job and 80-MiB defensive capture ceiling remain unchanged.

The filter streams at most **256 MiB of combined raw compiler output** through
the same incremental parser and hashes, without a raw IR file or full buffer.
This is a separate diagnostic transit budget. Each line is limited to 256 KiB
before UTF-8 decoding; fixed counters and at most 16 KiB of scalar samples are
retained. Only a summary of at most 64 KiB reaches the outer capture. The parent
rechecks identities after owned cleanup, including incomplete summaries.
`component-inputs/public-wineh.json` cannot report observed unless the child
exits successfully, both pipes reach EOF, both exact prints complete and the
postchecks pass. Raw IR, the ticket and diagnostic Wasm are not uploaded. Missing
or changed inputs, overflow, unknown syntax and incomplete output fail closed;
an earlier failure is not applicable. Original compiler output, exception and
the 16-MiB normal log cap remain unchanged; no automatic retry is selected.

The [first attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40117757282)
refused TeaVM's actual `@`-escaped header names before replay. The private reader
correction retains the original inventory bounds and global Rust path rules.
The [corrective attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40120265783)
reached real replay but exceeded the then-used 80-MiB full-buffer cap. Both are
failed/incomplete historical observations; no counters or pass attribution were
retained. The [count-only run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40125799067)
completed both prints and owned cleanup, with unchanged postchecks. It observed
140,717,621 bytes of compiler stderr, no stdout, and a zero compiler exit. All ten
hosted source controls passed. Its original module remains byte-identical to the
historical `FULL`/`-O2` failure, and component assembly still refuses the oversized
15,264,587-byte public `pools` body at the unchanged parser limit.

For that one function, the pass changed these complete IR counts:

| Counter | Before WinEH preparation | After | Change |
| --- | ---: | ---: | ---: |
| Instructions | 231,750 | 1,913,670 | +1,681,920 |
| PHIs | 216,215 | 214,755 | -1,460 |
| PHI incoming edges | 2,574,479 | 894,019 | -1,680,460 |
| Stores | 5,405 | 1,685,865 | +1,680,460 |
| Allocas | 190 | 1,650 | +1,460 |
| Volatile stores | 2,586 | 2,586 | 0 |
| Volatile loads | 2,145 | 2,145 | 0 |

The matching removed PHI incoming edges and added stores identify substantial
expansion during WinEH preparation. The volatile counts did not grow across
this pass. This measurement does not establish an exclusive end-to-end cause,
a safe compiler repair or Java execution qualification. The
[retained evidence](../evidence/java-public-wineh-ea252/receipt.json) binds the
source, original module, commands, finite limits and complete scalar counts.

A subsequent [selected-fiber `-O0` attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40129296830)
used identical generated C and changed only the Clang optimization argument.
Its ten hosted source controls passed, but component assembly still refused
`pools`: 9,904,105 bytes at `0x1b343`, above the unchanged 7,654,321-byte limit.
WinEH preparation added 638,994 stores (379 PHIs times 1,686 invoke sites);
volatile counts again stayed unchanged across that pass. The smaller expansion
did not establish a compiler repair. The candidate `O0` policy, provenance enum
and added candidate test are withdrawn; the original `FULL`/`-O2` compiler and
`O2`-only Java provenance validation remain intact. The [failed-attempt receipt](../evidence/java-fiber-o0-a464/receipt.json)
binds its historical source and actual failure. No runtime qualification or
additional compiler trial follows from this measurement.

[The 25 October compiler evidence](../testing/evidence/java-private-scalar-compiler-2026-10-25.json)
records one authenticated compiler build with 9 SSA controls and 15 LLVM lit
cases, followed by the unchanged public Java/WIT programme. TeaVM remains at
`FULL`, Clang at `-O2`, with native EH/SjLj, 64 KiB stack and 64 MiB maximum
memory. Its generated C remains 733,980 bytes with the original digest and
650-file inventory. The largest core function, `meth_dla_Capsule_pools`, fell
from 15,264,587 to 6,133,668 bytes, below the unchanged 7,654,321-byte parser
limit. Normal component construction and validation passed. The raw result
remains `component-built-unqualified`; that compiler-only run did not execute
a Java component. Runtime execution is recorded separately below.

A separate data-only check used the existing packer and installer on the exact
compiler subproduct: 10,154 SDK files plus 13 provenance files, 771,176,565 bytes
in total. Both complete inventory identities matched, including link
flattening. Normal compiler admission also passed from the isolated installed
recipe without site packages. The selected `clang-21` driver bytes and command
construction matched the actual public compilation. This check executed no
Clang command and did not assemble or qualify an entire native SDK/frontend.
Actions artifacts are expiring builder inputs; the sealed normal distribution
contains the compiler bytes and provenance rather than relying on an evergreen
Actions URL. Full runtime, GC, hostile-input, cost and ownership acceptance
remains open.



## Retained public fibers through the normal signed node

[The 26 October runtime evidence](../testing/evidence/java-retained-fibers-runtime-2026-10-26.json)
records twelve fresh activations of that exact retained 10,282,099-byte public
component: three iterations of all four original modes. A source-matched native
v11 `local_service` harness was built once; Java, LLVM and the component were
not rebuilt. The existing package, signing, catalog admission and activation
manager path returned `[42]` for every call, with twelve distinct requested and
actual activation IDs. The actual cumulative Store counter advanced from zero
to twelve. All seven sampled Store/reservation/broker counters were zero after
each call; the original broader `Fixture::idle` assertions also remained active.

The original ceiling stayed at 10 billion fuel, 64 MiB and 120 seconds per
activation, one cell and zero outbound requests, with Task5/Executor3/Queue8/
Wait8/Timer2/Result8/Native2. Actual fuel was 5,708,210 to 10,186,665 and maximum
reported peak memory was 9,549,999 bytes. Preparation took about 55.6 seconds;
the 65.5-second selected test process includes that setup. All three pure
input/origin/observation controls and all five owned commands passed.

The original compiler receipt remains unchanged; this separate runtime receipt
binds source `9f4d763b5b4eda8f6e9c62f70bf03175487c4dca` and its raw twelve rows.
It qualifies this finite public fixture, not the full Java concurrency profile,
GC/accounting matrix, published worker/timer library requirement or separately
gated standard socket/DNS/stream integration. Issue #741 remains open.
