# Phase 0 Wasmtime echo backend

Issue #21 introduced the first executable `ExecutionBackend` for the narrow `examples:echo/service@0.1.0` contract. The maintained `Phase0WasmtimeEngineFactory` and `Phase0WasmtimeBackend` now preserve that contract as a compatibility facade over the shared Phase 1 backend. This page describes the retained echo path; see [the generic Wasmtime runtime](../runtime/wasmtime.md) and [activation capabilities](../runtime/capabilities.md) for the current runtime surface. These updates do not revise the archived Phase 0 measurements or authorization.

## Engine profile

`Phase0WasmtimeEngineFactory` constructs one node-owned Wasmtime 47.0.3 engine through the shared factory, with the Component Model, async support, fuel accounting, and epoch interruption enabled. Wasm and asynchronous stacks have explicit maximum sizes, and detailed Wasm backtraces are disabled. The shared runtime owns one `latent-wasmtime-epoch` helper thread per factory, shared by backend handles and prepared uses. The factory creates no Tokio runtime, listener, socket, execution cell, or persistent guest instance. The final shared-runtime owner wakes and joins the epoch helper when dropped.

The generated profile and preparation key include compatibility-relevant engine, store, cache, context, codec, and log bounds, including aggregate linear-memory accounting and the Phase 0 guest-to-host transfer ceiling. A key from a different Wasmtime version, target, CPU profile, or configuration is rejected before compilation. The internal prepared handle also binds component content and bounded artifact, manifest, and contract metadata, so a changed capsule resource ceiling cannot reuse an older prepared policy. Deployment-only budget updates can reuse the compiled artifact while receiving a newly admitted revision and grant.

## Trust and interface validation

`ExecutionBackend::prepare` on the Phase 0 facade accepts the locally built artifact from `tools/build_echo_capsule.py`. The facade and shared preparation path verify the following before publishing a prepared cache entry:

- the release and SHA-256 component digest;
- the manifest world, backend, required imports, exported contract, and resource ceiling;
- the Component Model binary through `wasmtime::component::Component`;
- the component imports, exports, and supported value signatures against the manifest and supplied contract metadata;
- linker resolution for the echo fixture's required `latent:context/context@0.1.0` and `latent:log/log@0.1.0` imports; and
- an additional typed echo-world signature check using `ServicePre` generated from the authoritative WIT.

The shared linker installs only the Phase 1 context, log, monotonic-clock, and wall-clock interfaces; it never installs ambient WASI. The Phase 0 facade restricts its manifest to the two required context and log imports, and actual component imports must match. The echo and oversized-log fixtures remain self-contained `wasm32-unknown-unknown` cores wrapped with `wasm-tools component new`, so they receive no clock, filesystem, network, environment, process, random, state, blob, secret, event, timer, or other undeclared capability. An extra or missing import or export fails preparation.

## Invocation ownership

Each `invoke` creates a fresh:

- `Store<HostState>`;
- aggregate resource limiter;
- activation context;
- bounded invocation log counters and budget accounting; and
- component instance.

The store is initialized with the invocation fuel grant, an epoch deadline, and the effective minimum of the invocation, cell, and node memory limits. Linear-memory growth is accounted across every memory in the store: a component with multiple memories cannot multiply the activation's `memory_bytes` grant, and `peak_memory_bytes` reports the aggregate peak rather than the largest individual memory.

Before instantiation, `backend.rs` configures `Store::set_hostcall_fuel` once for the fresh store. Wasmtime applies this allowance to each guest-to-host Component Model transfer. The Phase 0 facade caps the configured allowance at 80 KiB, retaining the 65,536-byte echo result plus 16 KiB of canonical-ABI headroom; callers may configure a tighter limit. Independent log message, field, entry-count, and complete encoded-record byte limits are enforced after lifting. Using the 256-byte log-message ceiling as the store-wide allowance would reject valid echo results.

The facade converts the legacy echo request to the shared bounded value codec, and the backend invokes the validated `echo` export through Wasmtime's dynamic Component Model API. Wasmtime owns canonical-ABI lowering, lifting, and post-return. The facade maps successful results back to UTF-8 bytes and the declared `empty-message` and `message-too-large` variants to bounded JSON with media type `application/vnd.latent.echo-error+json`. Runtime failures, cancellation, and deadlines use the maintained containment path described in [activation-containment.md](activation-containment.md).

A valid guest log write is offered immediately to the bounded node sink while the activation is running. Sink rejection returns the WIT `unavailable` error and refunds the uncommitted log reservation; accepted records remain subject to bounded node retention. Logs are not deferred until instance teardown. The instance, store, host state, decoded values, and activation-owned guards are reclaimed before the backend returns a reusable cleanup proof, so a later invocation starts with fresh guest state.

## Prepared cache

Preparation retains immutable compiled component state, the linker pre-instance, validated dynamic export indices and signatures, and the declared resource ceiling. It retains no guest store or instance. The shared least-recently-used cache has separate entry, source-component-byte, metadata-byte, and compiled-image-byte limits. Compilation uses a bounded, nonqueueing reservation with separate in-flight source and metadata accounting. `ExecutionBackend::release` removes a resident entry, and `PreparedCacheSnapshot` exposes these limits and counters.

Compiled-image accounting uses Wasmtime's reported `Component::image_range`; it does not measure total compiler heap or process RSS. Resident cache accounting excludes an evicted runtime still pinned by an active prepared use. Such a pin remains owned until that use finishes, and the shared active-instance limit bounds these uses. Retained Phase 0 measurements remain historical evidence for their original configuration and source revision.

## Validation

The repository contract gate builds the Issue #19 echo artifact, loads its generated component bytes and `capsule.json`, and invokes it through the maintained Phase 0 facade. It verifies that a 65,536-byte success result round-trips through the shared backend and legacy response framing. It also builds a same-interface capsule that passes a string larger than the Phase 0 guest-to-host allowance to `latent:log/log`, then verifies deterministic host-call-fuel rejection before the sink accepts bytes:

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
cargo build -p latent-toolchain-smoke --example oversized-log-capsule \
  --target wasm32-unknown-unknown --release --locked
wasm-tools component new \
  target/wasm32-unknown-unknown/release/examples/oversized_log_capsule.wasm \
  -o target/capsules/oversized-log/oversized-log-capsule.wasm
LSF_ECHO_COMPONENT=target/capsules/echo/echo-capsule.wasm \
LSF_ECHO_CAPSULE=target/capsules/echo/capsule.json \
LSF_OVERSIZED_LOG_COMPONENT=target/capsules/oversized-log/oversized-log-capsule.wasm \
  cargo test -p latent-wasmtime --test echo_backend --locked -- --ignored --nocapture
```
