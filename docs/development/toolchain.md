# Phase 0 toolchain baseline

The Phase 0 baseline makes the interface scaffold executable and builds the first real Component Model capsule without implementing a service runtime. Exact project-selected versions live in [`tools/toolchain.toml`](../../tools/toolchain.toml); Rust dependency resolution is frozen by the committed root `Cargo.lock`.

## Selected versions

| Area | Version | Purpose |
| --- | ---: | --- |
| Rust toolchain | 1.97.1 | Default formatter, compiler, Clippy, test toolchain, and reproducible guest compiler |
| Rust MSRV | 1.94.1 | Oldest compiler checked for all native workspace targets |
| Rust guest target | `wasm32-wasip2` | Build the Rust echo capsule as a Component Model binary |
| Wasmtime | 47.0.3 | Host-side Component Model bindings and ephemeral typed fixture invocation |
| `wit-bindgen` | 0.60.0 | Generated Rust guest imports, exports, domain types, and canonical ABI glue |
| Tokio | 1.53.1 | Selected async runtime for later Phase 0 implementation work |
| Serde / `serde_json` | 1.0.229 / 1.0.150 | Rust contract serialization |
| TOML | 1.1.4 | Configuration parsing and serialization; the published crate carries `+spec-1.1.0` build metadata |
| BLAKE3 | 1.8.5 | Content hashing |
| Clap | 4.6.4 | CLI surfaces |
| `tempfile` | 3.27.0 | Test-only temporary storage |
| `wasm-tools` | 1.254.0 | Component validation and WIT inference for every package and built fixture |
| Buf | 1.72.0 | Protobuf linting and descriptor-set generation |
| Python / `jsonschema` | 3.13.5 / 4.26.0 | Repository, schema, and component-build validation |
| Go / Node / TypeScript / .NET | 1.23.2 / 22.16.0 / 5.8.3 / 8.0.423 | Cross-language interface compilation |
| Eclipse Temurin JDK | 21.0.11+10 | Exact Java compiler and runtime distribution (`setup-java` selector `21.0.11+10.0.LTS`) |
| Zig / Clang / C target | 0.16.0 / 21.1.8 / `x86_64-linux-gnu` | Exact bundled C frontend for the C11 header smoke test |

Workspace dependencies are exact requirements in the root `Cargo.toml`. New Phase 0 crates and targets consume them with `workspace = true` rather than selecting independent versions. Cargo ignores SemVer build metadata in dependency requirements, so the TOML requirement is deliberately written as `=1.1.4`; the resolved package recorded in `Cargo.lock` may display `1.1.4+spec-1.1.0`.

The echo guest is a `cdylib` example target owned by the already-locked `latent-toolchain-smoke` package. Its handwritten source remains under `examples/echo-contract/guest-rust/`; this arrangement keeps a single workspace lock graph while making the fixture's location and purpose explicit.

## Reproducibility boundary

CI uses the explicit `ubuntu-24.04` hosted-runner label instead of `ubuntu-latest`. Language and contract compilers are installed at the exact versions above and `tools/check_tool_versions.py` verifies the installed binaries before the SDK surfaces compile. The echo builder independently rejects Rust or `wasm-tools` versions that differ from `tools/toolchain.toml`, uses `--locked`, disables incremental compilation, sets `SOURCE_DATE_EPOCH=0`, remaps the checkout path to `/workspace`, and rebuilds from a clean fixed target directory.

`make echo-capsule-check` compares two clean component builds byte for byte. The claim is intentionally bounded to the same source tree, committed lockfile, Rust 1.97.1 toolchain, `wasm32-wasip2` target, release profile, and deterministic build path. Phase 0 does not claim bit identity across different host operating systems or linker implementations.

TypeScript is pinned by both `package.json` and `package-lock.json`. The SDK validation installs with `npm ci` and then verifies the local compiler version against `tools/toolchain.toml`; the CI workflow therefore does not duplicate the TypeScript version as an unrelated literal.

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

`tools/validate_contracts.sh` also performs the full echo gate:

```bash
python3 tools/build_echo_capsule.py --check-reproducible --run-component-tests
```

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

## Generated-output policy

Handwritten Rust, WIT, Protobuf, JSON Schema, examples, and SDK files remain authoritative. Build tooling writes only to Cargo `OUT_DIR` or ignored directories below `target/`:

- `tools/toolchain-smoke/build.rs` stages the runtime and echo worlds with repository-local WIT dependencies, then generates host and guest bindings from those staged trees.
- `tools/stage_runtime_wit.py` creates the equivalent deterministic layout for command-line validation.
- `tools/build_echo_capsule.py` writes the component, inferred WIT, computed-digest capsule manifest, stable build metadata, and local trust declaration below `target/capsules/echo-rust/`.
- `wasm-tools` JSON output, the Protobuf descriptor set, SDK compiler output, and C header smoke source are placed under `target/contracts/`.

The repository validator excludes known generated directories but continues to inspect every authoritative source file. Its traversal behavior has unit tests under `tools/tests/`.

## Allocation boundary

Building the guest starts no service, listener, socket, execution cell, worker thread, or persistent guest instance. The ignored component integration test creates one Wasmtime engine, linker, store, and component instance inside the test process, invokes the fixture, and drops them before returning. This test-only state is not service-owned and remains unrelated to capsule identity. `latent-testkit::block_on` continues to poll on the calling thread and creates no worker thread.
