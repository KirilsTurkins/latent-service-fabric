# Validation baseline

Updated on **2026-08-18** for the Phase 0 executable contract, toolchain baseline, and Rust echo capsule fixture.

## Entry point

After installing the exact prerequisites in [`docs/development/toolchain.md`](docs/development/toolchain.md), a clean checkout is validated with:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

The command is intentionally non-mutating for authoritative sources. Formatting is checked with `cargo fmt --all --check`; generated bindings, descriptors, and capsule artifacts are written below `target/` or Cargo `OUT_DIR`.

## What is validated

- The committed root `Cargo.lock` contains the selected direct dependency versions and is consumed unchanged by every Cargo command with `--locked`; CI does not generate or substitute a dependency graph.
- The pinned Rust toolchain, MSRV, target, direct dependency versions, Python requirements, and CI tool versions remain synchronized.
- Every Rust workspace target compiles, passes Clippy, and runs its tests using the committed lockfile.
- The runtime WIT world is staged with all platform dependencies; every platform and example WIT package is parsed by `wasm-tools`; generated Wasmtime host bindings and `wit-bindgen` guest bindings compile.
- The Rust echo guest returns normal input unchanged and its shared implementation tests cover `empty-message`, `message-too-large`, the exact 65,536-byte boundary, UTF-8 byte accounting, and bounded activation-ID logging data.
- The echo guest is built as a `wasm32-wasip2` Component Model artifact with generated WIT bindings. `wasm-tools validate` accepts it, and the extracted root world must import exactly `latent:context/context@0.1.0` and `latent:log/log@0.1.0` and export exactly `examples:echo/api@0.1.0`.
- The extracted component interface contains the exported `echo` function and both declared domain-error variants. Any ambient WASI import, missing import, or unexpected export fails validation.
- Two isolated clean echo builds must be byte-identical. A generated capsule manifest, build receipt, and SHA-256 file record stable metadata, local-build trust, the documented reproducibility boundary, and the computed component digest beneath `target/capsules/echo/`.
- All Protobuf files pass Buf lint and generate a deterministic file-descriptor set.
- All six JSON Schemas pass Draft 2020-12 meta-schema validation, and checked-in capsule, deployment, binding, policy, and trigger examples validate against their corresponding schemas.
- Rust, Go, TypeScript, Java, .NET, and C SDK interface surfaces compile or pass syntax checks.
- SDK compiler identities are verified before compilation, including Eclipse Temurin 21.0.11+10 and Zig 0.16.0 with its Clang 21.1.8 frontend targeting `x86_64-linux-gnu`; the runner-provided C compiler is not used.
- Generated directories are excluded from repository traversal without excluding malformed authoritative source files.
- Deterministic test IDs, manual time, temporary workspaces, and a current-thread future executor are covered by Rust unit tests.

## Echo fixture commands

Build and validate one generated fixture:

```bash
make echo-capsule
```

Run the two-build digest stability check explicitly:

```bash
make echo-capsule-reproducibility
```

The artifact remains generated rather than checked in. The generated `capsule.json` starts from the checked-in contract example but replaces its placeholder digest with the actual `sha256:` content digest and marks the artifact as an unsigned local clean build.

## CI jobs

The workflow fixes its host boundary at `ubuntu-24.04` and separates default Rust checks, the MSRV check, contract and echo-component validation, and SDK validation. The contracts job installs the pinned `wasm-tools` version before running the reproducible component build. A failure in any job indicates that the executable interface baseline is no longer reproducible from a clean checkout.

## Allocation boundary

Contract and capsule validation starts compiler and validator commands only. It does not start a service process, construct a Wasmtime engine or store, create an async runtime or worker pool, open a listener, lease an execution cell, or reserve capsule-owned execution state.

## Scope

Passing this baseline establishes source consistency, guest behavior, component-interface validity, and same-boundary build reproducibility. It does not establish runtime invocation correctness, performance, isolation, cross-platform byte identity, wire compatibility of future generated clients, or the zero-idle-allocation invariant under execution. Those require the remaining Phase 0 vertical slice and the conformance and benchmark suites described under `tests/` and `benchmarks/`.
