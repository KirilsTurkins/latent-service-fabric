# Executable build foundation

This document is the clean-checkout contract for the first Phase 1 foundation. It turns the checked-in Rust, Protobuf, and WIT interfaces into compilable generated surfaces while preserving the Phase 0 execution and evidence paths.

## Scope

The foundation provides:

- one locked Rust workspace with exact dependency versions;
- build-generated Rust messages plus Tonic clients and servers for every checked-in Protobuf file;
- build-generated Wasmtime host bindings for the aggregate platform runtime world and the maintained echo fixture;
- build-generated Rust guest bindings for the aggregate platform runtime world;
- deterministic test utilities for current-thread async execution, child-process capture, temporary workspaces, IDs, clocks, and current-process resource snapshots;
- repository validation for path-dependency cycles, exhaustive code-generation inputs, generated-output ownership, and generated-source boundaries;
- pull-request CI for formatting, compilation, Clippy, tests, contracts, and SDK surfaces.

It does **not** implement an RPC listener, service process, execution cell, scheduler, or service-owned runtime. Code generation runs only as a Cargo build step and writes only to `OUT_DIR`.

## Pinned Rust inputs

The exact dependency baseline is recorded in both the root `Cargo.toml` and `tools/toolchain.toml`:

| Area | Version |
| --- | ---: |
| Rust toolchain / MSRV | 1.97.1 / 1.94.1 |
| Tokio | 1.53.1 |
| Prost | 0.14.4 |
| Tonic / Tonic Prost | 0.14.6 / 0.14.6 |
| Tonic Prost Build | 0.14.6 |
| Vendored `protoc` | 3.2.0 |
| Tracing / tracing-subscriber | 0.1.44 / 0.3.23 |
| Wasmtime | 47.0.3 |
| `wit-bindgen` | 0.60.0 |

The committed root `Cargo.lock` is authoritative. Local commands and CI use `--locked`; they do not silently replace the dependency graph.

## Code-generation ownership

### Protobuf

`api/proto/` is authoritative. `api/proto/latent-api.protos` is a sorted and exhaustive manifest of every `.proto` input. `crates/latent-rpc/build.rs` verifies that the manifest and directory are identical, uses the pinned vendored `protoc`, and emits messages, clients, servers, and a descriptor set into Cargo `OUT_DIR`.

Generated Rust is exposed by `latent-rpc` as:

- `latent_rpc::control::v1`;
- `latent_rpc::invocation::v1`;
- `latent_rpc::FILE_DESCRIPTOR_SET`.

The integration test in `crates/latent-rpc/tests/generated_services.rs` type-checks every generated client surface, every generated server trait/server wrapper, and the descriptor set. Adding a Protobuf service without generated compilable Rust therefore fails the workspace build.

### Component Model WIT

Checked-in WIT remains authoritative. `crates/latent-component-bindings/build.rs` is the single shared staging and generation owner for:

- `wit/platform/runtime` plus every platform dependency;
- `examples/echo-contract/wit` plus its context and log dependencies.

It emits bindings into `OUT_DIR` and exposes:

- `latent_component_bindings::host::runtime`;
- `latent_component_bindings::host::echo`;
- `latent_component_bindings::guest::runtime` on Wasm targets.

`latent-wasmtime` consumes the shared echo host bindings. `latent-toolchain-smoke` consumes the shared aggregate runtime bindings. The executable echo guest fixture still invokes `wit-bindgen` from the authoritative echo WIT in its component crate because canonical ABI exports must be generated in the final guest crate.

## Generated-output boundary

No generated Rust is committed under `api/proto`, `wit`, or an example `wit` directory. The foundation validator requires the two generation owners above, rejects the superseded duplicate build scripts, and rejects unlisted Protobuf files or generated language sources inside contract-authority directories.

Generated files may exist only in ignored build locations such as Cargo `OUT_DIR`, `target/contracts/`, SDK compiler output directories, and `target/capsules/`.

## Dependency graph boundary

`tools/validate_foundation.py` resolves all workspace path dependencies and performs cycle detection before contract compilation. A cycle is a validation error with the concrete dependency path. Missing path dependencies remain covered by the repository validator.

## Test foundation

`latent-testkit` exposes reusable primitives without starting service-owned resources:

- `DeterministicIds`, `ManualClock`, `TempWorkspace`, and the calling-thread `block_on` executor;
- `AsyncTestRuntime`, an explicitly constructed Tokio current-thread runtime with no worker pool;
- `ProcessHarness` and `CapturedProcess` for deterministic CLI/integration command construction and captured output;
- `CurrentProcessProbe` and `ProcessResources` for portable process identity and Linux `/proc` RSS, thread, file-descriptor, and socket observations.

A test creates these utilities explicitly. Merely linking a service crate creates no thread, process, socket, listener, or runtime.

## Clean-checkout sequence

The supported reference environment is Linux or WSL. Install the pinned Rust toolchains and targets, Python 3.13.5, `wasm-tools` 1.254.0, Buf 1.72.0, and the language SDK prerequisites documented in [toolchain.md](toolchain.md). A system `protoc` is not required because Rust generation uses the pinned vendored binary.

Run:

```bash
rustup toolchain install 1.97.1 --profile minimal --component rustfmt,clippy \
  --target wasm32-wasip2,wasm32-unknown-unknown
rustup toolchain install 1.94.1 --profile minimal

python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock

make phase1-foundation
make sdks
```

`make validate` is the equivalent complete command. The foundation-only command expands to:

```bash
cargo fmt --all --check
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked
cargo test --workspace --all-targets --all-features --locked
tools/validate_contracts.sh
```

Focused generation checks are available as:

```bash
make rpc-bindings
make component-bindings
make guest-bindings
```

## CI contract

`.github/workflows/ci.yml` runs for every pull request, pushes to `development`, and manual dispatches. Its Rust job verifies formatting, the whole workspace, host and guest Component Model bindings, RPC generation, Clippy, and tests. Separate jobs verify the MSRV, repository contracts and retained echo/containment integration, and all language SDK surfaces.

## Phase 0 continuity

The Phase 0 feasibility result is closed and authorizes Phase 1. The following commands remain supported:

| Command | Status | Purpose |
| --- | --- | --- |
| `make echo-capsule` | retained | Build and validate the maintained echo component |
| `make echo-capsule-reproducibility` | retained | Verify same-host byte reproducibility |
| `make phase0-spike-demo` | retained | Exercise the local feasibility path |
| `make phase0-gate-smoke` | retained | Validate the lightweight Phase 0 gate path |
| `make phase0-gate` | retained | Validate the complete retained evidence receipt |
| legacy per-crate binding build scripts | replaced | Centralized in `latent-component-bindings` |

The retained benchmark/evidence tooling remains under `benchmarks/phase0` and `tools/`. This foundation does not reinterpret the Phase 0 measurements; it promotes the proven echo/WIT/Wasmtime path into maintained build ownership.
