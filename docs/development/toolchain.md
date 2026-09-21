# Toolchain and reproducibility baseline

The executable build foundation keeps Rust dependency requirements in the root
`Cargo.toml`, the resolved Rust graph in the committed `Cargo.lock`, and
compiler, contract-tool, SDK, and external guest-tool selections in
`tools/toolchain.toml`. It preserves the
Phase 0 Component Model evidence path and supplies maintained Protobuf RPC
generation, centralized WIT bindings and test infrastructure for the current
runtime and completed Phase 2 delivery surface. Toolchain and code-generation
steps are separate from the explicit [standalone node](../reference/standalone-node.md)
startup command.

See [build-foundation.md](build-foundation.md) for generation ownership, focused commands, test utilities, dependency-cycle validation, and the clean-checkout Phase 1 sequence.

## Version authorities

Version ownership is intentionally split by what consumes the value. Cargo dependency
updates must not require a second manually maintained Rust-dependency version table.

| Area | Authority | Purpose |
| --- | --- | --- |
| Rust toolchain, MSRV, and compilation targets | `tools/toolchain.toml` | Compiler and target qualification |
| Rust workspace dependencies | root `Cargo.toml` | Exact direct requirements; every versioned workspace dependency must use `=version` |
| Resolved Rust dependency graph | root `Cargo.lock` | Reproducible `--locked` builds |
| Guest `wit-bindgen` CLI release and archive digest | `[guest-tools.wit-bindgen]` in `tools/toolchain.toml` | Independently reviewed external generator binary |
| `wasm-tools`, Buf, Python, and schema tooling | `tools/toolchain.toml` | Contract validation toolchain |
| Go, Node, TypeScript, Java, .NET, Gradle, Zig, and C tooling | `tools/toolchain.toml` plus their native lock/config files where applicable | SDK and native fixture qualification |

`tools/validate_repository.py` enforces these ownership boundaries. In particular,
it rejects non-exact Cargo workspace requirements and rejects any reintroduced
`[rust.dependencies]` mirror in `tools/toolchain.toml`. Cargo ignores SemVer build
metadata in requirements, so an exact TOML requirement can resolve to a lockfile
version that additionally displays build metadata.

## Java 25 SDK baseline and migration

The Java SDK now targets Java 25, including generated protocol classes, tests
and packaged SDK classes. Java 21 cannot load the new SDK JAR. Consumers must
upgrade their application build/runtime to Java 25 before adopting it; changing
only the CI launcher while retaining `--release 21` is not this migration.
The minimum class-file runtime is Java 25, while repository qualification uses
the exact Temurin patch/build above. This does not qualify every later JDK,
Android or a Java guest runtime, and does not change the public SDK or wire API.

Set `JAVA_HOME` to that Temurin installation and put its `bin` first on `PATH`.
The standalone helper chooses `JAVA_HOME`, or resolves `java` from `PATH` when
it is unset, then uses that one installation's `javac`, `java` and `jar`.
A wrong explicit installation fails rather than falling back. Both the compiler's
own runtime and the runtime launcher must match the exact vendor and build;
only the Temurin `-LTS` suffix is normalized. Every probe retains its 30-second
limit. Gradle disables automatic discovery/downloads and uses `JAVA_HOME` with
the same exact identity check and explicitly selected execution launcher.

`tools/toolchain.toml` distinguishes runtime `25.0.4.1+1` from the exact
`actions/setup-java` selector `25.0.4+101.0.LTS`. Adoptium's SemVer metadata
encodes the fourth version component as `100 * patch + build`; here it is 101.
Do not substitute a floating major, omit the build metadata, or pass the
four-component runtime string as a SemVer selector. See the
[Temurin release](https://github.com/adoptium/temurin25-binaries/releases/tag/jdk-25.0.4.1%2B1)
and [Gradle compatibility matrix](https://docs.gradle.org/current/userguide/compatibility.html).
Gradle 9.1.0 is the pinned CI version; Java 25 requires Gradle 9.1.0 or newer.
CI verifies the distribution against the committed SHA-256 before extraction.

From the repository root, with the selected JDK and Python available:

```sh
python3 sdk/java-client/tools/java_toolchain.py check
python3 -m unittest tools.tests.test_check_tool_versions tools.tests.test_java_toolchain
python3 sdk/java-client/tools/generate_bridge.py --check
python3 sdk/java-client/tools/build.py test
python3 sdk/java-client/tools/build.py build
python3 sdk/java-client/tools/java_toolchain.py classes sdk/java-client/build/latent-java-client.jar
# Optional separate build path; JAVA_HOME must identify the selected Temurin JDK.
gradle --no-daemon -p sdk/java-client clean check
```

Standalone builds do not require Gradle or Maven. Both paths verify every SDK
class header as major 69, minor 0, rejecting empty outputs, Java 21 classes and
preview bytecode. Existing locked dependencies and generators are unchanged.
The small Python tests use mocked probes and synthetic class headers; they are
not evidence of Java compilation or a real-node transport run.

The existing SDK CI job executes Gradle and standalone semantic/transport/JAR
checks on `ubuntu-24.04` and retains `java-sdk-qualification-<source-sha>` with
source/JDK/Gradle/OS identities, logs, class-file checks and the standalone JAR
digest. The existing repository-contract job runs the Java participant in the
[separate-node provider workflow](../testing/sdk-provider-workflow.md), retaining
its receipts in the existing `phase-1-bounded-conformance-<source-sha>` artifact.
Use successful results from the same reviewed source revision; configuration
alone is not a qualification pass. Historical Java 21 release documentation and
retained Windows tests compiled with `--release 21` remain historical evidence,
not Java 25-targeted Windows qualification. No milestone or phase gate is added.

## Reproducibility boundary

CI uses `ubuntu-24.04`, not a floating runner label. Rust, contract tools, and language compilers are installed at the exact versions above. `tools/check_tool_versions.py` validates installed SDK compilers. Each SDK version probe has a 30-second timeout so a non-responsive local tool fails validation instead of blocking indefinitely. TypeScript is pinned in both `package.json` and `package-lock.json` and installed with `npm ci`.

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

Routine PR CI runs the executable Phase 0 outcome/recovery matrix immediately
after fixture generation in `CI / Repository contracts`. The separate runtime
regression workflow collects a smoke baseline only on manual dispatch; it is not
an additional path-filtered PR check. See [CI ownership](../testing/phase0-ci-layout.md).
Fresh Phase 2 evidence uses the bounded commands in
[offline validation](../testing/phase-2-offline-validation.md) and the
[operator walkthrough](standalone-quickstart.md#bounded-phase-2-operator-workflow).

The MSRV check is reproducible with:

```bash
rustup toolchain install 1.94.1 --profile minimal
cargo +1.94.1 check --workspace --all-targets --all-features --locked
```

Install the remaining contract tools at their selected versions, for example `cargo install wasm-tools --version 1.254.0 --locked` and Buf 1.72.0. The Rust toolchain file installs `rustfmt`, Clippy, `wasm32-wasip2`, and `wasm32-unknown-unknown`.

## Linux and evidence boundary

Linux or WSL may run `make validate`, `make phase0-gate-smoke`, and `make phase0-gate`.
Only a clean native-Linux host or VM may create replacement **Phase 0**
calibration, profiling or resource-soak evidence; those wrappers reject WSL and
containers because their measurements establish a native-host reference.
The separate Phase 1 collectors record their actual supported environment.
The completed [extension comparisons](../phase-1-extension-completion.md),
including Docker and Kubernetes, ran on the documented Docker Desktop/WSL2
host. They are valid for that measured environment and do not replace the
Phase 0 native baseline or claim bare-metal/cloud capacity.

Before a full authorization attempt, verify:

```bash
git status --porcelain --untracked-files=all
```

The retained August 30 Phase 0 receipt records an authorized pass for its canonical execution identity. It remains historical evidence; the build foundation does not modify the measured thresholds or results.

## Generated-output policy

The [Wasmtime security baseline](wasmtime-security-update.md) records the 47.0.4
advisory scan, native-loader review and runtime/compiler upgrade requirements.

Handwritten Rust, WIT, Protobuf, JSON Schema, examples, and SDK sources remain authoritative. Generated build products normally live in Cargo `OUT_DIR`, `target/contracts/`, `target/capsules/`, and SDK compiler directories. The type-only codec fixture described below is an explicit checked-in exception:

- `crates/latent-rpc/build.rs` generates all Protobuf messages, clients, servers, and the embedded descriptor set;
- `crates/latent-component-bindings/build.rs` stages the aggregate runtime and echo WIT worlds and emits shared host/guest binding invocations;
- the maintained echo, containment, generic, and capabilities fixtures generate canonical ABI exports in their final guest crates from authoritative WIT;
- `tools/build_echo_capsule.py` emits the validated component, extracted interface, computed digest, generated manifest, typed `contracts.json`, `deployment.json`, `input.json`, and build receipt;
- `tools/stage_runtime_wit.py`, `wasm-tools`, and Buf emit validation artifacts under `target/contracts/`.

Executable capsule binaries and generated transport source are not checked in. The small `crates/latent-wasmtime/src/values/types.wasm` fixture contains Component Model type declarations for codec unit tests and is regenerated from adjacent `types.wat`. `tools/validate_contracts.sh` parses that source using pinned `wasm-tools`, compares the generated bytes with the checked-in fixture, and validates the result. This fixture check does not extend the historical echo reproducibility claim to other hosts or toolchains. The foundation validator continues to check authority boundaries, generation ownership, exhaustive Protobuf inputs, and the absence of superseded duplicate build scripts.

## Allocation boundary

Build and validation code starts compiler/validator subprocesses only when a command explicitly runs. Linking generated bindings creates no engine, store, listener, socket, process, service thread, execution cell, or service-owned async runtime. `latent-testkit::block_on` polls on the calling thread; `AsyncTestRuntime` is explicitly constructed for tests and uses Tokio's current-thread scheduler without a worker pool.

## Phase 3 guest contract tools

The full contract gate also builds the Rust guest SDK examples and the C
canonical ABI fixture. Install the guest `wit-bindgen` CLI selected by
`[guest-tools.wit-bindgen]` in `tools/toolchain.toml` and the pinned Zig
toolchain alongside the existing Rust, Python, and wasm-tools pins. On Linux
x86_64, `python3 tools/install_guest_bindgen.py "$HOME/.local/lsf-guest-tools"`
reads that external-tool contract, downloads the matching upstream release, and
verifies its committed SHA-256 before writing the executable into a new
directory; add that directory to `PATH`. CI uses this same verifier and the
existing pinned Zig setup action. The installer refuses to overwrite an existing
executable. The guest CLI selection is deliberately independent of the Cargo
`wit-bindgen` crate requirement so a Dependabot crate update cannot silently
replace a reviewed executable checksum.

Generated source, components and observations stay under the selected target
root. See the [guest SDK workflow](../component-development/guest-sdk.md) for
build, signed admission and actual Rust/C runtime checks.
