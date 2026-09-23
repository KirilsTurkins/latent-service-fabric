# Java guest feasibility — not yet a supported authoring workflow

This directory is work toward [#548](https://github.com/KirilsTurkins/latent-service-fabric/issues/548),
not a Java capsule SDK release. The external RPC client remains separate in
[`../java-client`](../java-client). No qualification, deployment, signing,
capability ownership, or real-node result is implied by compilation.

The candidate uses maintained TeaVM **0.15.0**, its C backend, the current pinned
`wit-bindgen` **C** generator, Zig's WASI C compiler, and `wasm-tools`. It does not
use the removed, unmaintained TeaVM-WASI generator. WIT canonical ABI code is
generated from `feasibility/wit/world.wit`; the tiny Java/C smoke bridge is not a
general Java binding generator.

## Reproduce the compiler probe

Use the repository's pinned [development toolchain](../../docs/development/toolchain.md),
including Temurin 25, Gradle 9.1.0, Zig 0.16.0, wit-bindgen 0.62.0 and wasm-tools
1.254.0. Build tools can run JVM processes; deployed capsules must not own one.
From the repository root:

```sh
python3 sdk/java-guest/tools/feasibility.py --output target/java-guest-feasibility-1
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
Dependency transitive-input verification is also explicitly unqualified.

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
