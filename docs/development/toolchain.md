# Phase 0 toolchain baseline

The Phase 0 baseline makes the interface scaffold executable and builds the first Rust-authored echo component fixture without implementing a service runtime. Exact project-selected versions live in [`tools/toolchain.toml`](../../tools/toolchain.toml); Rust dependency resolution is frozen by the committed root `Cargo.lock`.

## Selected versions

| Area | Version | Purpose |
| --- | ---: | --- |
| Rust toolchain | 1.97.1 | Default formatter, compiler, Clippy, tests, and echo-component build |
| Rust MSRV | 1.94.1 | Oldest compiler checked for all native workspace targets |
| Rust guest target | `wasm32-wasip2` | Compile generated guest bindings and the echo Component Model fixture |
| Wasmtime | 47.0.3 | Host-side Component Model engine, generated bindings, and Phase 0 echo execution |
| `wit-bindgen` | 0.60.0 | Guest-side Rust bindings and canonical ABI exports generated from WIT |
| Tokio | 1.53.1 | Selected async runtime for later Phase 0 implementation work |
| Serde / `serde_json` | 1.0.229 / 1.0.150 | Rust contract serialization |
| TOML | 1.1.4 | Configuration parsing and serialization; the published crate carries `+spec-1.1.0` build metadata |
| BLAKE3 | 1.8.5 | Runtime cache keys and prepared-component identity |
| SHA-256 (`sha2`) | 0.10.9 | Component digest verification against generated capsule metadata |
| Clap | 4.6.4 | CLI surfaces |
| `tempfile` | 3.27.0 | Test-only temporary storage |
| `wasm-tools` | 1.254.0 | WIT parsing, component validation, and interface extraction |
| Buf | 1.72.0 | Protobuf linting and descriptor-set generation |
| Python / `jsonschema` | 3.13.5 / 4.26.0 | Repository, generated capsule, and Draft 2020-12 schema validation |
| Go / Node / TypeScript / .NET | 1.23.2 / 22.16.0 / 5.8.3 / 8.0.423 | Cross-language interface compilation |
| Eclipse Temurin JDK | 21.0.11+10 | Exact Java compiler and runtime distribution (`setup-java` selector `21.0.11+10.0.LTS`) |
| Zig / Clang / C target | 0.16.0 / 21.1.8 / `x86_64-linux-gnu` | Exact bundled C frontend for the C11 header smoke test |

Workspace dependencies are exact requirements in the root `Cargo.toml`. Phase 0 targets consume them with `workspace = true` rather than selecting independent versions. Cargo ignores SemVer build metadata in dependency requirements, so the TOML requirement is deliberately written as `=1.1.4`; the resolved package recorded in `Cargo.lock` may display `1.1.4+spec-1.1.0`.

## Reproducibility boundary

CI uses the explicit `ubuntu-24.04` hosted-runner label instead of `ubuntu-latest`. Language and contract compilers are installed at the exact versions above and `tools/check_tool_versions.py` verifies the installed binaries before the SDK surfaces compile. The C check does not use the runner-provided `cc`; it uses Zig 0.16.0's bundled Clang 21.1.8 frontend with the explicit `x86_64-linux-gnu` target and C11 mode. Runner-provided shell and filesystem utilities remain outside the compiler identity boundary.

TypeScript is pinned by both `package.json` and `package-lock.json`. The SDK validation installs with `npm ci` and then verifies the local compiler version against `tools/toolchain.toml`; the CI workflow therefore does not duplicate the TypeScript version as an unrelated literal.

The echo build tool requires the active Rust and `wasm-tools` versions to equal the baseline. It removes ambient `RUSTFLAGS`, `CARGO_ENCODED_RUSTFLAGS`, and `CARGO_TARGET_DIR` from the child Cargo environment; disables incremental compilation; fixes release codegen units, debug information, stripping, locale, timezone, and `SOURCE_DATE_EPOCH`; and always uses the committed lockfile. `make echo-capsule-reproducibility` performs two isolated clean builds and compares the complete component bytes before publishing the generated output.

The Phase 0 reproducibility claim is deliberately bounded: byte identity is verified for the same checkout and source path on the same host platform with the pinned compiler, target, lockfile, and canonical release settings. Cross-platform byte identity is not claimed.

## Clean-checkout validation sequence

The supported reference environment is Linux or WSL. Install the versions above, then run this sequence from a clean checkout:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

`make validate` executes, in order through its prerequisites:

```bash
cargo fmt --all --check
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked
cargo test --workspace --all-targets --all-features --locked
tools/validate_contracts.sh
tools/validate_sdks.sh
```

`tools/validate_contracts.sh` also compiles the generated echo bindings for `wasm32-wasip2`, builds the release component twice, requires byte-identical output, validates the binary with `wasm-tools`, extracts its interface, rejects any import/export drift, and emits generated capsule metadata with the actual SHA-256 digest.

The root lockfile is authoritative. Neither local validation nor CI generates or substitutes a dependency graph; a missing or stale `Cargo.lock` causes the `--locked` commands and repository validator to fail.

The MSRV check used by CI can also be reproduced explicitly:

```bash
rustup toolchain install 1.94.1 --profile minimal
cargo +1.94.1 check --workspace --all-targets --all-features --locked
```

The Rust toolchain file installs `rustfmt`, Clippy, and `wasm32-wasip2`. Install the remaining contract tools at the selected versions, for example with `cargo install wasm-tools --version 1.254.0 --locked` and the Buf 1.72.0 release binary. Verify prerequisite resolution before validation with:

```bash
rustc --version
cargo --version
wasm-tools --version
buf --version
python --version
go version
node --version
node sdk/typescript-client/node_modules/typescript/bin/tsc --version
javac -version
java -XshowSettings:properties -version
dotnet --version
zig version
```

## Echo component commands

Build and validate one generated artifact:

```bash
make echo-capsule
```

Verify the documented reproducibility boundary:

```bash
make echo-capsule-reproducibility
```

The direct command accepts `CARGO`, `RUSTC`, and `WASM_TOOLS` executable overrides and an optional output directory:

```bash
python3 tools/build_echo_capsule.py --verify-reproducible
```

## Generated-output policy

Handwritten Rust, WIT, Protobuf, JSON Schema, examples, and SDK files remain authoritative. Build tooling writes only to Cargo `OUT_DIR`, `target/contracts/`, or `target/capsules/`:

- `tools/toolchain-smoke/build.rs` stages the runtime world and its local WIT dependencies under `OUT_DIR`, then compiles host or guest bindings from that staged tree.
- The `echo-capsule` target generates bindings directly from `examples/echo-contract/wit/echo.wit` and the checked-in context and log WIT packages. It does not copy or hand-maintain ABI types.
- `tools/build_echo_capsule.py` writes the validated component, extracted WIT/JSON interface, computed digest, generated capsule manifest, and stable local-build receipt under `target/capsules/echo/`.
- `tools/stage_runtime_wit.py` creates the equivalent deterministic layout for command-line contract validation.
- `wasm-tools` JSON output, the Protobuf descriptor set, SDK compiler output, and C header smoke source are placed under `target/contracts/`.

No generated echo binary is checked in. The checked-in `examples/echo-contract/capsule.json` remains a schema-valid contract example with a placeholder digest; the generated copy replaces that digest with the artifact's actual SHA-256 value.

The repository validator excludes known generated directories but continues to inspect every authoritative source file. Its traversal behavior and the echo build tool have unit tests under `tools/tests/`.

## Allocation boundary

The build and validation foundation compiles files and starts only compiler/validator subprocesses. It does not create a Wasmtime engine or store, an async runtime, a service process, a thread or thread pool owned by a capsule, a listener, an execution cell, or any service-owned idle resource. `latent-testkit::block_on` polls on the calling thread and creates no worker thread.
