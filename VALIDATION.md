# Validation report

Generated and validated on **2026-08-17**.

This repository is intentionally an interface and architecture scaffold. It contains type models, traits, WIT contracts, Protobuf services, JSON Schemas, SDK abstractions, documentation, conformance specifications, and empty binary entry points. It does not contain runtime behavior.

## Checks completed successfully

- Repository structural validator: `python3 tools/validate_repository.py`
- All JSON and TOML files parse successfully.
- All six JSON Schemas are valid Draft 2020-12 schemas.
- Capsule, deployment, binding, policy, and trigger examples conform to their schemas.
- The GitHub Actions workflow parses as valid YAML.
- Cargo workspace members and local path dependencies resolve structurally.
- The 29 internal Rust crates plus the Rust SDK form an acyclic dependency graph.
- Rust cross-crate imports resolve against the declared public interface surface in a static scan.
- Rust source delimiters and interface-only policy checks pass.
- Protobuf imports resolve within `api/proto/` and all definitions declare `proto3` packages.
- WIT files declare packages and define at least one interface or world.
- Java SDK interfaces compile with `javac 21.0.11`.
- Go SDK interfaces pass `go test ./...` with Go 1.23.2.
- TypeScript SDK interfaces pass strict `tsc --noEmit` with TypeScript 5.8.3.
- C SDK header passes GCC 14.2 C11 syntax validation with warnings treated as errors.

## Checks deferred to CI or a development machine

The generation environment did not include the following toolchains:

- Rust/Cargo: `cargo check`, `cargo fmt --check`, and Clippy were not executed locally.
- `buf`/`protoc`: Protobuf definitions were structurally checked but not compiled.
- `wasm-tools`: WIT packages were structurally checked but not parsed by a Component Model toolchain.
- .NET SDK: the C# interface project was inspected but not compiled locally.

The repository includes CI and build metadata for these checks. The first implementation commit should make a clean CI run a merge requirement before interfaces are treated as frozen.

## Scope limitation

Passing these checks establishes repository consistency, syntax for the locally available SDK toolchains, and schema/example validity. It does not establish runtime correctness, wire compatibility with generated clients, performance, isolation, or the zero-idle-allocation invariant; those require the implementation and the conformance/benchmark suites described under `tests/` and `benchmarks/`.
