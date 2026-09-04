# Phase 1 generic invocation service

Issue #12 implements the hardened `latent.invocation.v1.InvocationService` as
an embeddable Tonic service in `latent-wire::invocation`. The implementation
owns no listener, socket, worker pool, or activation lifecycle. `latentd` can
wrap it in any local listener and inject the Phase 1 activation manager through
the `InvocationRuntime` seam.

## Generated RPC foundation

The authoritative files under `api/proto` are compiled once by `latent-rpc`.
`latent-wire` directly reuses the generated messages,
`InvocationServiceClient`, `InvocationServiceServer`, and server trait. It does
not have a build script, checked-in generated template, private Protobuf codec,
or parallel method-path constants.

The generated server wrapper applies the configured message ceiling to both
decoding and encoding. Domain conversion helpers preserve optional presence,
oneof outcome identity, every budget and accounting field, ordered structured
error details, stable lower-kebab-case platform codes, and map values. The
repository descriptor-set golden remains authoritative for field numbers,
cardinality, oneofs, enums, service methods, and reserved fields.

## Lifecycle ownership

The RPC boundary validates and converts a request into `InvocationCommand`; it
does not construct `ActivationEnvelope`, allocate activation/root/trace IDs,
resolve a route, publish status, or own cleanup. Those responsibilities stay in
the single activation manager implemented by issue #11.

`InvocationRuntime::invoke` must reserve the manager-selected activation ID and
its authenticated owner atomically before the operation can yield. Its
`cancel` and `get_activation` operations receive the authenticated principal
and must combine ownership authorization with the lifecycle lookup/mutation at
one linearization point. The service never treats a missing status snapshot as
permission to cancel, closing the invoke/status-publication race.

The runtime also owns current status and bounded terminal retention. Active
records must never be evicted. This service can therefore be developed and
tested independently, but final node composition and the production retention
implementation remain supplied by issue #11.

## Local authentication convention

A listener or interceptor inserts `AuthenticatedInvocationContext` into Tonic
request extensions. The principal is never reconstructed from arbitrary
invocation metadata. The default `LocalPrincipalPolicy` rejects anonymous or
empty identities; non-administrators must carry the exact invocation tenant,
while administrators may cross tenants. Metadata under `latent.auth.*` and
`latent.principal.*` is rejected before lifecycle work starts.

This convention is explicit and replaceable. A later identity provider can
replace the interceptor and policy without changing the Protobuf contract.

## Bounded request handling

`InvocationLimits` is enforced before the runtime is called. The boundary caps:

- encoded request and response messages;
- payloads and declared-error payloads;
- metadata entry count, individual values, and aggregate bytes;
- identifier, media-type, and cancellation-reason syntax and size;
- caller and `grpc-timeout` durations;
- relative wall-time grants; and
- every resource-budget dimension.

Zero-valued resource grants remain valid hard ceilings. Missing targets or
budgets, malformed IDs, forged principal metadata, expired deadlines, and
oversized inputs fail before route resolution, admission, or cell allocation.

## Deadlines and transport cancellation

The effective absolute deadline is the earliest of the request deadline, the
authenticated transport deadline, and the generated client's `grpc-timeout`
metadata. It is passed to the activation manager and raced at the RPC boundary.
Expiry signals the same per-invocation cancellation token provided to the
manager.

A guard also signals that token whenever the Tonic request future is dropped,
which covers client disconnects and transport-enforced timeouts. Each RPC gets
an independent token, so cancelling one stream cannot cancel another call on
the same connection. A cancelled or lost response still does not prove that
execution never began.

## Outcomes, status, and public errors

Successful guest return, declared guest/domain error, and platform failure use
three distinct generated oneof branches. Immediate responses carry the
manager-assigned activation ID, pinned revision, release digest, route
generation, and finalized consumption. Retained terminal status preserves its
outcome category, completion time, metadata, success summary, and final
accounting.

Canonical `latent-rpc` conversions preserve full internal platform errors for
trusted domain/Protobuf round trips. The public service applies a separate
allowlist policy: messages are stable code-specific text, unknown detail kinds
are omitted, and only narrowly typed fields from known public detail kinds are
retained. Raw diagnostics, payloads, credentials, connection strings,
filesystem paths, and backtraces are not returned by default.

## Validation coverage

Rust tests exercise generated message and domain round trips, all three
generated service methods in process, pre-runtime validation, manager-owned ID
assignment, deterministic cancellation dispositions, terminal accounting,
atomic cross-tenant cancellation before status publication, per-call transport
cancellation isolation, live `grpc-timeout` propagation, and adversarial public
error redaction. The merged contract descriptor golden continues to protect
serialized compatibility.
