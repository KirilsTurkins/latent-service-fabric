# Bounded Go node client

This native client implements the eight-operation [shared SDK profile](../profile/README.md).
It is not a Go guest runtime, a browser client, a provider credential API, or an
installed-bundle/production qualification. The existing `latent.Client` facade
remains available through `transport.NewLegacy` or `client.Legacy()`; the full
`profile.ClientProfile` surface is implemented by `*transport.Client`.

| Package | Responsibility |
| --- | --- |
| `latent.dev/sdk/go` | Existing three-operation public invocation facade |
| `latent.dev/sdk/go/profile` | Shared, generated public DTOs and eight-operation interface; owned by #227 |
| `latent.dev/sdk/go/transport` | Explicit connection ownership, admission, unary wire transport and conversions |
| `internal/rpc` | Private generated Protobuf/gRPC bindings; reproducible, ignored build output |
| `cmd/provider-workflow` | Executable native HTTP/blob guest example and separate-node qualification participant |

## Build and focused validation

The qualified development toolchain is Linux x86-64 with Go **1.23.2**, Buf
**1.72.0**, and Python 3.10 or newer. The repository's development image supplies
these tools. Other OS/architecture combinations are not qualified by this
delivery; the native participant deliberately requires Linux file permissions.

From the repository root:

```sh
python3 sdk/go/generate.py
python3 sdk/go/generate.py --check
cd sdk/go
go test -timeout 30s ./...
go test -race -timeout 60s ./transport \
  -run 'TestCancellationQueueAndReservedRecovery|TestConcurrentCloseReapsPendingAndQueuedCalls|TestFailedStartupAndAdoptedConnectionOwnership'
go vet ./...
go build -trimpath -o target/provider-workflow ./cmd/provider-workflow
```

Generation uses only the authoritative common, policy, capability and invocation
Protobuf sources. It installs local `protoc-gen-go v1.36.6` and
`protoc-gen-go-grpc v1.5.1` under this SDK's ignored `target/tools`, verifies both
versions, and compares byte-for-byte with a fresh staged generation in `--check`
mode. `GOTOOLCHAIN=local` prevents silent compiler upgrades. First use requires
access to the pinned Go modules; dependencies and checksums are in `go.mod` and
`go.sum`. No generated RPC files or globally installed plugins are committed.
The repository's `tools/validate_sdks.sh` runs generation, checking, the Go suite
and the focused race checks. A plain Go build before generation is not the
clean-checkout build procedure.

## Endpoint, authority and lifecycle

`transport.DefaultConfig(endpoint, bearerToken)` supplies finite bounds; `New`
requires an explicit config and a non-nil context. Endpoints must be canonical
`http://127.0.0.1:PORT` or `http://[::1]:PORT`-style numeric loopback addresses
with an explicit nonzero port and no user information, path, query or fragment.
DNS names, HTTPS/mTLS and remote endpoints are rejected. The client does not
consult ambient proxy settings, cookies, gRPC metadata or environment credentials.
There is no redirect, resolver, cluster-balancing or TLS fallback.

The constructor dials one TCP socket and verifies its HTTP/2 handshake under
the earlier of the caller's deadline and `ConnectTimeout`. The constructor's
context owns startup only; after success the caller owns the client until
`Close`. A failed startup closes its socket. `AdoptConnection` instead accepts
an already connected `*net.TCPConn` to the exact configured loopback endpoint:
ownership transfers on entry, **including failure**, and the caller must stop
using or closing that connection. Borrowed/shared gRPC connections are not a
supported ownership mode.

The owner has one reusable HTTP/2 connection, bounded call admission, and a
single lifetime watcher. It never creates replacement connections. A private
connection pool permits exactly one reservation attempt per RPC, including
`REFUSED_STREAM` and GOAWAY failure paths. Neither invocation nor mutation is
automatically retried. `Close` is concurrent-safe and idempotent: it stops
admission, wakes queued calls, cancels local waits, closes the actual socket and
waits for call and socket-I/O owners. It sends no implicit `Cancel` RPC.

`Snapshot().Reaped` reports closed transport, retired call/queue/socket owners
and the retired watcher. It is not proof of remote guest/provider retirement,
zero process RSS or zero global Go runtime goroutines. The pinned HTTP/2 library
can retain a fixed unused-connection cleanup timer for up to five seconds;
its closed-state pending-reset counter can also remain nonzero without a live
stream/socket owner. Live reset/concurrency slots still count against admission
until the transport retires them. Neither case acquires deployment-specific
workers or additional sockets.

The explicit bearer is sent only on this connection. Config/client formatting
and local errors are redacted; the client's own bearer is redacted from typed
remote diagnostic messages and field values. HTTP/2 verbose logging is rejected
at construction. Opaque application payloads remain opaque, not a general
secret-scrubbing service. Caller-supplied lineage and metadata are transmitted
as claims, never interpreted as principals or authority. Redacted capability
inspection is diagnostic data, not permission to access a provider.

## Finite resource and time profile

| Limit | Default | Configurable ceiling |
| --- | --- | --- |
| Startup time | 2 seconds | 30 seconds |
| Local RPC time | 5 seconds | 30 seconds, additionally bounded by caller context |
| In-flight calls | 8 | 32 |
| Recovery reservations | 2 | At least 1 and less than in-flight capacity |
| Queued calls | 8 | 64; zero disables waiting |
| Encoded request/response | 1 MiB each | 4 MiB each |
| HTTP/2 header list | 16 KiB | 32 KiB |
| Conversion/decoding graph budget | 8 MiB / 8,192 nodes | 32 MiB / 16,384 nodes |
| Nested Protobuf depth | 16 | Fixed |
| HTTP/2 frame / HPACK tables | 16 KiB / 4 KiB each | Fixed |

Graph budgets are conservative conversion/accounting limits, not a process-RSS
claim. Encoded buffers, caller-owned inputs, generated messages and the pinned
HTTP/2 library's finite stream/connection flow-control buffers are additional
bounded owners. Compression and streaming RPCs are unsupported. The decoder
checks frame length before allocation, rejects extra unary frames and malformed
or contradictory oneofs, and bounds graph work before unmarshalling.

Policy requests/responses have additional 128 KiB/1 MiB bounds. Capability
inspection uses 8 KiB/128 KiB. Policy pages explicitly request 1–32 entries and
have at most a 117-byte opaque cursor. Capability pages are at most 128 entries
(absent/zero means that default) and use at most a 160-byte opaque cursor. The
client never walks subsequent pages automatically.

Effective admission also respects the peer's advertised stream limit, retaining
the configured recovery capacity for `Cancel`, `GetActivation` and
`GetPolicyOperation`. Startup rejects a peer that cannot supply that capacity
plus a normal call. A peer that later reduces capacity or stops responding can
still make a call fail within its original deadline; reservations are not a
remote availability guarantee.

One absolute local deadline covers queueing, conversion, wire-slot reservation,
sending, reading, decoding and local completion. The remaining `grpc-timeout`
is refreshed at the one wire reservation, never restarted. Optional local
`CallOptions.TimeoutMillis = 0` expires without dispatch; unrepresentable full
width values and values above the finite ceiling are rejected without wrapping.
`InvokeRequest.DeadlineUnixMillis` remains a separate absolute node deadline;
`ResourceBudget.WallTimeLimitMillis` remains a separate relative guest budget.
Both retain native full-width `uint64` values in the model and wire conversion.
In particular, the maintained real-node guest fixture caps both its wall budget
and incoming `grpc-timeout` at **5,000 ms**: use the example's **3,000 ms** calls,
not a generic longer transport ceiling. Its held absolute-deadline case is
**500 ms**.

## Outcomes, bytes and explicit recovery

All eight calls use generated RPC methods: `Invoke`, `Cancel`, `GetActivation`,
`GetPolicy`, `ListPolicies`, `ListCapabilities`, `ApplyPolicy` and
`GetPolicyOperation`. No handwritten JSON-to-RPC proxy or CLI invocation is used.
Public DTOs are converted directly through authoritative descriptors; opaque
bytes are copied, not converted through floating-point JSON. Keep the complete
input graph unchanged until a call returns, including while queued. Returned
byte slices and maps do not alias a reusable receive buffer or another response.

Nil, present-empty optional identity and present-zero numeric values remain
distinct. The server validates invocation lineage/identity claims. A successful
RPC still distinguishes success, declared application error and platform
failure, with publication identity and final consumption. The legacy facade
preserves those three outcomes; use the full profile for management and audit
metadata. Future management enum values and signed raw gRPC status values stay
lossless. Unsupported invocation phase/terminal/error values fail with bounded
raw evidence, not invented success.

Choose an activation ID before sending. Local `context.Context` cancellation
only aborts the local wait; `errors.Is(err, context.Canceled)` and
`errors.Is(err, context.DeadlineExceeded)` work through `profile.ClientFailure`.
Use `errors.As` for dispatch state, raw status, identity and uncertainty. After
cancellation, use a fresh live context for explicit `Cancel`/`GetActivation`
with the original ID. Accepted, already-terminal and not-found cancellation
remain distinct. Not-found is not proof of nonexecution. If the connection
itself failed, explicitly construct a new client for lookup; do not resend
the invocation implicitly.

Mutations require a caller-known operation ID and an explicit expected
generation, including zero for creation. Recover a lost mutation response using
`GetPolicyOperation` with that same ID, then perform an exact replay only as a
separate caller decision. Changed documents and stale generations are not
silently repaired. Audit facts remain independent of mutation receipts: current
policy RPCs provide **no audit metadata**, so all three audit fields stay absent.
Known future responses retain acknowledgement, raw status and independent u64
attempt; unknown textual status retains raw status/attempt without fabricating
an `AuditAck`. A durable attempt alone never proves commit.

## Native HTTP/blob example

`cmd/provider-workflow` is the maintained executable example. It accepts exactly
`--config /absolute/input.json`; it never receives a bearer or provider secret
on argv. Input is the parent's shared `latent.sdk.provider.workflow.input.v1`
contract: protected client credential file (0600), private directories (0700),
numeric node endpoint, tenant, exact signed `http`/`blob`/`callee` targets,
controlled upstream URL and one empty-rule policy document. The participant
rejects unknown/duplicate JSON fields, oversized input and policy authority.
It does not create providers, sign packages, start a second CLI fixture, or
invent a generic provider proxy.

Build the binary as above. On an integration checkout containing the centrally
owned shared runner and the fresh three-guest #226 fixture, run:

```sh
python3 tools/run_sdk_provider_workflow.py \
  --cli /absolute/latent --node /absolute/latentd \
  --fixture-root /absolute/fresh-signed-inputs --language go \
  -- /absolute/latent-fabric/sdk/go/target/provider-workflow
```

The runner and provider setup belong to the shared SDK qualification work, not
this client; follow its `docs/testing/sdk-provider-workflow.md` when integrated.
The Go PR can run controlled-peer tests independently before that stack merges.
The example invokes the authorized HTTP/blob guest with
`application/vnd.latent.wit-values.v1+json` payloads `[0, URL, "0"]` and
`[0, "", "0"]`, checking `["2201"]` and `["4"]` without losing u64 precision.
Only the guest and node access HTTP/blob providers; the Go process has no
provider credential or direct HTTP/blob client.

The complete example exercises all eight SDK operations and the runner's 18
assertions, with four distinct held-upstream cases for local cancellation,
explicit cancellation, the original deadline and shutdown. Started/closed
markers are test rendezvous only: closure is accepted only after the runner's
actual provider-socket EOF/reset marker and retained terminal status. Output is
one bounded, redacted result line, no stderr, original `go-` admitted IDs,
`go-policy-create`, and `auditAttempt: null` after asserting all three current
node audit fields absent. Controlled peers separately verify real/future audit
headers and full-width values; the native example never fabricates one.

See [Go qualification evidence](../../docs/testing/go-client-qualification.md)
for measured checks and remaining integration gaps. The root SDK support matrix
is centrally coordinated: shipping a Go transport does not ship Go guest
bindings or qualify every platform.
