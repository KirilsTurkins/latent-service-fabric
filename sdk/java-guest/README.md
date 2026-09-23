# Java guest feasibility — not yet a supported authoring workflow

The actual component from [attempt a4b31059](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35890049528)
was rejected by the current LSF engine: its Wasm exception proposal is disabled.
The opt-in `java-guest-diagnostic` experiment enables maintained Wasmtime exception
handling with a non-moving 4 MiB exception-GC reservation and fresh Stores. It
does not satisfy signed node qualification. A separate `engine.javaGuest: true`
node opt-in now installs the bounded exception profile. Its full 4 MiB reservation
is charged before each activation Store; linear memory shares the same budget.
Ordinary nodes explicitly keep Wasm GC support and exceptions disabled. The Java
profile rejects pooling and mixed renderer installation, changes compiler/AOT
compatibility identity, and does not increase operator limits.

This directory is work toward [#548](https://github.com/KirilsTurkins/latent-service-fabric/issues/548),
not a Java capsule SDK release. The external RPC client remains separate in
[`../java-client`](../java-client). No qualification, deployment, signing,
capability ownership, or real-node result is implied by compilation.

The candidate uses maintained TeaVM **0.15.0**, its C backend, the current pinned
`wit-bindgen` **C** generator, WASI-SDK **29** / Clang **21.1.4**, and `wasm-tools`. It does not
use the removed, unmaintained TeaVM-WASI generator. WIT canonical ABI code is
generated from `feasibility/wit/world.wit`; the tiny Java/C smoke bridge is not a
general Java binding generator. The new `tools/java_guest` generator instead
reads the authoritative `wasm-tools` type graph, creates typed Java bindings and
marshals through maintained unflattened C bindings. The original WIT async
contract remains authoritative; synchronous Java execution suspends in Wasmtime
without creating a language-owned event loop. This path is under qualification.

## Reproduce the compiler probe

Use the repository's pinned [development toolchain](../../docs/development/toolchain.md),
including Temurin 25, Gradle 9.1.0, WASI-SDK 29, wit-bindgen 0.62.0 and wasm-tools
1.254.0. Build tools can run JVM processes; deployed capsules must not own one.
From the repository root:

```sh
python3 sdk/java-guest/tools/feasibility.py --output target/java-guest-feasibility-1 --wasi-sdk /path/to/wasi-sdk-29.0-x86_64-linux
```

Use a **new output directory for every attempt**. The command never removes a
previous attempt. It checks the configured versions, executes the Java-source
self-test on the build JVM, compiles those sources to C, generates the WIT C
bindings, compiles a core module and attempts component validation. The JVM
self-test is only a compiler baseline, not evidence of execution inside LSF.

`report.json` records exact source hashes (including current platform WIT and
engine surface), stage commands, elapsed times and the failed stage. Logs and
generated C remain available even after compilation fails. Exit status is
nonzero for a failed stage. `component-built-unqualified` only proves component
construction, not LSF execution or completion of #548. `qualified` remains false.
Gradle strictly checks the reviewed dependency metadata and 70-JAR inventory.

The generated bridge experiment can be reproduced separately:

```sh
python3 tools/qualify_java_bridge.py --output target/java-bindings-1 --wasi-sdk /path/to/wasi-sdk-29.0-x86_64-linux
cargo run --locked -p latent-wasmtime --features java-guest-diagnostic --example java_runtime_probe -- target/java-bindings-1/compiled/component.wasm --typed
```

It covers full signed/unsigned integer widths, UTF-8/NUL, declared errors, a real
async capability import, exceptions, GC and fresh Stores. It still deliberately
reports `qualified: false` until the full signed-node and ownership matrix passes.
The bridge supports records, lists, tuples, options, results, variants, enums,
flags and imported owned resources. Unsupported future/stream values, exported
resources, resource methods, inline interfaces and ambiguous multiple interface
versions fail explicitly during generation. Resource wrappers are `AutoCloseable`;
borrows cannot overlap close or consume, ownership transfers before dispatch,
and there is no finalizer, hidden retry or background cleanup.

## Boundaries still requiring qualification

The probe exercises full-width signed Java integers, UTF-8 including embedded NUL
and a supplementary character, caught Java exceptions and repeated allocations.
It does **not** establish WIT declared-error mapping, async resource ownership,
all class-library APIs, reflection, dynamic loading, JNI, threads or arbitrary
Java dependencies. These features must not be advertised as supported. In
particular, neither a JVM self-test nor a compiler-generated `.wasm` measures
activation startup, guest GC, cancellation or reclamation on a real node.

TeaVM's C runtime currently selects Unix APIs for GCC-compatible compilers. The
probe deliberately tests the real generated runtime rather than substituting a
C implementation for the Java application. Any runtime port must retain bounds,
exception semantics and host authority; fake clocks, ambient OS imports,
provider grants, retries and revived legacy generators are not valid fixes.

Before this can become the authoring workflow, implement and execute the typed
WIT binding generator, all guest capabilities and their ownership tests, the
three contract examples, signed package/admission/deployment/invocation/cleanup,
and the complete #548 real-node cancellation, exhaustion, fresh-state and
resource-measurement matrix. Keep #548 open and this work unqualified until those
results and newcomer review are linked. No runtime release publication is enabled.

Cleanup consists only of deleting the chosen local probe output after retaining
its evidence; the probe creates no node deployment or package publication.
