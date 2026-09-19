# Bounded Rust RPC client

`latent-sdk` implements `LatentClient` with `network::RpcClient`, using the
authoritative generated Protobuf messages and gRPC methods. The default
`transport` feature enables it; `--no-default-features` retains the
transport-neutral invocation models. This client does not depend on CLI
internals, grant provider access or embed a node.

## Explicit connection and ownership

`ClientConfig` requires a numeric loopback socket address, tenant and bearer
credential. There is no ambient endpoint, DNS, proxy, token discovery or
insecure remote fallback. This is the shipped node's local management profile,
not a public-Internet TLS client. Remote access needs an independently secured,
operator-controlled local tunnel; the SDK does not create or authenticate one.
Tenant and lineage fields remain claims subject to server authorization.

Construction performs no I/O. Clones share one lazy HTTP/2 channel, at most one
socket and a bounded executor. Initial connection is attempted once. A failed
initial connection, cancelled initialization or later connection loss never
causes an automatic reconnect/retry; deliberately create a new client when
appropriate, retaining all uncertain operation identities. A new client is not
permission to replay an uncertain mutation.

| Limit | Default | Configurable hard ceiling |
| --- | --- | --- |
| Simultaneously admitted calls | 8 | 32 |
| Encoded request / decoded protobuf frame | 256 KiB each | 4 MiB each |
| Aggregate message-buffer reservations | 16 MiB | 64 MiB |
| Connect ceiling | 3 seconds | 5 minutes |
| RPC ceiling | 10 seconds | 5 minutes |
| Connections | 1 | 1 |
| Owned executor tasks | `2 * maximum_calls + 4` | 68 |
| HTTP/2 stream / connection windows | 32 / 128 KiB | fixed |
| HTTP/2 header list / table | 16 / 4 KiB | fixed |
| Policy/capability page | explicit 1..64 | 64 |
| Page token | 2 KiB | fixed |
| Typed gRPC error details | 8 KiB | fixed |

Admission reserves a call slot and
`2 * (encoded_request_bytes + maximum_response_bytes) + 32768` message-buffer
bytes before encoding or transport submission. Capacity failure is immediate,
not an unbounded waiter queue. A reservation follows the actual outgoing and
incoming bodies: dropping the caller cannot refund a retained body. Decoded
Protobuf collection allocations, runtime/allocator overhead and OS socket
bookkeeping are not an exact RSS interpretation of that buffer counter. They
are constrained by finite message/frame/concurrency limits. Returned values
belong to the caller and are outside SDK retention accounting.

`usage()` reports call, buffer, task and socket ownership. `shutdown(deadline)`
closes admission across every clone, interrupts local waits, drops the channel
and waits until all its actual body/task/socket owners retire. Timeout is a
failure, not a clean-shutdown receipt. Dropping the last client requests local
shutdown but does not await its physical completion.

## Deadlines and cancellation

The `_until` methods accept one absolute Tokio `Instant`. The client clamps it
to its configured RPC ceiling; connection initialization, channel readiness,
request/response transport and decoding share that original deadline. Connect
has an additional, shorter ceiling. An invocation's optional Unix deadline
further restricts the call; present zero is expired, not absent. No stage
renews the original deadline. Generated `grpc-timeout` reflects only the
remaining time.

Dropping/aborting an invocation future cancels its local transport wait. It
does **not** send the application `Cancel` RPC or prove guest/provider cleanup.
Choose and retain a caller activation ID before invoking; query
`get_activation_until` after losing the response, and use `cancel_until`
explicitly when desired. Cancellation `Accepted` confirms admission of the
request, not completion of guest cleanup. Retained status can expire;
`NotFound` never proves that execution did not happen. No implicit polling,
identity generation or resubmission occurs.

## Typed management and recovery

The separate `network::management` module exports the generated common
profile: `GetPolicy`, `ListPolicies`, `ListCapabilities`, `ApplyPolicy`, and
`GetPolicyOperation`. List calls require a finite explicit page. The caller
decides whether and when to request another page. Binding inspection remains
redacted server-produced metadata; requesting node usage does not grant an
operator role.

`ApplyPolicy` requires an operation ID and a present expected generation;
present zero means conditional create, not an omitted precondition. Record
and receipt identity, tenant, kind, generation, digest and revocation must
agree. Recovery uses the original operation ID. A missing retained receipt is
unknown, not evidence of non-execution. The SDK never changes a failed
precondition, generates a fresh operation ID or automatically replays a
mutation. Any deliberate exact replay is a separate caller decision using
the original request and identity.

`RpcResponse<T>` preserves an optional audit acknowledgement independently
of the application response. `RpcFailure` separates local capacity/configuration
failures, connection/deadline failures, rejections and invalid replies. It
retains known activation/operation IDs, dispatch uncertainty, the raw gRPC
code, bounded typed platform details and audit metadata. An audit
`outcome-unknown` or `audit-unavailable` cannot become a known mutation result.
Malformed post-dispatch replies remain uncertain, including mismatched IDs or
page metadata. Known audit data survives later semantic validation failures.

Successful invocation results distinguish application success, declared guest
errors and platform outcomes. Unknown wire classifications fail explicitly
and retain their bounded raw value in `unsupported`; they are not coerced to
an existing terminal state, retry recommendation or authority. Management
Protobuf enum numbers remain raw generated integers. Optional presence and
full-width `u64` fields are not routed through floating point or endpoint JSON.

The legacy `LatentClient` trait returns only its pre-existing minimal
`ClientTransportError`; that compatibility path intentionally cannot expose
all recovery/audit fields and never recommends automatic retry. Use the rich
`_until` API for recovery-sensitive applications. Default error formatting
omits untrusted server text and credentials; inspect typed fields deliberately
rather than logging entire application replies.

## Validation and example

Run `cargo test -p latent-sdk --all-targets --locked` and
`cargo clippy -p latent-sdk --all-targets --locked --no-deps -- -D warnings`.
The real TCP/gRPC controlled-peer tests cover channel reuse, all outcome kinds,
known-ID cancellation/status after response loss, tenant rejection, absolute
deadlines, capacity, exact explicit mutation replay, full-width audit values,
bounded pages/messages, no reconnect and actual transport shutdown. Unit
tests additionally check protected configuration, ambiguous audit metadata,
canonical typed failures and physical reservation retention. The peer is
**not** an LSF node or a provider-backed guest; those tests alone do not satisfy
the real-node acceptance criterion of #228.

The [provider client example](../../sdk/rust/README.md) invokes the maintained
HTTP/blob guest contracts and reads only a protected node-client credential.
Its standalone provider-backed qualification depends on the node wiring and
workflow delivered with #226. Until that complete real-node workflow is run
and recorded, #228 remains open. A compiled example is not runtime evidence.
