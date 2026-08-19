# Validation baseline

Updated on **2026-08-19** for the Phase 0 executable contract, toolchain, and Rust echo component fixture.

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
- The Rust echo fixture compiles as a `wasm32-wasip2` Component Model `cdylib` from the checked-in `examples:echo/service@0.1.0` world without handwritten ABI types.
- The generated echo component validates with `wasm-tools`, exposes only the declared context and log imports, exports the typed echo function and both domain-error cases, and has a generated capsule manifest, SHA-256 digest, stable build metadata, and explicit local trust declaration.
- Two clean echo builds are byte-for-byte identical under the pinned build boundary. Typed Wasmtime tests cover success, `empty-message`, `message-too-large`, activation-ID access, and exactly one bounded structured log per invocation.
- All Protobuf files pass Buf lint and generate a deterministic file-descriptor set.
- All six JSON Schemas pass Draft 2020-12 meta-schema validation, and checked-in capsule, deployment, binding, policy, and trigger examples validate against their corresponding schemas.
- Rust, Go, TypeScript, Java, .NET, and C SDK interface surfaces compile or pass syntax checks.
- SDK compiler identities are verified before compilation, including Eclipse Temurin 21.0.11+10 and Zig 0.16.0 with its Clang 21.1.8 frontend targeting `x86_64-linux-gnu`; the runner-provided C compiler is not used.
- Generated directories are excluded from repository traversal without excluding malformed authoritative source files.
- Deterministic test IDs, manual time, temporary workspaces, and a current-thread future executor are covered by Rust unit tests.

## Focused echo commands

Build and validate one local bundle:

```bash
make echo-capsule
```

Run the complete fixture gate, including repeated-build comparison and typed component invocation:

```bash
make echo-capsule-check
```

Both commands create output only under `target/capsules/echo-rust/`. The full gate is also executed by `tools/validate_contracts.sh` and the contracts CI job.

## CI jobs

The workflow fixes its host boundary at `ubuntu-24.04` and separates default Rust checks, the MSRV check, contract and component validation, and SDK validation. A failure in any job indicates that the executable interface baseline is no longer reproducible from a clean checkout.

## Scope

Passing this baseline establishes source consistency, component behavior, typed ABI compatibility, and reproducibility inside the documented Phase 0 build boundary. It does not establish production runtime performance, isolation under hostile code, wire compatibility of future generated clients, cross-host bit identity, or the zero-idle-allocation invariant under a long-running fabric. Those require the remaining Phase 0 runtime, conformance, and benchmark work described under `tests/` and `benchmarks/`.
