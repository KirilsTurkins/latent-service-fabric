# Phase 0 Wasmtime echo backend

Issue #21 implements the first executable `ExecutionBackend` for one deliberately narrow contract: `examples:echo/service@0.1.0`. It is a spike boundary, not the generic Phase 1 component dispatcher.

## Engine profile

`Phase0WasmtimeEngineFactory` constructs one node-owned Wasmtime 47.0.3 engine with the Component Model and Component Model async support enabled. Fuel accounting and epoch interruption are enabled, the Wasm and asynchronous stacks have explicit maximum sizes, and detailed Wasm backtraces are disabled. The factory does not create a Tokio runtime, worker thread, listener, socket, execution cell, or persistent component instance.

The generated profile and preparation key include a digest of every Phase 0 engine, store, cache, and log bound that affects compatibility. A preparation key created by a different Wasmtime version, target, CPU profile, or configuration is rejected before compilation.

## Trust and interface validation

`ExecutionBackend::prepare` accepts the locally built artifact from `tools/build_echo_capsule.py`. Before retaining any prepared state it verifies:

- the release and SHA-256 component digest;
- the manifest world, backend, required imports, exported contract, and resource ceiling;
- the Component Model binary through `wasmtime::component::Component`;
- the exact top-level component imports and export;
- linker resolution using only `latent:context/context@0.1.0` and `latent:log/log@0.1.0`; and
- the typed `examples:echo/service@0.1.0` export indices generated from the authoritative WIT.

The linker never installs WASI. Therefore the guest receives no filesystem, network, environment, process, random, clock, state, blob, secret, event, timer, or other undeclared authority. Any extra or missing import/export fails preparation deterministically.

## Invocation ownership

Each `invoke` creates a fresh:

- `Store<HostState>`;
- static resource limiter;
- activation context;
- bounded invocation log buffer; and
- component instance.

The store is initialized with the invocation fuel grant, an epoch deadline, and the effective minimum of the invocation, cell, and node memory limits. The generated typed binding calls `echo`; no handwritten canonical-ABI value decoding is used. Success returns UTF-8 bytes. The declared `empty-message` and `message-too-large` variants return a bounded JSON domain-error payload with media type `application/vnd.latent.echo-error+json`. Wasmtime call failures become a bounded `GuestOutcome::Trapped`; timeout and running-cancellation classification is completed by issue #22.

The instance and store are dropped before logs are published and before `invoke` returns. Repeated calls cannot retain prior linear memory, input, metadata, activation identity, or host state.

## Prepared cache

Preparation retains only node-owned compiled component state, the linker pre-instance, generated typed export indices, and the declared resource ceiling. It never retains a guest store or instance. The cache is bounded by both entry count and total source-component bytes and evicts least-recently-used entries. `ExecutionBackend::release` removes an entry explicitly. `PreparedCacheSnapshot` exposes the current and maximum accounting for tests and the spike harness.

The byte bound accounts for source component bytes, while entry count bounds compiled objects. Phase 0 does not claim a byte-exact measurement of compiler-owned native code; baseline measurement and production cache admission are later work.

## Validation

The repository contract gate builds the echo component and invokes it through the backend:

```bash
tools/validate_contracts.sh
```

Focused commands are:

```bash
cargo fmt --all --check
cargo check --workspace --all-targets --all-features --locked
cargo clippy --workspace --all-targets --all-features --locked
cargo test --workspace --all-targets --all-features --locked
python3 tools/build_echo_capsule.py --verify-reproducible
LSF_ECHO_COMPONENT=target/capsules/echo/echo-capsule.wasm \
  cargo test -p latent-wasmtime --test echo_backend --locked -- --ignored --nocapture
```
