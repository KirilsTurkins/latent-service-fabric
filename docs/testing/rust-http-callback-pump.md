# Rust HTTP callback readiness and cancellation

The Rust standard-WASI adapter uses `sdk/wasi-http-runtime/pump.rs`. Its
async exports must return `Pending` to the pinned bindgen executor rather than
run a blocking wait loop inside a callback. An entered callback excludes other
calls into that component instance: successful host I/O alone cannot make a
sibling callback enter it. The CLR pump remains independently owned and unchanged.

## Ownership and scheduling

One private async driver polls the original accepted HTTP and timer futures.
The selected `rust-wasi-http-cooperative` Cargo feature enables the pinned
bindgen executor's async spawn and real inter-task wakeups. It is selected by
the adapter build recipe, not by a guest declaration or an ordinary host default.
Synchronous `ready`, `get` and stream operations inspect existing state and
signal the driver; they do not poll an async import in a synchronous WIT task.

Each waiter retains its original readiness sources and current waker. The
driver wakes only callers whose actual sources became ready. The operation
and deferred-retirement capacity remains 32; at most 64 live waiters and 64
sources per wait are admitted. Dropped waiters release their sources and their
slots can be reused. Duplicate input sources preserve their original indices.

Dropping an accepted operation from a synchronous resource destructor retains
its pinned future, original activation owner and quota slot. Only the private
async root drain destroys them, in the driver's original async task. Drain
refuses live waiters or unresolved accepted work; it neither cancels unrelated
siblings nor refunds a physically retained owner. Four immediate HTTP state
transitions yield back to the executor before further real work is polled.

## Executed controls

The maintained `rust-wasi-http-runtime.yml` owner compiles the selected backend,
verifies its source and complete WIT surface, runs native bounded-state controls,
and executes a separate compiled probe against Wasmtime. Pipeline failures are
propagated through `tee`; a log upload cannot turn a failed executable into a pass.
The workflow records observations, not a hard-coded test-count requirement.

The actual guest probe imports two independently held operations. The host
releases only the sibling and requires it to return while the original remains
held. A separate operation is abandoned while its host future is still live;
only the explicit async drain may destroy it. The engine must then report empty
concurrent state. Native tests additionally cover cancellation, waiter capacity,
index preservation, waker replacement and refusal of premature drain.

With the repository-pinned Rust toolchain and wasm-tools installed:

```sh
rustc --edition=2021 --test sdk/wasi-http-runtime/pump.rs -o /tmp/rust-http-pump-controls
/tmp/rust-http-pump-controls
cargo build --locked -p latent-toolchain-smoke --target wasm32-unknown-unknown \
  --example rust-http-pump-probe --features rust-wasi-http-cooperative --release
wasm-tools component new \
  target/wasm32-unknown-unknown/release/examples/rust_http_pump_probe.wasm \
  -o /tmp/rust-http-pump-probe.wasm
wasm-tools validate --features all /tmp/rust-http-pump-probe.wasm
cargo --config .cargo/managed-guest.toml --config profile.dev.opt-level=1 run \
  --locked -p latent-toolchain-smoke --example rust-http-pump-control \
  -- /tmp/rust-http-pump-probe.wasm
```

## Evidence boundary

Hosted run `42358646857` compiled the adapter and probe and passed both the five
observed native cases and the actual guest sibling/cancellation/empty-state
control. Its tested source tree is `407134dd76c12361dda2562175f7c9d71186ba1c`.
This is callback-mechanism evidence, not signed-node application qualification,
a general memory bound, arbitrary Rust dependency support, or completion of
#689/#743.

The [fixed combined diagnostic](rust-combined-http-diagnostic.md) still retains
its original compiler failure and exact frozen graph. Changing the adapter
source does not rewrite or silently replace those historical bytes. Separate
run `42359431189` explicitly recomposed only the adapter, preserving the
application and forwarding root. Core provenance and interface checks passed,
but its signed invocation trapped after 6,924 microseconds with two outbound
requests. That run is a failure, not a passing four-request witness. Keep the PR
draft until the corrected graph and its source provenance pass the unchanged
signed progress and physical-retirement gates on the final head.
