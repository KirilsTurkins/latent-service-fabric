# Guest SDK: build and run a capsule

For a new independent project, follow [Create your own Rust capsule](rust-authoring.md)
or [Create your own C capsule](c-authoring.md). The bounded
[Java authoring profile](java-authoring.md) uses maintained TeaVM and typed WIT
bindings; its [SDK reference](../../sdk/java-guest/README.md) documents exact
language, heap, clock-grant and ownership boundaries.
That guide covers editable source, generated contracts, packaging, signing,
enforced node admission and cleanup. This reference describes capability ownership.

The maintained guest SDK is [Rust `latent-guest`](../../sdk/rust-guest/README.md).
The [C guest SDK](../../sdk/c-guest/README.md) provides explicit allocation and
async ownership helpers over generated canonical ABI bindings.
External client interfaces in Go, TypeScript, Java, .NET, C and Rust are separate
from guest execution profiles. They do not establish general Go/JVM/.NET/JS guest
support or a Node.js/WASI environment inside an LSF activation.

## Exact toolchain and host surface

Use the pins in [tools/toolchain.toml](../../tools/toolchain.toml): Rust 1.97.1,
`wit-bindgen` 0.62.0, `wasm-tools` 1.254.0, Python 3.13.5 and Zig 0.16.0 for C.
Rust guests target `wasm32-unknown-unknown`. The C reactor uses Zig's libc and
64 KiB stack without importing WASI. Node and compiler use Wasmtime 47.0.4.
The generated aggregate is `latent:platform/capsule@0.4.0` (host profile V4).
Each example imports only the capability it needs; the service callee has none.

| SDK module | Exact WIT interface | Ownership and failure contract |
| --- | --- | --- |
| `http` | `latent:http/client@0.2.0` | One bounded buffered call; owned response, exact typed error, no retry. |
| `streaming` | `latent:http/streaming@0.3.0` | Owned upload/body/chunk resources. Drop aborts I/O or releases the chunk; finish/abort consumes the owner. |
| `blob` | `latent:blob/blob@0.2.0` | Private writer/reader handles with async close/seal; owned chunks materialize once. |
| `secrets` | `latent:secrets/reader@0.1.0` | One zeroizing byte owner, borrowed access, exact read error. Copies made by applications have their own lifetime. |
| `events` | `latent:events/publisher@0.2.0` | Exact broker receipt or typed error, including uncertainty. No durable outbox, consumer-processing promise or retry. |
| `service` | `latent:service/invoke@0.1.0` | Exact returned, declared-domain and platform outcomes with host-controlled descendant budgets. |
| `random` | `latent:random/random@0.1.0` | Exact bounded entropy operations and errors. |
| `metrics` | `latent:telemetry/custom@0.1.0` | Bounded configured instruments and labels; no implicit series or exporter. |

Context, log and monotonic/wall clock bindings also re-export their authoritative
interfaces. The obsolete blob 0.1 interface is not an SDK wrapper. Import
recognition is separate from provider installation and per-activation authority.
There is no grant constructor, global provider, hidden worker or automatic retry.

Blob writer/reader handles are primitive WIT values, so Rust `Drop` cannot call
their asynchronous close. Use explicit `close` or consume a writer with `seal`.
Abandonment remains charged to the original activation until host cleanup; the
SDK does not report an early refund. HTTP and blob chunks are real Component
Model resources and use generated destructors. A retained chunk keeps its own
charge after its reader/body is closed. `Chunk::bytes(self)` consumes the wrapper.

Cancellation and deadlines remain host-controlled. Stopping a wait cannot prove
an external effect did not happen. Existing synchronous secret WIT has only
not-found, permission-denied, expired and unavailable: cancellation can produce
`Unavailable` before activation interruption wins. The wrapper preserves that
contract and does not invent a success, cancellation disposition or retry.

## Build, inspect, sign, admit and execute

On the maintained Linux conformance environment, install the pinned tools and
run from the repository root:

```sh
python3 tools/build_guest_capsules.py --output "$PWD/target/guest-capsules"
LSF_GUEST_CAPSULES="$PWD/target/guest-capsules" \
  cargo test -p latent-wasmtime --test guest_sdk --locked -- \
    --ignored --nocapture --test-threads=1
```

The driver builds nine maintained Rust examples under
[tools/toolchain-smoke/examples](../../tools/toolchain-smoke/examples): buffered
HTTP, streaming HTTP, blob, secrets, events, random, metrics, service caller and
callee. It also compiles equivalent C capability peers. Each output directory contains the
actual component, exact capsule/contract metadata, locked WIT,
`package-source.json` and `build-observation.json`. The manifest enables only the
selected import and needed resource dimensions. It requests no durable effects,
threading, snapshots or fusion. Outputs remain temporary, not source artifacts.

The [admission helper](../../crates/latent-wasmtime/tests/guest_sdk/package.rs)
checks the completed build marker and source inventory, then uses the production
capsule packager with an embedded bounded inventory. Ephemeral test publisher and
builder keys sign the exact package and observed component. Production verifiers
check both signatures and current policy before `open_enforced` catalog admission.
The inventory describes these package inputs; it does not assert a complete
transitive dependency inventory. The helper contains no fixed private keys,
trusted-local admission switch or injectable eligibility proof.

The two separately approved [guest build profiles](../reference/build-provenance.md#phase-3-guest-recipes)
identify explicit worktree inputs. Their revision is a source-inventory hash,
not a Git commit claim. Existing echo builder approvals do not authorize them.
For an application, inspect its package and configure real publisher/builder
policy, revocations and tenant admission through the
[package workflow](packaging.md). Test keys and fixture policies grant nothing
to a running deployment. Arbitrary build recipes need their own reviewed profile.

## Least-privilege deployments and executable checks

The integration compositions below contain the actual checked deployment,
policy and provider-binding documents. They bind the admitted publication and
tenant at setup, instead of copying a stale digest into a runnable example.

| Capability | Exercised deployment/policy configuration | Runtime checks |
| --- | --- | --- |
| Buffered HTTP | [HTTP fixture](../../crates/latent-wasmtime/tests/http/fixture.rs), one local test origin and `/allowed` path | GET/HEAD/POST, owned payload and denied path. |
| Streaming HTTP | [Streaming fixture](../../crates/latent-wasmtime/tests/streaming_http/fixture.rs), bounded local origin | Verified EOF, repeated trailers, body abandonment and chunks surviving body drop. |
| Blobs | [Blob fixture](../../crates/latent-wasmtime/tests/local_blobs/fixture.rs), tenant `tests`, namespace `private` | Rust/C close, abandonment, stale handles, C repeated materialization, queued cancellation and reuse. |
| Secrets | [Secret fixture](../../crates/latent-wasmtime/tests/local_secrets/fixture.rs), explicit logical references | Value ownership, provider-only/foreign references, expiry, cancellation and recovery. |
| Events | [Event fixture](../../crates/latent-wasmtime/tests/nats_events/fixture.rs), exact mapped topic | TLS protocol peer, acknowledged/uncertain results, denial, exactly one publication attempt. |
| Service calls | [Node fixture](../../crates/latent-wasmtime/tests/local_service/fixture.rs), exact caller/callee publications and isolated-local binding | Real node admission, declared errors, target denial, descendant charges and reused cells. |
| Random | [Random fixture](../../crates/latent-wasmtime/tests/random/fixture.rs), explicit entropy capability | Byte/scalar APIs, invalid length and reuse. |
| Metrics | [Metrics fixture](../../crates/latent-wasmtime/tests/metrics/fixture.rs), four configured instruments | Each metric kind and typed invalid-name failure. |

Most tests use the actual Wasmtime backend and broker/provider owners directly;
the service pair also traverses the activation manager and deployment store.
The event peer is a bounded TLS JetStream protocol fixture, not a live broker
benchmark. Provider-specific suites retain their separate conformance coverage.
These small tests make no performance or hostile-production qualification claim.

## Generated-source drift and CI

`tools/build_guest_capsules.py` regenerates the exact aggregate Rust and C
bindings and compares their hashes with
[tools/guest_bindings.lock.json](../../tools/guest_bindings.lock.json).
An intentional WIT/generator change requires review and an explicit
`--update-bindings` run. The examples map imports to the same generated Rust
types and C builds against the generated headers.

The full-profile Repository contracts CI job installs the SHA-verified binding
generator, compiles all examples and runs the signed guest suite. Docs-only CI
selection remains unchanged. No generated source dump, private key or large
benchmark report is committed or uploaded by this guest gate. `--skip-c` is a
local Rust iteration option; it is not the complete conformance gate.
