# Compiler, runtime and library-use inventory

Maintained-profile observations below are tied to LSF baseline
`b40a31aa7e63128698df2be86324657b4d22a590` on 2026-09-30. The 2026-09-30
usability revision changes the proposed direction, not the behavior qualified at
that baseline. [ADR-0060](../../adr/0060-bound-invocation-scoped-concurrency.md)
now targets standard runtime compatibility underneath unchanged application and
transitive dependency code, rather than developer-supplied executor/transport
adapters. Production enablement requires separate qualification.

**Evidence labels:** **profile** means maintained LSF source/documentation;
**upstream source** means inspected compiler/runtime implementation, not an LSF
execution result; **experiment** means this track's actual Rust component with
its original passing receipt; **target** means proposed work, not available APIs
or a certified third-party package. Native tests do not substitute for emitted
components. Toolchain changes require fresh evidence.

## Pinned profiles and standard library patterns

| Language | Reviewed compiler/runtime context | Current evidence and unchanged-source qualification targets |
| --- | --- | --- |
| Rust | Rust 1.97.1, `wasm32-unknown-unknown`, wit-bindgen 0.62.0, wasm-tools 1.254.0; host Wasmtime 48.0.3. [SDK](../../sdk/rust-guest/README.md). | **Profile:** typed `latent-guest` async host calls. **Experiment:** `std::future::Future`, `poll_fn`, bounded join and actual `std::thread::spawn` rejection. **Target:** an LSF runtime target, standard-library and maintained executor integration for ordinary thread/join/synchronization and default library runtime paths; not a requirement to adopt the research join or inject an executor. Tokio/Rayon or arbitrary futures are not qualified by that experiment. |
| Java | TeaVM 0.15.0 C backend, Temurin 25.0.4.1+1, Gradle 9.1.0, WASI SDK 29/Clang 21.1.4 and generated C component bindings. [SDK](../../sdk/java-guest/README.md). No deployed JVM. | **Profile:** synchronous-looking capability calls suspend on the host; LSF traps scheduling hooks. **Upstream source:** low-level `TThread.start` queues a fiber; `Fiber` and `EventQueue` supply continuation/event machinery. **Target:** actual `Thread.start`/`join`, interruption, thread locals, monitors, executor/future/default-pool and timeout behavior, including `CompletableFuture.supplyAsync` where the class-library implementation is completed. No such target API is newly certified here. |
| C | Zig 0.16.0 `zig cc`, C11, `wasm32-wasi`, wit-bindgen 0.62.0, wasm-tools 1.254.0; documented 64 KiB guest stack. [SDK](../../sdk/c-guest/README.md), [ownership helper](../../sdk/c-guest/include/lsf/ownership.h), [async helper](../../sdk/c-guest/include/lsf/async.h). | **Profile:** generated async calls retain input/result frames until subtask retirement; the 32-entry resource helper is not a thread limit. **Target:** libc/runtime implementations for `thrd_create` or a declared pthread surface, contended locks/conditions, thread-local storage and standard blocking I/O. Ordinary synchronous `qsort` callbacks and canonical subtasks do not establish stackful thread support. |
| JavaScript / TypeScript | Maintained ComponentizeJS 0.22 line and exact SDK lock/provenance graph; synchronous projection restored to async WIT. [SDK](../../sdk/typescript-guest/README.md). | **Profile:** exports return ordinary values, not Promises; activation-local promises/microtasks exist; disabled `setTimeout` traps. **Target:** invocation-driven Promise exports/completion, job queues, timeout/recurrence and named standard/Node runtime surfaces. `Promise.all`, default asynchronous library APIs and timer callbacks need emitted-component qualification; a Promise object is not already an event-loop guarantee. |
| Go | Patched Go 1.27.1 with maintained `wasiOnIdle`, componentize-go 0.4.3 and pinned commit, `go.bytecodealliance.org/pkg` 0.2.3. Not stock Go or TinyGo. [SDK](../../sdk/go-guest/README.md). | **Profile:** actual examples exercise activation-local goroutines, channels and GC on single-threaded Wasm; unsupported `poll_oneoff` means `time.Sleep` and timer polling are not promised. **Target:** preserve Go scheduling, qualify `sync.WaitGroup`/channel fan-out, runtime-created work, standard timers/polling and the ordinary socket-using `net/http` path. A custom `RoundTripper` is not required by the new compatibility goal or sufficient to prove the default path. |
| .NET | .NET SDK 10.0.100, Componentize.NET SDK/WitBindgen 0.8.0-preview00011, NativeAOT LLVM 10.0.0-rc.1.26306.1, WASI SDK 29/LLVM 21.1.4. [SDK](../../sdk/dotnet-guest/README.md). | **Profile:** completed/uncompleted activation-local Task probes and synchronous import projection; no supported general thread/timer/event-loop profile. The 256-resource scope is not a scheduler limit. **Target:** runtime/ThreadPool/wait integration for `Task.Run`, completion chains, waits, thread locals, timers and ordinary networking paths. A supplied `HttpMessageHandler`, synchronization context or `Task.FromResult` test does not qualify those default paths. |

The target is automatic runtime support throughout the captured dependency graph,
including libraries that create their own workers. LSF-owned versioned runtime or
package ports must be applied by the toolchain and retained in provenance, not
handed to each application as a patching task. Ordinary application dependency
admission remains separately scoped; this table neither opens arbitrary build
plugins nor claims arbitrary JAR/npm/NuGet/native-module compatibility.

## Separate the six concurrency dimensions

This table records the **current baseline**, not the revised target's availability.

| Profile | Host suspension | Guest tasks | CPU parallelism | Locks / atomics | Timers | Background lifetime |
| --- | --- | --- | --- | --- | --- | --- |
| Rust | Existing typed host futures. | Research bounded stackless join, not a general thread runtime. | No guest OS threads in this target profile. | Local atomic/state operations do not establish independent workers; blocking polls can starve siblings. | No timer import in the experiment. | No work survives root retirement. |
| Java | Maintained synchronous-looking host bridge. | Upstream fibers exist; LSF scheduling hooks trap. | No JVM/virtual-thread parallelism qualified. | Contended monitor/wait progress needs actual compiler/runtime integration. | Scheduling hooks remain disabled. | No persistent Java pool or heap. |
| C | Generated canonical async calls retain frames. | Canonical subtasks, not general C stacks/threads. | No pthread/C11 thread support claimed. | An uncontended-lock test does not qualify contended waits. | No timer API added. | No surviving callbacks or resources. |
| JavaScript | Current synchronous projection can suspend host work. | Activation-local promise state, not arbitrary async exports. | No workers/Node threading qualified. | Shared-memory worker protocols remain unqualified. | Current disabled APIs still trap. | Leftover local state is destroyed, not persistent work. |
| Go | Runtime bridge integrates supported waits. | Existing cooperative goroutines/channels. | Single-threaded guest execution. | Scheduler can support local rendezvous; unsupported native/poll paths still fail. | Existing sleep/poll restriction remains. | No goroutine survives Store destruction. |
| .NET | Synchronous import projection can suspend. | Local Task values are not a ThreadPool qualification. | No general thread scheduler promised. | Contended BCL synchronization requires emitted-component tests. | No timer/event-loop expansion delivered. | No CLR allocation per dormant service. |

The revised direction is to implement real logical threads/tasks and scheduling
where needed, not preserve every present denial permanently. Standard runtime
ports must preserve identity, thread locals, interruption, synchronization, executor
ordering and language-specific exception behavior. They must park only the waiting
logical thread and provide qualified safe scheduling opportunities in CPU loops.
Shared physical capacity does not imply a shared logical executor queue, CPU
parallelism, or universal memory-model equivalence.

Library maintenance and recurring callbacks are **targets within an activation**,
not newly enabled features. Runtime-managed worker shutdown must distinguish
accepted work from idle infrastructure. An opaque custom worker cannot be declared
harmless because it sleeps or is daemon-marked. Required work must settle or produce
a bounded lifecycle failure; persistent work after activation retirement remains
unsupported. The same original budget, deadline and explicit authority apply.

## Java source finding and integration boundary

The inspected upstream 0.15.0 sources are:

- [`TThread.java`](https://github.com/konsoletyper/teavm/blob/0.15.0/classlib/src/main/java/org/teavm/classlib/java/lang/TThread.java):
  low-level `start()` queues `Fiber.start`, with logical current-thread and
  interruption state; join/sleep use waiting machinery.
- [`Fiber.java`](https://github.com/konsoletyper/teavm/blob/0.15.0/core/src/main/java/org/teavm/runtime/Fiber.java):
  continuation value storage and suspension/resumption state.
- [`EventQueue.java`](https://github.com/konsoletyper/teavm/blob/0.15.0/core/src/main/java/org/teavm/runtime/EventQueue.java):
  event registration, cancellation and processing through platform time/wait hooks.

At the LSF baseline,
[`sdk/java-guest/tools/teavm_platform.py`](../../sdk/java-guest/tools/teavm_platform.py)
replaces `teavm_waitFor` and `teavm_interrupt` with traps. The maintained
[`compiler.py`](../../tools/java_guest/compiler.py) applies that adaptation to
generated C. These are identifiable integration points, not proof that enabling
hooks implements missing class-library APIs, fiber-aware WIT entry/return,
monitors, fairness, GC roots, clock policy or cancellation. The upstream event and
continuation storage also needs explicit resource limits.

Prioritize that integration and unchanged Java library tests. Do not infer support
for `ExecutorService`, `CompletableFuture`, virtual threads or native/JVM facilities
from the presence of `TThread`. Complete and qualify each claimed standard surface.

## Concrete semantic counterexamples

A library starts a worker that waits until its caller finishes initialization:

```text
start(worker: wait until initialized; then publish result)
initialized = true
join(worker)
```

Replacing `start` with `worker()` deadlocks before initialization. Pretending
`start` succeeded without running the worker leaves the result or join wrong.
The real Rust component's `inline-start-deadlock` exhausts bounded fuel, while
`cooperative-rendezvous` explicitly yields and permits initialization. These are
**not** compiled TeaVM thread compatibility tests and do not prove automatic
compiler checkpoint insertion.

The revised runtime must additionally qualify a synchronized flag loop that lacks
an explicit application yield, a blocking host call while a sibling is runnable,
and independent logical executors sharing physical capacity. Test real ordering,
reentrancy, lock ownership, interruption and exception timing against the reference
runtime. Do not require callers to rewrite these patterns into LSF APIs.

## Qualification and source ownership

The ADR requires unchanged published-library workloads and transitive workers for
each claimed language profile, with pinned versions and default construction/API
paths. Custom executor/transport injection may be tested as an optional adapter,
but cannot count as default-path compatibility. Publish the corpus, unsupported
cases and measured costs; source inventory alone establishes no compatibility rate.
The prototype's eight-task cap is an experiment bound, not a product-wide policy.

The six linked SDK sources and their build provenance describe current profiles.
[`host/service.rs`](../../crates/latent-wasmtime/src/host/service.rs) installs
concurrent host callbacks with brief Store checkpoints and owned completion.
[`backend.rs`](../../crates/latent-wasmtime/src/backend.rs) and
[`backend/owned.rs`](../../crates/latent-wasmtime/src/backend/owned.rs) retain
fuel, limits, Store reclamation, prepared-state ownership and capacity. None
installs the proposed language-runtime compatibility layer.

The Rust research fixture uses the workspace's locked Wasmtime 48.0.3 API. An
upstream Component Model mechanism or moving engine documentation is not a
qualification of that version. Compiler, binding, runtime and dependency changes
need new actual-component evidence. Preserve original receipts and negative cases;
this revised inventory does not relabel them as execution of the proposed ports.
