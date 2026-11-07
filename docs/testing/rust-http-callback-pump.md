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
calls a synchronous readiness observation while both are pending, then releases
only the sibling and requires it to return while the original remains held.
A separate operation is abandoned while its host future is still live; only
the explicit async drain may destroy it. The engine must then report empty
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
cargo --config .cargo/managed-guest.toml --config profile.dev.opt-level=1 run \
  --locked -p latent-toolchain-smoke --example rust-http-pump-control \
  -- /tmp/rust-http-pump-probe.wasm --native-profile
```

The last invocation additionally selects the engine's more-async-builtins,
component threading and async-stackful flags. It remains a mechanism control,
not the authenticated combined host or a signed application execution.

## Evidence boundary

Hosted run `42358646857` compiled the adapter and probe and passed both the five
observed native cases and the actual guest sibling/cancellation/empty-state
control. Its tested source tree is `407134dd76c12361dda2562175f7c9d71186ba1c`.
The maintained backend run `42360961390` passed on `5462d84a`. Additional
run `42361351398` passed the synchronous readiness observation under both
ordinary and native-enabled engine configurations. Its six-member archive
passed CRC; SHA-256 is
`14918b3591eaf151c97e553391b6c1dc58b1071ea7bd1715c31e1d32ad684133`.
These are callback-mechanism observations, not signed-node application
qualification, a general memory bound, arbitrary Rust dependency support,
or completion of #689/#743.

## Independent fixture failure exposed after the callback correction

The [fixed combined diagnostic](rust-combined-http-diagnostic.md) retains its
original compiler failure and exact frozen graph. Changing adapter or fixture
source does not rewrite those historical bytes.

Separate run `42359431189` explicitly recomposed only the adapter, preserving
the application and forwarding root. Core provenance and interface checks
passed, but its signed invocation trapped after 6,924 microseconds with two
outbound requests. Numeric-only diagnostic `42360564252` reproduced the same
fuel count and trap. Its original frames map to `Option::unwrap_failed`,
`golem_wasi_http::Response::read`, `std::io::default_read_to_end`, and the
fixture's `thread_http_sibling`. The original application, not the adapter,
owns those frames. The fault archive has 149 CRC-valid members and SHA-256
`3275806d0fbd9ec225acd7dc29277e39d260acbbdf05c0e0250806860e079a5a`.

The pinned [Golem 0.2.0 response implementation](https://github.com/golemcloud/golem-wasi-http/blob/v0.2.0/src/wasi/response.rs)
uses `self.body.take().unwrap().into_reader().read(buf)` in `Read::read`.
Consequently the second read made by `read_to_end` panics. The fixture now
uses its public consuming `Response::bytes()` API instead. That implementation
retains the original incoming stream in `Body::buffer` through successive
blocking reads and real EOF. No dependency source or host response is patched.
The exact 4,109-byte body and its contents must still be validated before the
two JSON requests begin; the buffer is dropped before those requests. The
two ordinary thread pools, four-request success condition, independent grants,
5,000 ms deadline, 16 MiB memory limit and peer gates remain unchanged.

The corrected fixture and adapter were compiled together from `27164664` by
compiler job `128380436039` in run `42364782237`. That job completed source
capture, isolated application compilation, composition and interface checks;
its ancillary source-check job failed on an invalid validator command, so that
whole workflow remains failed. Signed observation `42366341977` passed the old
panic and reached a third request, but timed out before the fourth. A bounded
numeric host trace (`42367791040`) observed the third response's body and EOF
within about 27 ms. These are failed observations, not signed qualification.

The subsequent completed-EOF retirement change below was independently built
from commit `1d81c35ca6b206bafba113b6214de09bc6781bdb` in successful compiler
run `42369110799`. The selected `combined-corrected-v1` graph and its original
source/build lineage are described in the [diagnostic guide](rust-combined-http-diagnostic.md).
Old compiler bytes and failed signed results remain intact; successful source
compilation and unit controls cannot substitute for a passing signed witness.


## Completed exchange ownership

Completed HTTP exchanges were retaining Task owners until root drain. In a
held-header programme, this unnecessarily retains capacity needed by a later
sequential request even though the previous body has reached EOF.

The Rust-specific retirement frame owns the original canonical future, upload,
body, buffers, activation owner and quota slot in physical-drop order. Observed
EOF is necessary but insufficient: synchronous retirement also requires no
pending future and no upload. Resources and buffered data are destroyed before
the original Task is settled. All other cases remain on the explicit async-root
retirement queue, without early refund, replacement owner, dial retry or replay.
An unwinding resource destructor still retains the owner while the remaining
buffers are destroyed. The .NET implementation is unchanged.

Maintained native controls exercise completed EOF, repeated admission under
finite capacity, retained pending work and destructor unwind. The compiled guest
control separately completes two sequential siblings while the original import
stays held, checks synchronous readiness and deferred cancellation, and requires
empty engine state under ordinary and native-enabled configurations. Neither
control is an authenticated signed-node qualification.
