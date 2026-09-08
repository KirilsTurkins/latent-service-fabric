# Phase 1 generic invocation service

`latent-wire::invocation` implements the generated Tonic `Invoke`, `Cancel`,
and `GetActivation` methods. `LocalInvocationRuntime` connects the adapter to
`LocalActivationManager`, the existing activation lifecycle and bounded journal.
The service remains embeddable. The [standalone Linux node](../reference/standalone-node.md)
supplies listener configuration, trusted authentication and shared runtime
composition (#14).

## Generated RPC foundation

`latent-rpc` generates the authoritative Protobuf messages, clients, server trait,
server wrapper, and descriptor set from `api/proto`. The adapter reuses these
outputs directly. `InvocationServiceAdapter::new(runtime, limits)` validates its
configuration; `with_services` additionally injects the clock, principal policy,
and trace source. `into_server` applies the message ceiling to both decoding and
encoding.

Conversions preserve optional presence, the three outcome categories, every
budget and accounting field, ordered structured error details, and map values.
The descriptor golden protects field numbers, cardinality, oneofs, enums,
service methods, and reserved fields.

## One lifecycle owner

The adapter validates a request and supplies its trusted principal and trace in
`InvocationCommand`. `LocalInvocationRuntime` translates that command into
`ActivationRequest` with `retry_attempt = 0`. The protocol has no caller retry
field; arbitrary metadata does not change it.

`LocalInvocationRuntime::invoke` calls `LocalActivationManager::start`
synchronously before returning its future. The resulting handle owns the exact
accepted identity, pinned route, accounting, preparation, cell cleanup, and
terminal publication. The adapter creates no parallel status map, detached
execution task, or second activation lifecycle.

Once accepted, a caller-supplied activation ID supports status and cancellation
while the unary Invoke is still pending. An absent ID requests manager assignment.
Present empty IDs remain present and fail validation. With neither root nor
parent, the manager uses the effective activation ID as root. A parent without a
root is rejected; explicit root/parent values are bounded opaque correlation
claims and require no local ancestor lookup. They grant no additional authority.

Cancel/Get derive the tenant from authenticated context and call the manager's
scoped operations. Scope validation and lookup/mutation occur together. Foreign
and unknown IDs produce the same NotFound behavior. The manager retains active
records and bounds terminal retention; eviction means NotFound cannot establish
that an activation never executed. Retained IDs reject duplicate invocation;
an ID may receive a new owner after its old terminal record is evicted.

## Trusted local authentication and trace context

A listener or interceptor inserts `AuthenticatedInvocationContext` into Tonic
request extensions. Missing context is unauthenticated. The default
`LocalPrincipalPolicy` rejects anonymous, malformed, or unscoped identities;
service principals also need a service identity. Every principal, including an
administrator, must carry the exact invocation tenant. Principal claims remain
trusted embedding input, never facts reconstructed from caller metadata.

Authentication/context bounds are checked before cloning retained principal
information. Invocation metadata under case-insensitive `latent.auth.*` and
`latent.principal.*` prefixes is rejected before lifecycle work starts.
Replacing `PrincipalPolicy` does not bypass the manager's tenant boundary.

`InvocationServiceServices` owns an injectable `ActivationClock`,
`PrincipalPolicy`, and `InvocationTraceSource`. The default trace source creates
fresh trace/span correlation IDs from a source namespace and checked sequence,
with flags zero and empty baggage. Trace source output is bounded and validated
before acceptance. Invoke metadata supplies neither authentication nor trace
propagation. This is a local convention, not an external identity provider or
an implementation of incoming trace-header propagation.

## Bounded request handling

`InvocationLimits` caps encoded requests/responses, payloads, metadata counts and
bytes, identifiers, strings, cancellation reasons, deadlines, budget grants,
and public error details. Borrowed trusted context is bounded before cloning,
and owned request allocations are checked before transfer to the lifecycle.
The manager independently enforces its configured request and journal limits;
node composition must configure compatible ceilings.
`LocalInvocationRuntime::new(manager)` uses default RPC limits;
`with_limits(manager, limits)` validates and retains custom limits for the
bridge's scoped principal checks. Custom composition supplies the same limits
to the adapter and bridge, with compatible manager request limits.

Missing targets/budgets, malformed IDs, forged principal metadata, expired
request deadlines, and oversized input fail before route resolution, admission,
or cell allocation. Explicit zero resource grants remain hard ceilings. Child
calls, outbound requests, state/blob I/O, and effects must all be zero in Phase 1.

## Deadlines and dropped RPC futures

The request deadline, trusted transport deadline, and `grpc-timeout` header can
each tighten the effective deadline. The same sampled clock relates the wire
absolute deadline and the local monotonic wait; no later wall-clock sample
restarts the allowance. Relative budget wall time remains admission-relative.
The adapter and manager clocks must use the same monotonic domain. The adapter
checks the remaining allowance again after synchronous acceptance: if a Received
observation consumes the deadline, the accepted handle expires before its first
lifecycle poll, so no route or cell work begins.

Each invocation has an independent typed interruption token. Explicit
cancellation and deadline expiry remain distinct causes, with the first accepted
cause preserved. Dropping the RPC future drops its owned manager handle and
performs terminal publication and cleanup. A transport deadline consumes the
same handle with a deadline disposition, including before its first poll; it
never looks up an ID later and risks cancelling a replacement owner.

A cancellation, timeout, or lost response does not prove execution never began.
The caller may query the known ID; the adapter and SDK contracts add no automatic
Invoke retry. Cancelling one RPC does not cancel other calls sharing a connection.

## Outcomes, status, and public errors

Guest success, declared domain error, and platform failure occupy distinct
response branches. Accepted terminal responses contain the activation ID and
final consumption. When resolution succeeded, the receipt includes that exact
revision, release digest, and route generation. An accepted failure before
resolution represents the absent pin as empty revision/release strings and
route generation zero; it never invents routing data. That representation is
valid only for a platform-failure response.

GetActivation preserves live phase and terminal category, completion time,
success summary or error, and final accounting. Cancel returns Accepted,
AlreadyTerminal with its terminal state, or NotFound. Malformed requests and
pre-acceptance failures use transport status; accepted execution failures remain
platform outcomes unless the transport itself has ended.

Canonical domain/Protobuf conversions preserve internal platform errors. The
public adapter separately replaces diagnostic messages with fixed code-specific
text and permits only typed fields from known public detail kinds. Unknown
kinds, credentials, paths, connection strings, and backtraces are omitted.
Declared guest error data remains application data in its own result branch.

## Focused validation

```sh
cargo test --locked -p latent-wire
```

The `invocation_service` integration target calls all three generated RPC methods
in process using a real manager, admission controller, and scheduler. Tiny local
catalog, artifact, and backend fixtures cover pending status/cancellation, strict
tenant scope including administrators, optional identity and opaque lineage,
trace/retry defaults, pre-acceptance rejection, absent/pinned failure receipts,
retained ID reuse, catalog pinning, outcome/accounting preservation, public error
redaction, dropped-call isolation, a short live timeout, and cell cleanup/reuse.
Completion waits have five-second watchdogs. These tests open no listener and
run no Wasmtime workload, scale test, or soak. Separate
[standalone node tests](../reference/standalone-node.md) exercise socket-level
composition and the bounded release-to-invocation workflow.
