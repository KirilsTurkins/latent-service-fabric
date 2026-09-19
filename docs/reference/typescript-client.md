# Bounded Node.js client

`@latent/sdk/node` implements the shared
[client profile](../../sdk/profile/README.md) on Node.js 24.19.x. The package root
remains transport-neutral. This is a client for the shipped private node
transport, not remote node discovery, public RPC, a browser management API,
cluster routing or provider access from the host application.

## Authority and channel lifetime

Construct `RpcClient` with an exact `http://127.x.x.x:PORT` or
`http://[::1]:PORT`, an explicit tenant and a 32–256-byte ASCII client bearer
credential. Noncanonical addresses, DNS names, non-loopback IPs, URL userinfo,
paths, query strings, fragments and proxy configuration are unsupported.
The actual connected numeric peer and port must match. There is no hidden
environment, cookie, browser-storage or provider-secret lookup.

The client copies the caller's credential into its own buffer, excludes it
from ordinary inspection and marks the Authorization header as HPACK-sensitive.
Shutdown zeros that owned buffer. JavaScript strings and HTTP/2 implementation
copies cannot be reliably zeroized; this is not a process-memory secrecy claim.
Keep client/server errors and payloads out of logs unless explicitly redacted.

One lazy HTTP/2 session owns at most one TCP socket. There is one initial
connection attempt, no transparent reconnect, channel per call, automatic
pagination or replay. A failed initialization or later connection failure
requires an explicit new client. That decision does not authorize resending an
uncertain invocation or mutation. The caller owns its Node event loop; the SDK
does not create a thread or process per client, deployment or request.

## Finite bounds

| Limit | Default | Hard maximum |
| --- | ---: | ---: |
| Concurrent admitted calls | 8 | 32 |
| Encoded request | 256 KiB | 4 MiB |
| Encoded response | 256 KiB | 4 MiB |
| Aggregate message reservations | 16 MiB | 64 MiB |
| Connect ceiling | 3 seconds | 5 minutes |
| RPC ceiling | 10 seconds | 5 minutes |

Admission is immediate: there is no SDK wait queue. Each call reserves
`2 * (maximumRequestBytes + maximumResponseBytes) + 65536` bytes before encoding
or I/O. Reservations cover bounded message staging, not exact JavaScript heap
or process RSS. They remain owned until the physical stream closes, even after
the caller's promise settles. Reply payloads copy only their exact bytes and
do not retain the full reserved receive buffer.

HTTP/2 additionally has finite header, frame, stream and connection windows:
16 KiB/32-pair response headers, 4 KiB dynamic header table, 16 KiB frames,
32 KiB stream receive window and 128 KiB connection receive window. Push and
reserved remote streams are disabled. The Node session's 4 MiB credit limit
is an implementation accounting limit, not a hard process-memory sandbox.

Only one uncompressed unary gRPC message is accepted. Unsupported compression,
duplicate header/status values, inconsistent lengths, extra frames, oversized
messages and malformed Protobuf fail closed. Before allocating decoded objects,
the codec enforces depth 12, 256 messages, 2048 fields, 128 entries per repeated
field and 32 string-map entries with 128-byte keys/1024-byte values. Duplicate
known singular/oneof fields, duplicate map keys and proto2 groups are rejected
in this closed proto3 profile. Bounded unknown ordinary fields are skipped;
unknown enum integers and opaque string values remain distinguishable. Input
objects must be plain data without accessors, unknown fields or sparse lists.

These aggregate bounds can reject an otherwise schema-valid oversized object.
They are supported-profile restrictions, not server authorization. Selected
management pages require an explicit size 1–64 and an opaque next token of at
most 2048 bytes. The client never follows the token automatically.

## Deadlines, cancellation and physical shutdown

Each call captures one monotonic deadline before encoding. It covers connect,
HTTP/2 readiness, send, receive and decoding; a separate finite connect cap can
only shorten it. `CallOptions.timeoutMillis` is a checked `bigint` of at most
300000. An optional invocation Unix-millisecond deadline further shortens the
same budget; absent and present-zero remain different. Full-width wire
deadlines are compared as `bigint` before converting a bounded local duration.

`AbortSignal` aborts the local stream/wait. It does **not** send the application
`Cancel` RPC, prove the node never admitted the guest, or prove guest cleanup.
After dispatch, a timeout, disconnect or local abort remains uncertain. Retain
the original activation ID and use a fresh live signal/deadline for explicit
`getActivation` or `cancel`. No ID is invented when the caller omits one; a lost
server-assigned response may therefore be unrecoverable by this client.

`shutdown(timeoutMillis)` closes admission, cancels transport work across all
outstanding calls and waits for actual call/session/socket retirement.
Concurrent shutdown callers share one pending promise. Success requires all
physical counters to reach zero; a shutdown timeout is not clean completion.
`usage()` exposes those finite counters. The Node event loop must remain alive
to observe close events. Local client shutdown makes no guest-cleanup claim.

## Typed results and recovery

The generated wire descriptors live under `src/node/protocol`, separate from
the generated cross-language DTO facade and the handwritten owner/convenience
modules. The supported RPCs are `Invoke`, `Cancel`, `GetActivation`, `GetPolicy`,
`ListPolicies`, `ListCapabilities`, `ApplyPolicy` and `GetPolicyOperation`.
Control/management operations reuse the node's real authorization and protocol;
there is no ad hoc JSON endpoint or authority derived from lineage claims.

Invocation success, declared application error and platform failure are distinct
response alternatives. `RpcError.failure` separately describes local admission,
cancellation, deadline, transport, gRPC or decode failure, with bounded recovery
identity and explicit outcome knowledge. Canonical platform details must match
the gRPC code. Standard string/inspection output does not print server-provided
diagnostics, payloads or the credential. Failure facts remain available for
explicit caller handling. Unknown cancellation classifications fail safely with
their raw numeric value; they are not changed into a known disposition.

Optional IDs and zero values retain presence. Request buffers are snapshotted
before dispatch; returned payload bytes belong to the caller. `uint64` always
uses `bigint`, including `18446744073709551615n`. Audit absence, disabled status,
durable acknowledgement and uncertainty stay distinct. A bounded unknown audit
status remains opaque; it cannot be promoted to a known acknowledgement and
does not erase an independently observed operation receipt.

`ApplyPolicy` requires an explicit operation ID and generation precondition
(`0n` means create). Receipts must agree with the requested identity, tenant,
record and observed policy. Save the exact original request before sending.
On uncertain response, use the same operation ID with `getPolicyOperation`;
an absent retained receipt is **unknown**, not proof of nonexecution. Explicit
exact replay is a caller decision using the unchanged original precondition and
document, never an automatic recovery action. Server `retryable` hints do not
cause a retry. Explicit cancellation similarly preserves accepted,
already-terminal and not-found as distinct outcomes.

## Validation status

The transport tests use a controlled, separate real TCP/HTTP2 peer with generated
Protobuf messages. They cover full-width values, typed outcomes, caller ownership,
aborted wait versus explicit cancellation/status, ambiguous mutations and exact
manual replay, malformed/oversized replies, bounded pages, shared physical
shutdown, failed-connection non-replacement and rejected local authority.

This is wire/lifecycle evidence, **not** a real `latentd` provider qualification,
an installed bundle test or proof of the Angular/browser workflow. Those separate
Phase 3 #230 acceptance items remain explicitly pending. The
[package README](../../sdk/typescript-client/README.md) records commands and the
Node-versus-browser boundary. The SDK does not duplicate an Angular renderer or
install a generic privileged browser proxy.
