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

Compiler checkpoints are selected from actual application class files and the
captured JAR closure, without a package allowlist or loading application classes
in the compiler JVM. A bounded source-origin index and its digest are retained
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
isolation, join, and a volatile flag loop without explicit yield. Every invocation
checks real Store, broker, activation and cell reclamation. The same unmodified
application source returns 42 in three separate reference-JDK executions.

The pinned Linux debug experiment measured 9241560 bytes of activation peak
memory in each run under the unchanged 67108864-byte ceiling. The first run
included cold preparation at 14.73 seconds; subsequent runs took 112.9 and 118.4
milliseconds. These measurements describe this small fixture, not general
latency, fairness or physical memory plateaus.

## Remaining profile requirements

ExecutorService, ordinary Executors factories, Future/CompletableFuture,
independent queues, scheduled executors, recurring callbacks, full interruption
and wait/notify races, shared I/O readiness, sockets/DNS, idle-pool retirement,
cross-tenant reuse, late wakes and node stop remain open. General generated host
I/O still uses the existing synchronous lowering and does not establish sibling
progress while an accepted socket operation waits. Published library/default
factory qualification, dependency safe-point coverage and measured active/parked
owner plateaus are also required for #741. This first thread slice does not close
#741, #736, #695 or the SDK Library milestone.
