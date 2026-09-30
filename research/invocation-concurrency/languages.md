# Compiler, runtime and library-use inventory

Reviewed against repository baseline `b40a31aa7e63128698df2be86324657b4d22a590`
on 2026-09-30. The linked repository sources are the evidence for the maintained
profiles; version bumps require rereading them and rerunning affected probes.
This table does not turn a compiler build or a library API's existence into
runtime compatibility.

**Evidence labels:** **profile** means the maintained SDK documents/source state
that behavior; **experiment** means this track has an executable real-component
case, whose passing status must be established by a receipt; **candidate** means
a real library pattern considered here but not newly compiled/qualified by this
investigation. Native tests are not substituted for emitted-component evidence.

## Pinned profiles and practical library patterns

| Language | Compiler/runtime source at the baseline | Real library use cases and evidence | Decision |
| --- | --- | --- | --- |
| Rust | Rust 1.97.1, `wasm32-unknown-unknown`, wit-bindgen 0.62.0, wasm-tools 1.254.0. [SDK](../../sdk/rust-guest/README.md); the workspace locks Wasmtime 48.0.3 for the host. | **Profile:** typed `latent-guest` async HTTP/service bindings. **Experiment:** `std::future::Future`, `poll_fn`, bounded join of generated host futures, and actual unsupported `std::thread::spawn`. **Candidate:** a library accepting a caller-supplied executor/transport rather than creating its own Tokio/Rayon runtime. Those runtimes are not qualified by a `Future` implementation alone. | Keep existing async imports. Defer an SDK scope API until real-node accounting/cleanup qualification; reject OS-thread substitution. |
| Java | TeaVM 0.15.0 C backend, Temurin 25.0.4.1+1, Gradle 9.1.0, WASI SDK 29/Clang 21.1.4; generated C component bindings. [SDK](../../sdk/java-guest/README.md). This is not a deployed JVM. | **Profile:** synchronous Java capability methods over activation-suspending host imports. **Candidate:** `CompletableFuture.completedFuture(...).thenApply(...)` as a synchronous completion chain versus `supplyAsync(...)` using a default executor, and `Thread.start`/`join` rendezvous. The completed-chain candidate still needs TeaVM class-library/reachability qualification; it is not marked supported here. Arbitrary application JAR admission is separately scoped. | Prefer explicit synchronous/transport seams; reject inline or fake thread start; defer executor/continuation transforms. |
| C | Zig 0.16.0 `zig cc`, C11, `wasm32-wasi`, wit-bindgen 0.62.0, wasm-tools 1.254.0; documented 64 KiB guest stack. [SDK](../../sdk/c-guest/README.md), [ownership helper](../../sdk/c-guest/include/lsf/ownership.h), [async helper](../../sdk/c-guest/include/lsf/async.h). | **Profile:** generated async calls retain input/result frames until subtask retirement; the C resource helper's 32-entry bound is not a thread count. **Candidate:** ordinary synchronous libc `qsort` callbacks versus a C11 `thrd_create`/contended `mtx_lock` library path. C callbacks that perform supported host calls do not imply POSIX threads or a scheduler ABI. | Preserve explicit generated async ownership; defer stackful/OS-thread emulation. |
| JavaScript / TypeScript | Maintained ComponentizeJS 0.22 line, exact dependency graph in the SDK lock/provenance inputs, synchronous JavaScript projection restored to async WIT. [SDK](../../sdk/typescript-guest/README.md). | **Profile:** ordinary values at WIT exports, not Promises; activation-local promise/microtask state; disabled `setTimeout` traps. **Candidate:** `Promise.resolve`/`Promise.all` local computation versus exported unresolved Promises, Node workers or recurring timer callbacks. A Promise object is not permission to keep an activation alive or to admit arbitrary npm/Node dependencies. | Keep the closed export/runtime profile. Defer a general async export/event-loop contract and reject detached/timer work. |
| Go | Patched Go 1.27.1 with the maintained `wasiOnIdle` integration; componentize-go 0.4.3 and pinned commit; `go.bytecodealliance.org/pkg` 0.2.3. Not stock Go or TinyGo. [SDK](../../sdk/go-guest/README.md). | **Profile:** compiled examples exercise channels, activation-local goroutines and GC on single-threaded Wasm; unsupported `poll_oneoff` means `time.Sleep`/timer-backed polling is not promised. **Candidate:** `sync.WaitGroup`/channel fan-out and `net/http.RoundTripper` injection, not the default socket-using `net/http` transport. Extra modules/replace directives remain subject to the maintained build policy. | Preserve real existing cooperative scheduling. Defer independently enforced task-count/timer expansion; an explicit transport adapter is a different work item. |
| .NET | .NET SDK 10.0.100, Componentize.NET SDK/WitBindgen 0.8.0-preview00011, NativeAOT LLVM 10.0.0-rc.1.26306.1, WASI SDK 29/LLVM 21.1.4. [SDK](../../sdk/dotnet-guest/README.md). | **Profile:** completed/uncompleted activation-local Task probes, synchronous import projection, no supported thread/timer/event-loop profile; the 256-resource scope is not a task scheduler limit. **Candidate:** `Task.FromResult`/`TaskCompletionSource` completion chains versus `Task.Run`/ThreadPool/Timer, and an explicit `HttpMessageHandler` rather than a default networking stack. Arbitrary NuGet compatibility is not inferred. | Preserve documented Task behavior; defer scheduler and timer expansion pending emitted-component qualification. |

The versions above identify the compiler/runtime context for standard-library
patterns. Third-party package versions and transitive graphs must be pinned by
any adapter's separate qualification; this investigation deliberately makes no
unversioned third-party-library compatibility claim.

## Separate the six concurrency dimensions

| Profile | Synchronous-looking host suspension | Cooperative guest tasks | CPU parallelism | Locks / atomics | Invocation timers | Detached / background work |
| --- | --- | --- | --- | --- | --- | --- |
| Rust | Existing typed host futures, awaited explicitly. | This experiment's bounded stackless join; no general SDK executor promise. | No guest OS threads in this profile. | Local state/atomic operations do not establish threaded memory semantics; blocking polls can starve peers. | No new timer import in this experiment. | Rejected; join/drain and Store teardown own all work. |
| Java | Supported by the maintained generated bridge; does not need a Java executor. | No generic executor established by this profile. | No JVM threads/virtual threads. | Monitors/locks requiring another thread need compiler/runtime evidence, not synchronous substitution. | No new scheduler/timer promise. | Rejected; no daemon/default executor escape. |
| C | Generated canonical async calls preserve frame ownership. | Generated subtasks, not general C thread stacks. | No pthread/C11 thread support claimed. | Contended waits are not made safe by an uncontended-lock test. | No new timer API. | Rejected; resources/subtasks must retire. |
| JavaScript | The maintained projection can suspend host work while an export returns ordinary values. | Limited activation-local promises/microtasks, not arbitrary async exports. | No workers/Node thread facilities. | Shared-memory atomics/worker protocols are not qualified. | Existing disabled timer API remains disabled. | Rejected; microtask leftovers disappear with the Store, not persist as work. |
| Go | Runtime bridge integrates supported host waits. | Existing cooperative goroutines/channels, with activation fuel/memory/lifetime bounds. | Single-threaded guest, not parallel execution. | A goroutine scheduler can support local rendezvous; native blocking and unsupported runtime poll paths still fail. | Current `time.Sleep`/`poll_oneoff` restriction remains. | No work may survive root return/Store destruction. |
| .NET | Synchronous C# projection can suspend through the host. | Existing local Task values do not qualify ThreadPool scheduling. | No guest thread scheduler promised. | Contended BCL synchronization paths need emitted-component tests. | No timer/event-loop profile added. | Rejected; no background CLR allocation per service. |

## Concrete semantic counterexample

A library starts a worker that waits until its caller finishes initialization:

```text
start(worker: wait until initialized; then publish result)
initialized = true
join(worker)
```

Replacing `start` with `worker()` deadlocks before initialization. Pretending
`start` succeeded without running the worker leaves `join` or the result wrong.
The real component's `inline-start-deadlock` case deliberately exhibits the first
failure under bounded fuel. `cooperative-rendezvous` explicitly yields and lets
the initializer run. This is a language-neutral counterexample implemented in
Rust; it is **not** presented as a compiled TeaVM `Thread.start` compatibility test.

Similarly, executing an async callback inline can change reentrancy, lock
ownership and exception timing even when it does not deadlock. An explicit
sequential path is valid only when the application/library opts into its semantics.

## Sources and required requalification

Repository source anchors at the reviewed baseline:

- `sdk/{rust,java,c,typescript,go,dotnet}-guest/README.md` and their pinned build
  provenance/toolchain inputs define the maintained profiles, not upstream
  language feature lists. The six concrete links above use the repository tree
  being reviewed; historical evidence is identified by the baseline SHA.
- `crates/latent-wasmtime/src/host/service.rs` installs concurrent host callbacks
  with brief Store checkpoints and owned dispatch/completion. It does not install
  a universal guest executor.
- `crates/latent-wasmtime/src/backend.rs` owns invocation fuel, limits, call,
  post-return and Store reclamation; `backend/owned.rs` retains the prepared-use
  owner and capacity permit. `tests/async_application.rs` is an existing real
  async-component execution test, not a six-runtime scheduler qualification.
- [Rust's target documentation](https://doc.rust-lang.org/stable/rustc/platform-support/wasm32-unknown-unknown.html)
  documents unsupported standard-library thread creation on this target. The
  experiment tests the actually pinned compiler rather than assuming that the
  moving documentation is its versioned execution receipt.

The new Wasmtime fixture uses the workspace's locked 48.0.3 API and repository
host patterns. Unversioned Wasmtime documentation may describe a newer API and
is not used as a substitute for compilation. Every relevant compiler, binding,
runtime or dependency update needs fresh actual-component evidence. Pure
source/diagnostic inventory and native test results remain separately labelled.
