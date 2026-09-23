# Java capsule compiler feasibility

This is executable research for [#548](https://github.com/KirilsTurkins/latent-service-fabric/issues/548),
not a delivered Java guest SDK. Java client tests do not establish guest support.
The feature remains unqualified until generated WIT bindings, all required
capabilities and real-node ownership/cancellation/package workflows pass.

The probe compiles the maintained Java sources with Java 25 and TeaVM 0.15.0
through its current C and Wasm-GC backends. It never uses the removed
TeaVM-WASI backend or the removed wit-bindgen Java generator. It preserves
compiler/linker/component diagnostics rather than supplying fake runtime imports.
No application JVM, JavaScript host, capability grants, deployment or release is
created by this probe. The JVM is used only for compilation and a separately
labelled source-level sanity check.

From the repository root, with the exact tools in `tools/toolchain.toml`:

```sh
python3 research/java-capsules/probe.py --output target/java-feasibility
```

A new output directory is required: attempts are never overwritten. The receipt
always distinguishes compilation from runtime qualification. A compiler/linker
failure is evidence for this exact candidate and input, not proof that every
possible Java runtime port is impossible. Startup, active guest memory, GC,
resource ownership and cleanup remain unmeasured until an actual node runs it.

Dependency capture is an explicit research-only first step:

```sh
python3 research/java-capsules/probe.py --capture-dependencies --output target/java-feasibility-capture
```

Captured dependency locks/checksums are not reviewed pins. Review them before
copying them back into this directory; subsequent attempts use strict dependency
verification. Generated code, receipts and logs stay under the selected output.
