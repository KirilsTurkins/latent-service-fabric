# Toolchain and reproducibility baseline

The executable build foundation uses exact project-selected versions from `tools/toolchain.toml` and the committed root `Cargo.lock`. It preserves the Phase 0 Component Model feasibility path while adding maintained Protobuf RPC generation, centralized WIT bindings, tracing dependencies, and reusable test infrastructure. It does not implement a production service runtime.

See [build-foundation.md](build-foundation.md) for generation ownership, focused commands, test utilities, dependency-cycle validation, and the clean-checkout Phase 1 sequence.

## Selected versions

| Area | Version | Purpose |
| --- | ---: | --- |
| Rust toolchain | 1.97.1 | Default formatter, compiler, Clippy, tests, code generation, and component build |
| Rust MSRV | 1.94.1 | Oldest compiler checked for all native workspace targets |
| Rust binding-check target | `wasm32-wasip2` | Compile generated Rust guest bindings against Preview 2 |
| Rust component-core target | `wasm32-unknown-unknown` | Build self-contained cores before explicit componentization |
| Tokio | 1.53.1 | Async runtime dependency and explicit current-thread test runtime |
| Prost | 0.14.4 | Generated Protobuf message implementation |
| Tonic / `tonic-prost` | 0.14.6 / 0.14.6 | Generated RPC clients, servers, and Prost codec |
| `tonic-prost-build` | 0.14.6 | Build-time Rust generation from every authoritative `.proto` |
| `protoc-bin-vendored` | 3.2.0 | Pinned cross-platform `protoc`; no ambient compiler lookup |
| Tracing / tracing-subscriber | 0.1.44 / 0.3.23 | Structured instrumentation baseline and compile probe |
| Wasmtime | 47.0.3 | Component Model host bindings and Phase 0 execution backend |
| `wit-bindgen` | 0.60.0 | Guest bindings and canonical ABI exports generated from WIT |
| Serde / `serde_json` | 1.0.229 / 1.0.150 | Rust contract serialization |
| TOML | 1.1.4 | Configuration parsing and serialization |
| BLAKE3 / SHA-256 | 1.8.5 / 0.10.9 | Cache/prepared identity and artifact digest verification |
| Clap / `tempfile` | 4.6.4 / 3.27.0 | CLI surfaces and test-only temporary storage |
| `wasm-tools` | 1.254.0 | WIT parsing, validation, componentization, and interface extraction |
| Buf | 1.72.0 | Protobuf linting and independent descriptor-set generation |
| Python / `jsonschema` | 3.13.5 / 4.26.0 | Repository and Draft 2020-12 schema validation |
| Go / Node / TypeScript / .NET | 1.23.2 / 22.16.0 / 5.8.3 / 8.0.423 | Cross-language interface compilation |
| Eclipse Temurin JDK | 21.0.11+10 | Java SDK compilation |
| Zig / Clang / C target | 0.16.0 / 21.1.0 / `x86_64-linux-gnu` | Pinned C11 header smoke test |

Workspace dependencies are exact requirements and workspace crates consume them with `workspace = true`. Cargo ignores SemVer build metadata in requirements, so TOML is pinned as `=1.1.4`; the resolved package may display `1.1.4+spec-1.1.0` in `Cargo.lock`.

## Reproducibility boundary

CI uses `ubuntu-24.04`, not a floating runner label. Rust, contract tools, and language compilers are installed at the exact versions above. `tools/check_tool_versions.py` validates installed SDK compilers. TypeScript is pinned in both `package.json` and `package-lock.json` and installed with `npm ci`.

Rust Protobuf generation uses `protoc-bin-vendored`; the build does not depend on a runner or workstation `protoc`. The exhaustive `api/proto/latent-api.protos` manifest and foundation validator prevent undeclared input drift. Generated RPC and WIT source is written only to Cargo `OUT_DIR` and is recreated from authoritative inputs on each clean build.

The echo build removes ambient Rust flags and target-directory overrides from child Cargo processes, disables incremental compilation, fixes release settings, uses the committed lockfile, builds a `wasm32-unknown-unknown` core, wraps it with the pinned `wasm-tools`, validates the result, and rejects interface drift. `make echo-capsule-reproducibility` performs two isolated clean builds and compares complete component bytes.

The Phase 0 reproducibility claim remains same-checkout, same-host, pinned-toolchain byte identity. Cross-platform byte identity is not claimed. The retained native collector receipt and benchmark evidence are documented in [Phase 0 completion](../phase-0-completion.md).

## Clean-checkout validation

The supported reference environment is Linux or WSL. Install the selected toolchains, create the Python environment, then run:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

`make validate` executes formatting, locked workspace checks, Clippy, tests, repository/foundation/contract validation, retained echo and containment integration, and all SDK compilation. `make phase1-foundation` runs the Rust and contract subset. A missing or stale `Cargo.lock` fails all locked commands.

The MSRV check is reproducible with:

```bash
rustup toolchain install 1.94.1 --profile minimal
cargo +1.94.1 check --workspace --all-targets --all-features --locked
```

Install the remaining contract tools at their selected versions, for example `cargo install wasm-tools --version 1.254.0 --locked` and Buf 1.72.0. The Rust toolchain file installs `rustfmt`, Clippy, `wasm32-wasip2`, and `wasm32-unknown-unknown`.

## Linux and evidence boundary

Linux or WSL may run `make validate`, `make phase0-gate-smoke`, and `make phase0-gate`. Only a clean native-Linux host or VM may create replacement calibration, profiling, or resource-soak evidence; those wrappers reject WSL and containers because the measurements establish a native-host reference.

Before a full authorization attempt, verify:

```bash
git status --porcelain --untracked-files=all
```

The retained August 30 Phase 0 receipt records an authorized pass for its canonical execution identity. It remains historical evidence; the build foundation does not modify the measured thresholds or results.

## Generated-output policy

Handwritten Rust, WIT, Protobuf, JSON Schema, examples, and SDK sources remain authoritative. Generated output is restricted to Cargo `OUT_DIR`, `target/contracts/`, `target/capsules/`, and SDK compiler directories:

- `crates/latent-rpc/build.rs` generates all Protobuf messages, clients, servers, and the embedded descriptor set;
- `crates/latent-component-bindings/build.rs` stages the aggregate runtime and echo WIT worlds and emits shared host/guest binding invocations;
- the echo guest fixture generates canonical ABI exports in its final component crate from authoritative WIT;
- `tools/build_echo_capsule.py` emits the validated component, extracted interface, computed digest, generated manifest, and build receipt;
- `tools/stage_runtime_wit.py`, `wasm-tools`, and Buf emit validation artifacts under `target/contracts/`.

No generated component binary or generated transport source is checked in. The foundation validator checks authority boundaries, generation ownership, exhaustive Protobuf inputs, and the absence of superseded duplicate build scripts.

## Allocation boundary

Build and validation code starts compiler/validator subprocesses only when a command explicitly runs. Linking generated bindings creates no engine, store, listener, socket, process, service thread, execution cell, or service-owned async runtime. `latent-testkit::block_on` polls on the calling thread; `AsyncTestRuntime` is explicitly constructed for tests and uses Tokio's current-thread scheduler without a worker pool.
