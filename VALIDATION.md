# Validation baseline

Updated on **2026-08-18** for the Phase 0 executable contract and toolchain baseline.

## Entry point

After installing the exact prerequisites in [`docs/development/toolchain.md`](docs/development/toolchain.md), a clean checkout is validated with:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

The command is intentionally non-mutating for authoritative sources. Formatting is checked with `cargo fmt --all --check`; generated bindings and descriptors are written below `target/` or Cargo `OUT_DIR`.

## What is validated

- The pinned Rust toolchain, MSRV, target, direct dependency versions, Python requirements, and CI tool versions remain synchronized.
- Every Rust workspace target compiles, passes Clippy, and runs its tests using the committed lockfile.
- The runtime WIT world is staged with all platform dependencies; every platform and example WIT package is parsed by `wasm-tools`; generated Wasmtime host bindings and `wit-bindgen` guest bindings compile.
- All Protobuf files pass Buf lint and generate a deterministic file-descriptor set.
- All six JSON Schemas pass Draft 2020-12 meta-schema validation, and checked-in capsule, deployment, binding, policy, and trigger examples validate against their corresponding schemas.
- Rust, Go, TypeScript, Java, .NET, and C SDK interface surfaces compile or pass syntax checks.
- Generated directories are excluded from repository traversal without excluding malformed authoritative source files.
- Deterministic test IDs, manual time, temporary workspaces, and a current-thread future executor are covered by Rust unit tests.

## CI jobs

The workflow separates default Rust checks, the MSRV check, contract validation, and SDK validation. A failure in any job indicates that the executable interface baseline is no longer reproducible from a clean checkout.

## Scope

Passing this baseline establishes source consistency and compilability. It does not establish runtime correctness, performance, isolation, wire compatibility of future generated clients, or the zero-idle-allocation invariant under execution. Those require the Phase 0 vertical slice and the conformance and benchmark suites described under `tests/` and `benchmarks/`.
