# C transport, ownership and bounds

## Transport and authority

The owner uses the native nghttp2 C HTTP/2 library with nanopb C protobuf
descriptors/runtime. It sends unary gRPC frames on one nonblocking TCP socket.
There is no automatic retry, library retry layer, DNS lookup, proxy, redirect,
HTTP/1 fallback, subprocess, background thread or connection per deployment.
Generated paths select exactly the eight common RPCs. A new explicit request
may open a replacement connection after failure; failed calls are never replayed.

Configuration requires `http://` followed by a numeric IPv4 address in 127/8 or
the IPv6 loopback address in brackets, and an explicit canonical port 1..65535.
Names, remote addresses, TLS URLs, userinfo, paths, fragments and queries are
rejected. Bearer tokens and tenant assertions must be nonempty printable ASCII,
at most 256 bytes; whitespace/control bytes are rejected. Authorization is sent
as sensitive/non-indexed HPACK metadata. No configuration or server diagnostics
are logged by the library. The fixed owner credential buffer is wiped on stop
and destruction; HTTP/2-owned copies are freed with the session.

The configured tenant is a client assertion, not an authenticated principal.
Invoke target and mutation metadata must match it; the server authenticates the
bearer and checks actual tenant authority. Caller lineage, budgets, operation
IDs, inspection results and policy documents do not grant execution permission.
The implementation adds neither a remote node listener nor mTLS/cluster routing.

## Public surfaces and lifetimes

`latent_transport_create` returns an owner plus optional structured construction
failure. It copies retained configuration and does not connect. All eight methods
in `latent_transport_profile_vtable()` accept their existing DTO, optional local
call options, completion callback and user data. The same owner implements the
legacy three-method invocation vtable through `latent_transport_legacy_vtable()`.
The legacy interface cannot express the complete profile error/metadata model;
use the profile when recovery, audit or dispatch uncertainty matters.

| Object | Lifetime |
| --- | --- |
| Configuration endpoint/tenant/token | Borrowed through create only; copied on success |
| Request/options, nested strings/bytes/maps | Borrowed through the initiating method only; retained request is encoded/copied before return |
| Callback and user data | Borrowed until completion returns; the SDK does not copy or own the pointed-to user data |
| Profile result/failure and all nested pointers | Borrowed only during the callback; copy what must outlive it |
| Non-NULL `latent_profile_call*` | Local handle retained through completion and until explicit `release_call` after callback return |
| NULL profile handle | Failure callback ran inline; nothing to release |
| Legacy `latent_invocation*` | Opaque correlation handle, valid through its completion callback only; automatically freed afterward |
| Profile/legacy client views | Borrowed from the owner, valid until owner destruction |

Callers provide readable buffers consistent with checked lengths and valid,
non-NULL client/callback pointers. Strings are length-delimited; embedded NUL in
ordinary protobuf strings/maps is preserved and is not a terminator. Every
well-formed API call invokes exactly one completion, with response **or** failure,
including connection/allocation failure. Absent flags govern presence, never
pointer values or zero-length heuristics. No existing public DTO/vtable layout
is modified here; the added transport header is additive. The common C ABI remains
pre-stabilization: rebuild consumers and producers together.

All operations on one owner must run on a single externally serialized caller
thread, including getters, polling and handle release. There are no worker
callbacks or hidden threads. Completion runs during admission, poll, cancel or
stop. A callback may submit another call, cancel a different pending call, or
request stop. Recursive polling is rejected. Destruction during a callback is
rejected, and releasing a still-pending/current callback handle has no effect:
release it after completion returns. Keep owner/user data live until callbacks
finish. The race tests exercise response/cancel/stop ordering on this documented
event loop; they do not assert thread-safe simultaneous API access.

## One deadline and physical shutdown

An absolute monotonic deadline starts before validation/encoding. The owner
default and supplied relative call option select the smaller timeout. Explicit
zero expires inline; an unrepresentable value above 300000 ms fails explicitly
without wrapping. An Invoke wall-clock deadline can only shorten that budget.
Relative activation wall-time budgets remain independent protobuf request fields.
Queueing, connection establishment, stream admission, send, receive, decode and
callback admission all spend the original deadline. gRPC timeout headers contain
the remaining milliseconds, not a renewed per-phase budget.

The caller must poll promptly to make progress and observe expiration; the
library creates no timer thread. `poll(owner, maximum_wait_millis)` accepts
0..1000, bounds its I/O passes and shortens sleep to the nearest call/connect
deadline. A response waiting behind another slow callback is not admitted as a
late success. User callbacks/allocators must themselves finish promptly; a C
library cannot preempt arbitrary caller code or guarantee scheduler latency.

`cancel_local` completes the selected pending call with LocalCancelled. If it
was dispatched, the implementation conservatively **retires the entire HTTP/2
connection**, closing the OS socket and deleting the session before notification.
Other unfinished calls sharing it fail too: dispatched siblings remain Unknown,
and unsent siblings remain NotDispatched. An expired dispatched call or malformed
connection similarly retires its physical transport. An unsent queued cancellation
does not needlessly terminate active work. A separate, explicit Cancel RPC has
normal capacity/deadline rules; no slot or automatic forwarding is invented.

`stop` is idempotent: reject new calls, close the socket, delete the HTTP/2 owner,
wipe the fixed credential buffer and complete pending calls. Already observed
completions may win the response/stop race. `shutdown(timeout_millis)` performs
the same physical stop and synchronously drains callbacks; false means the
caller-supplied time/recursive-callback preconditions were not met, not that a
local waiter proves cleanup. It can report an overrun caused by a slow callback,
but cannot interrupt that callback. Non-NULL profile handles remain owned until
released. `destroy` returns false unless all callbacks and handles are retired
and no poll/notification is active. The void vtable destroy methods obey the
same preconditions and do nothing when they are violated.

None of these operations promises remote activation/provider cleanup. Explicit
Cancel acceptance is advisory, not proof of completion. Recover using the
original activation/operation ID on a live owner. GetActivation/GetPolicyOperation
gRPC NotFound (5), or a missing operation receipt, remains OutcomeUnknown.

## Finite ownership

| Config field | Default | Hard maximum / rule |
| --- | ---: | --- |
| `timeout_millis` | 5000 | 300000, positive |
| `connect_timeout_millis` | 1000 | 300000, positive, shortened by call deadline |
| `maximum_in_flight` | 4 | 32, positive |
| `maximum_queued` | 4 | 128, zero allowed |
| `maximum_retained_calls` | 16 | 256, includes completed unreleased handles |
| `maximum_request_bytes` | 128 KiB | 1 MiB; policy <=128 KiB, capabilities <=8 KiB |
| `maximum_response_bytes` | 1 MiB | 1 MiB; capabilities <=128 KiB |
| `maximum_decoded_bytes` | 2 MiB | 8 MiB per call, including arena block storage |
| `maximum_owned_bytes` | 16 MiB | 128 MiB aggregate, at least the fixed owner size |

Message byte limits exclude the five-byte gRPC prefix; that prefix is separately
charged. Full bounded request and response frame storage is reserved at admission,
including queued calls. Exceeding a body/arena/admission/allocation bound reports
Limit, never a manufactured RPC success. Responses are fully materialized unary
values; no public stream can outlive accounting.

The configured allocator covers the owner, call handles, frame buffers, decoded
arenas and nghttp2 session allocations. It must provide malloc-compatible
alignment and matched non-reentrant allocate/deallocate functions. Tracked
allocations include their alignment/accounting headers and both old/new memory
during bounded growth. `owned_bytes` never exceeds the configured aggregate.
Releasing a completed handle returns its retained reservation; stopping alone
does not refund unreleased handles.

The exercised x86-64 layout is **1032 bytes per owner and 14960 bytes per call**,
before dynamic buffers/accounting headers. nghttp2's public option/callback
constructors use two fixed libc allocations, **152 + 232 bytes**, outside the
custom allocator. They exist only while initializing one session, are freed
before initialization returns, and are explicitly additional to `owned_bytes`.
The `owner-bounds` probe compiles against the pinned internal declarations to
report these values; the production transport uses only public nghttp2 APIs.
These are requested storage sizes, not a claim that malloc metadata, libc caches,
caller stack or process RSS equals the ownership counter.

There is at most one socket/session per owner and zero SDK-created threads.
Each socket requests 64 KiB send and receive buffers; Linux normally doubles
these accounting sizes and owns additional TCP bookkeeping. Fixed decoder scratch
is 2048 bytes per nesting level, bounded to 16 levels; receive scratch is 16 KiB.
The codec caps field visits/repeated growth at 4096, bounds all length arithmetic
and checks deadlines throughout. Unused growth blocks stay charged until callback
completion. HTTP headers are limited to two blocks, 32 fields, 64-byte names and
16 KiB aggregate field bytes. HPACK decoder table is 4 KiB; encoder dynamic table
is disabled; outstanding ACKs/settings are limited to 32 and continuations to 4.
All remaining HTTP/2 dynamic storage shares the aggregate allocator ceiling.

`get_usage` exposes current/peak tracked bytes, HTTP/2 bytes, in-flight, queued,
retained handles, pending callbacks, sockets, sessions and stopped state. Physical
stop must yield zero sockets/sessions/HTTP2 bytes; fully released shutdown also
yields zero call/queue/callback counters. The fixed owner lives until destruction.

## Preserved profile semantics

- Native `uint64_t` retains 0..UINT64_MAX, including numeric capability usage maps,
  generations, budgets, times and independent audit attempts. No float conversion.
- Optional empty strings, zero values, absent messages and unknown signed enums
  remain distinguishable. Contradictory oneofs and unsupported behavioral enums
  fail with bounded raw evidence rather than selecting a known success.
- Policy pages require size 1..32 and a page message, with cursors <=117 bytes.
  The server's configured policy default ceiling may be lower (normally 16).
  Capability page absence or size zero selects the server's 128 default, with
  maximum 128 and cursors <=160 bytes. No automatic paging or cursor repair.
- ApplyPolicy requires explicit precondition (zero is create-only), nonempty
  operation ID and the closed input record/metadata shape. The server alone
  validates the document and grants authority. The returned policy/receipt and
  lookup identity, generation, digest and record kind must agree.
- The current policy RPC emits no audit headers. Absence remains absent, not
  Disabled or Durable. Known audit headers preserve raw status plus independent
  u64 attempt; unknown text preserves raw facts without inventing a numeric ACK.
  Unknown audit state cannot overwrite an actually observed mutation receipt.
- Failures preserve known IDs and available raw gRPC status/typed details. Local
  pre-dispatch rejection is NotDispatched; loss after stream submission is
  conservatively Unknown. There is no automatic Invoke/mutation retry, inferred
  rollback, generated identity or fabricated durable attempt.
