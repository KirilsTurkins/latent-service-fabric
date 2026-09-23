# Go capsule SDK

Start with [Create your own Go capsule](../../docs/component-development/go-authoring.md).
It creates an editable project outside LSF, derives typed contracts from WIT,
captures the actual compiler inputs, signs the resulting package, admits it to
a node and explicitly cleans up. External Go clients under `sdk/go` are a
different product: they call a node and do not compile Go guests.

This profile uses the pinned Go 1.27.1 `wasiOnIdle` compiler and
componentize-go 0.4.3 commit recorded in [toolchain.lock.json](toolchain.lock.json).
Do not substitute stock Go or TinyGo. No ambient WASI imports survive the
closed runtime adapter. Runtime clocks and entropy are explicit LSF imports,
requiring installed providers, policy bindings and per-deployment grants.
The first node call without those grants must fail closed.

## Typed contracts

Edit `src/main.go`, `wit/world.wit` and `capsule-project.json` in the created
project. Export package names follow the selected WIT identity. Additional Go
source files in `src` must belong to generated export packages; unsupported
files, contracts and dependencies fail before signing. Generation runs twice
and compares exact output. The SDK and its reviewed Go dependency are vendored,
version-locked and hashed; application sources are captured before compilation
and checked again afterward.

The project includes the actual `go.mod` and `go.sum` used to assemble the
generated `wit_component` module. They pin `go.bytecodealliance.org/pkg v0.2.3`;
application dependency additions and `replace` directives are rejected. Run
the capsule builder, not a standalone `go build` of the ungenerated source.

WIT `u64` and `s64` are Go `uint64` and `int64`, not floating-point numbers.
Strings preserve UTF-8, including embedded NUL. Lists and records retain their
generated element and field types. `wit.Result[T,E]` distinguishes application
errors from infrastructure failures, and `wit.Option[T]` preserves absence.
Unsupported contract shapes are rejected by the authoritative contract
deriver; generated bindings do not independently grant host authority.

Use the generated `wit_component/lsf/<module>` packages for capabilities:

| Module | Calls and owners |
| --- | --- |
| `http` | `Send` returns the exact buffered response or typed HTTP error. |
| `streaming` | `Start`, upload `Write`/`Finish`/`Abort`, body `Read`/`Trailers`/`Abort`, and independently owned chunks. |
| `blob` | `Create`/`Open` return owned writers/readers; `Write`/`Read` borrow, `Seal` and `Close` consume. |
| `secrets` | `Read` returns one explicit byte owner; `WithBytes` borrows and `Close` clears the owned bytes. |
| `events` | `Publish` retains acknowledged, rejected and uncertain outcomes without replay. |
| `service` | `Call` preserves returned, declared-error and platform-error outcomes and host descendant budgets. |
| `random` | `Bytes` and `U64` call the granted entropy provider once. |
| `metrics` | `EmitMetric` uses only host-configured instruments and labels. |

Complete typed fixtures are in [examples](examples). They include HTTP denial,
EOF and trailers, reader/body closure with a surviving chunk, stale raw-handle
negative tests, secret zeroization, uncertain events, local service errors and
typed invalid random/metric arguments. They are compiled application code,
not a substitute implementation of those providers.

## Ownership, concurrency and cancellation

The supported profile is Linux x86-64 compilation to single-threaded Wasm with
the exact patched Go compiler, ordinary Go source and the reviewed dependency
graph. The examples exercise typed functions, generics, strings, slices,
channels, goroutines, garbage collection and `runtime.KeepAlive`. Pure
computation uses the Go standard library available for this target. `time` and
runtime entropy cross the explicit LSF clock/random bridges; they gain no
authority from a standard-library import. Filesystem access, sockets, process
creation, dynamic libraries, CGo and arbitrary third-party module graphs are
outside this profile. Unsupported ambient WASI operations fail closed; use the
typed LSF capabilities for host effects. This is not unrestricted native Go.
In particular, `time.Sleep` and timer-backed standard-library polling are not
component waits: the closed adapter rejects `poll_oneoff`. Use the generated
asynchronous capability calls; do not introduce a busy-wait workaround.

Owners contain private, shared state. Copying a wrapper does not create a
second host resource. A pending operation borrows its owner; closing, consuming
or borrowing it again while pending is rejected. Releasing a stale borrow
cannot release a later one. Consuming operations invalidate every alias on
success or failure; they do not retry uncertain effects.

Use explicit close operations and `defer` where appropriate. Streaming resource
`Close` drops exactly once. Blob reader/writer `Close` is asynchronous and
consumes the owner; calling it again is misuse. A chunk can be materialized only
once and retains its own host charge after its reader or body closes. Unclosed
owners remain charged until the activation is cleaned up. The SDK adds no
finalizers, goroutines, threads, background drains or retry workers.
The builder removes the pinned generator's `runtime.AddCleanup` blocks from
imported capability resource constructors, rejecting any unreviewed shape.
Explicit generated `Drop` methods stay intact; garbage collection cannot drop
a host owner behind the SDK's back. Abandonment is reclaimed by Store cleanup.

Secret zeroization covers the SDK-owned byte slice, including its aliases.
Copies or strings made by application code are outside that guarantee. A borrow
must not escape its callback or be used after close.

The compiler's async scheduler runs guest goroutines within the activation's
bounded linear memory, fuel and wall-time budget. A goroutine is not a host
thread. It cannot outlive the fresh Store; no heap, event loop or pending guest
task is kept for a dormant deployment. No other Store can inherit its statics.
Cancellation releases host owners through normal activation cleanup, not a
synthetic refund. Stopping a wait does not establish that an external effect
did not happen.

## Evidence and limitations

`BUILD-COMPLETE.json` means compilation and packaging succeeded, not that the
guest ran or that the ticket is qualified. `SDK-BUILD.json` deliberately records
`runtimeQualified: false`. The Linux `guest_sdk` integration gate must then
admit and execute every compiled fixture through actual provider owners:

```sh
python3 tools/build_go_guest_capsules.py --output /tmp/lsf-go-sdk-attempt
LSF_GUEST_CAPSULES=/tmp/lsf-go-sdk-attempt LSF_GUEST_SDK_LANGUAGE=go \
  cargo --config .cargo/managed-guest.toml test --locked -p latent-wasmtime --test guest_sdk -- --ignored --test-threads=1
```

Always use a fresh output directory. Native ownership tests are smaller and do
not replace Wasm execution:

```sh
go test sdk/go-guest/ownership/owner.go sdk/go-guest/ownership/owner_test.go
```

Keep failed attempt receipts and logs.
The [developer qualification record](../../docs/development/go-capsule-qualification.md)
records exact source, compiler decisions, failed attempts and measured runtime
results separately from the beginner workflow.
An uncertain deployment requires read-only operation inspection before any
new action. This workflow does not authorize release publication or replace
the separate human newcomer review.
