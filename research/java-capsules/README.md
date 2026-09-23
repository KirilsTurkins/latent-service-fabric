# Java capsule compiler feasibility

This is executable research for [#548](https://github.com/KirilsTurkins/latent-service-fabric/issues/548),
not a delivered Java guest SDK. Java client tests, a valid component and V8 core
execution do not establish LSF support. The issue remains open until authoritative
WIT bindings, capability ownership and the signed real-node workflow pass.

## Reproduce the candidates

Use the exact tools in [the toolchain configuration](../../tools/toolchain.toml):
Java 25.0.4.1+1, Gradle 9.1.0, Zig 0.16.0, wasm-tools 1.254.0 and Node
24.19.0. Install the checksum-pinned Gradle distribution as shown in the
[research workflow](../../.github/workflows/java-guest-feasibility.yml).
TeaVM 0.15.0 and its transitive artifacts are pinned in `gradle.lockfile` and
`gradle/verification-metadata.xml`. The pins preserve the 45 artifact identities
captured by the earlier CI attempt; normal runs use strict dependency verification.
The dependency files were checked against the retained compiler artifacts. This
is input pinning, not a claim of hermetic builds or complete supply-chain review.

From the repository root:

```sh
python3 -m unittest discover -s research/java-capsules/tests -v
python3 research/java-capsules/probe.py --output target/java-feasibility
```

The second command intentionally exits **2**, including when the headless
candidate succeeds: its receipt says `qualification: not-qualified`. A new output
directory is mandatory. The original C and Wasm-GC attempts and every failed
phase remain intact; the third candidate uses a separate `build/C-headless`
directory. A missing tool or incorrect tool version is an environment failure,
not proof of language infeasibility.

Expected boundaries for the pinned, unmodified upstream candidates are POSIX
signal/event-loop dependencies in C and unresolved `wasm:js-string` imports in
Wasm-GC. The probe does not install fake imports, revive the removed TeaVM-WASI
backend, or use the removed wit-bindgen Java generator.

The headless candidate should produce `build/C-headless/component.wasm`,
`port-receipt.json`, `sjlj-input.json` and `core-execution.json`. Inspect its real
exported WIT with:

```sh
wasm-tools component wit target/java-feasibility/build/C-headless/component.wasm
```

The export is `latent:java-probe/probe@1.0.0`, with `run(seed: s64) -> s64`.
This small research bridge is not a general Java WIT generator. The V8 runner
asserts there are **no core imports** before executing the actual compiled Java
method 40,010 times across two fresh instances. Java execution is not replaced
by JavaScript arithmetic. Node is a bounded compiler-test runner only, never a
language process owned by an LSF deployment.

## What the reactor port changes

The maintained Java source and TeaVM-generated application, class initialization,
GC and exception dispatch remain unchanged. The adapter checks pinned runtime
hashes and exact startup structure before copying the compiler output. It changes
only four runtime scaffold files and adds one thin C export bridge:

- Avoid the upstream assumption that any GCC-compatible compiler is a Unix host.
- Replace virtual-memory operations with checked allocation inside bounded Wasm
  linear memory. Logical uncommit clears bytes; it does **not** reclaim Wasm pages.
- Retain class/string/GC initialization without starting a Java main fiber, POSIX
  timer, event queue, thread or listener. A trapping initialization poisons the
  instance instead of being retried.
- Preserve real setjmp/longjmp Java exceptions using Zig's checksum-checked,
  bundled Wasm support and standard exception-handling instructions. Unsupported
  standard output traps; it does not claim a successful write.

Compile the application and the bundled setjmp implementation with the same
exception flags, then link ordinary libc separately. Passing those flags into
Zig's libc build exposed an LLVM weak-tag failure; disabling Java exception
handling is not an acceptable workaround. The exact commands and source/runtime
identities are retained in the attempt.

The profile is deliberately limited to the checked `Probe` entry point. Java
primitives, full-width signed integers, caught exceptions, arrays and internal
Unicode/string operations are exercised. Arbitrary dependencies, reflection,
dynamic loading, threads, fibers, standard I/O, asynchronous imports and a complete
Java class-library profile are **not qualified**. WIT strings/results/resources
and their ownership across asynchronous operations are not exercised by this
scalar contract. The source uses Java 25 compilation without claiming every
Java 25 language feature is supported by TeaVM.

## Observe the real LSF backend

Also install Rust 1.97.1 and the workspace's pinned build prerequisites. Run this
separately even though the compiler probe exited 2:

```sh
python3 research/java-capsules/engine_probe.py \
  --component target/java-feasibility/build/C-headless/component.wasm \
  --output target/java-engine-feasibility
```

This compiles a temporary research target against the **unchanged production
Wasmtime factory, dependency features and containment backend**. It never changes
Cargo manifests or installs provider authority. The owned target is removed on
success, failure or cancellation; a pre-existing or concurrently modified file
is never overwritten/deleted. Logs, source identities and observed backend
errors go to the new output directory. Its exit status remains 2: backend
execution alone would still not establish signed-node conformance.

The current workspace disables Wasmtime's `gc` feature. In pinned Wasmtime 47.0.4,
standard exception support is gated by that feature. Do not enable GC merely to
make the component load: exception/GC allocation must be bounded and accounted
alongside existing aggregate linear-memory limits, cancellation and fresh-store
cleanup. Read the actual `engine.json` status before claiming a backend result;
a build or observer environment error is not a component rejection.

## Measurements and remaining gates

The local, freshly recompiled Java 25 probe passed all 40,010 checks in Node
22.16.0/V8 12.4 with `--experimental-wasm-exnref`. This is explicitly a different
runner from pinned CI Node 24.19.0. The local component was 1,304,356 bytes,
SHA-256 `d060700434bfe1f2aefa95b6ca0fac4cb6867cb90717de746f9619e9d7d3e4a1`.
Linear memory after the first call and after repeated calls was 36,503,552 bytes
in both instances. The 16 MiB Java heap setting is **not** total active memory;
the experimental Wasm maximum is 64 MiB. These debug-bearing binaries are not a
reproducible-build or optimized-distribution size claim.

LSF startup, host exception/GC memory, cancellation and store-drop reclamation
remain separate measurements. A second fresh V8 instance does not prove LSF
reclamation. The retained receipts leave unmeasured fields unqualified rather
than assigning fabricated zeroes.

Still required before #548 can close: a maintained general WIT binding path and
project template; declared WIT errors distinct from Java exceptions; all #221
capability wrappers and ownership tests; greeting, word-count and shipping
capsules; real signed package/admission/publish/deploy/invoke/cleanup commands;
allowed/denied calls, deadline, cancellation, traps, exhaustion and fresh-state
conformance; bounded runtime resource accounting; required CI and newcomer
review. No runtime release is published by this research.

Preserve attempt directories or CI artifacts before cleaning up. The probes
create no deployment, provider or signing key; local cleanup is removal of the
two explicitly selected `target/java-*feasibility` directories after retaining
their receipts. Never reuse an old attempt directory for a new result.

Dependency recapture is research-only and must not be used to silence drift:

```sh
python3 research/java-capsules/probe.py --capture-dependencies \
  --output target/java-feasibility-capture
```

Review changed dependencies and exact artifact identities before updating pins.
A failed candidate is evidence for that input and recipe, not proof that every
possible maintained Java runtime port is impossible.
