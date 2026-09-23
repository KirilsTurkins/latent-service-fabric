# Java capsule guest SDK

The [authoring guide](../../docs/component-development/java-authoring.md) creates
an editable Java project outside the runtime checkout, builds its actual source,
packages it, and demonstrates signed admission and cleanup on a local node.
This guest SDK is separate from the [external Java RPC client](../java-client).

Qualification is **in progress**. Compilation and local state-machine tests are
not signed-node proof. The [implementation report](../../docs/testing/java-guest-authoring.md)
tracks the required real-component, ownership, node and guide gates. Do not treat
this branch as a release or close #548 until its exact-source qualification passes.

## Compiler and source contract

The maintained TeaVM **0.15.0 C backend**, Temurin **25.0.4.1+1**, Gradle **9.1.0**,
WASI-SDK **29** / Clang **21.1.4**, wit-bindgen **0.62.0 C**, and wasm-tools
**1.254.0** compile ordinary Java implementations into Wasm components.
The obsolete TeaVM-WASI generator is not used. Build machines run JVM processes;
capsules do not deploy or retain a JVM, Java server, guest host thread or event loop.

Edit `src/dev/latent/app/Capsule.java` and `wit/world.wit` in the created project.
The entry class implements generated `dev.latent.generated.Bindings.Exports`.
Additional Java source files beneath `src` are captured. Application JARs,
Maven projects, Gradle plugins/build scripts, JNI, reflection-based dynamic
loading, arbitrary native libraries and host threads are outside this profile.
Core Java values, records, exceptions, lambdas and the reachable TeaVM class
library used by the examples are supported; this is not a complete JDK runtime.
Filesystem, stdout/stderr and ambient networking are unavailable, not fake
successful operations. Use the declared platform capabilities for effects.

The builder copies application/SDK/WIT inputs to private staging, checks the
reviewed 70-JAR compiler closure and complete pinned tool distributions, records
source and generated-binding inventories, rechecks inputs and inspects the package.
An observation is unsigned until a separately authorized builder signs it.
The public repository label is operator-asserted, not source authentication.
The recipe does not claim reproducible or fully hermetic builds or a complete
transitive SBOM. Signing keys and production credentials never reach the compiler.

## Typed authoritative WIT

The bridge derives its graph from wasm-tools and current platform WIT, then
marshals through maintained generated C canonical ABI bindings. Every build
checks `bindings.lock.json` against the complete eight-capability reference and
checks application generation twice. An unsupported type fails explicitly.

Signed `s64` is Java `long`; `u64` is `Unsigned64`, retaining all 64 bits,
unsigned decimal parsing and comparisons. Narrow unsigned values use a wider
Java integer. Strings preserve strict UTF-8 and embedded NUL. Records, lists,
tuples, options, results, variants, enums, flags up to 64 bits and imported
resource ownership have typed representations. Declared WIT errors are
`Result.err`, not Java exceptions. Uncaught exceptions trap the activation.

One named exported interface is supported. Future/stream values, exported
resources, resource constructors/methods, inline/world-owned named interfaces
and ambiguous interface versions are rejected. Asynchronous host operations
suspend the Wasmtime activation while Java code waits synchronously. They do
not require a Java executor, hidden worker, retry queue or detached cleanup.

## Capability ownership

The nine [actual Java examples](examples) exercise the eight current interfaces:

| Capability | Java ownership and outcomes |
| --- | --- |
| Buffered HTTP | Typed request/response and exact permission/uncertainty errors; no retry. |
| Streaming HTTP | Try-with-resources upload/body/chunk owners; finish/abort consumes; trailers preserve invalid-state errors. |
| Blob | `Handle` owns opaque u64 reader/writer handles; seal consumes; retained chunks remain owned after reader close. |
| Secrets | `SensitiveBytes` adopts and clears the returned array on close; application copies have separate lifetimes. |
| Events | Exact receipt and uncertainty result; no outbox, retry or consumer-completion claim. |
| Local service | Exact returned/declared/platform outcomes and host-controlled child budgets. |
| Random | Exact u64 values, bounded bytes and typed invalid-length errors. |
| Custom metrics | Configured instruments, bounded labels and exact budget/unavailable errors. |

Canonical resource aliases share consumed/borrowed state. Close is idempotent;
consuming operations invalidate before dispatch. Borrow and consume cannot
overlap on canonical resource owners. Destructors are not retried if they fail.
The SDK has no finalizer or background resource release. Abandoned resources
remain charged until the host reclaims the activation; the wrapper does not
announce an early refund. Cancellation does not prove an external effect was
undone. Secret and private wire buffers are explicitly cleared where owned;
applications must not copy them into immutable strings or logs.

## Execution and memory boundaries

An operator must enable `engine.javaGuest: true`. It installs a separately
identified bounded engine/cache/AOT profile, rejects pooling and mixed renderer
profiles, and does not raise operator limits. Other nodes keep exceptions and
Wasm GC support disabled. Java uses a fixed 4 MiB managed heap inside linear
memory. Wasm exceptions use a non-moving GC reservation of 4 MiB, initially
64 KiB, with no growth reservation or guard. The full reservation is charged
before Store creation because Wasmtime 47 has no GC-growth limiter callback.
The activation's memory budget includes that charge plus every linear memory.

Templates request 64 MiB aggregate memory, 1 billion fuel and 5 seconds.
Marshalling payloads are capped at 8 MiB, non-byte lists at 65536 items, graph
depth at 32, imports at 256 and exports at 64. These protocol limits do not
promise every maximum-size value fits the 4 MiB managed heap. Allocation failure
is bounded and terminal. A Java `OutOfMemoryError` is a guest trap; an aggregate
host memory/fuel denial is resource exhaustion. Fresh calls receive new Stores
and static state. Only shared bounded compiled images may outlive activations.

TeaVM runtime clock calls are visible monotonic/wall WIT imports. Installed
providers and explicit publication/service/caller-scoped grants are required,
even for a greeting. No entropy is implicitly granted. Async host waits,
resource retention, cancellation and fuel remain controlled by LSF.

## Reproduce and inspect

With the exact pinned tools on PATH and `WASI_SDK_PATH` set, run from the checkout:

```sh
python3 tools/java_guest/lock.py
python3 tools/qualify_java_capsules.py --output /tmp/java-authoring-new-attempt --wasi-sdk "$WASI_SDK_PATH"
```

Use a new outside-checkout output path every time. `qualification.json` is
written only after five standalone builds, all nine actual SDK component tests,
signed-node success/denial/failure/recovery and physical reclamation, and the
six printed guide blocks pass. `QUALIFICATION-FAILED.json`, `BUILD-FAILED.json`,
`compiler-logs/` and bounded command logs retain failed-stage evidence.

The earlier `tools/qualify_java_bridge.py` and
`java_runtime_probe --typed` are useful compiler/value diagnostics, but
deliberately do not claim signed admission or node qualification.
Runtime release publication stays on HOLD and #345 remains a separate human review.
