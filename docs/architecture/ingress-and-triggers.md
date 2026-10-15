# Ingress and trigger architecture

Capsules never own listeners, queue-consumer loops, or timer threads. Shared ingress adapters and trigger sources translate external activity into activation envelopes.

The node exposes direct invocation RPC on its authenticated
loopback listener. It also provides [bounded local service calls](../runtime/local-service-invocation.md),
[shared NATS trigger delivery](../runtime/nats-triggers.md), and the
[bounded HTTP application mapping](../protocol/http-applications.md),
[durable HTTP routes](../reference/http-triggers.md) and an optional
[shared HTTP/TLS listener](../reference/http-ingress.md). HTTP selection pins the
publication, revision and policy snapshot before normal admission. Finite
connection, exchange, input, output and cleanup ownership applies to all routes.
Durable workflow timers and blob-trigger adapters are not implemented.
See the [invocation service](../protocol/invocation-service.md) for available calls.

## Ingress adapters

An adapter terminates one protocol, authenticates or extracts a principal, maps protocol metadata to an invocation target, applies payload limits, and converts the activation outcome back into a protocol response.

Protocol classes are HTTP, direct RPC, events, queues, timers, blobs, and internal
calls. Declaring a class does not install its adapter. Current NATS triggers use
shared durable consumer ownership; current HTTP application types use a bounded
collector/invocation/delivery owner, preserve repeated headers and obtain identity
from host context. Capsules own no protocol listener.

Browser-facing HTTP also enforces the closed
[same-origin and hydration policy](../security/browser-boundary.md). It shares
the existing transport/asset/cache owners; browser origin metadata is neither
RPC authentication nor a tenant/publication grant.

## Trigger lifecycle

```text
trigger resource
  → shared source adapter
  → source position / acknowledgement state
  → trigger event
  → activation mapping
  → activation dispatch
  → source acknowledgement
```

Acknowledgement follows the installed trigger's delivery contract. The generic
`TriggerEvent` declaration has an optional idempotency key; it does not supply
deduplication. The ordinary NATS adapter starts fresh stateless activations with
no host command key. Applications needing duplicate protection must retain
their own stable input identity or use the separately installed transactional
inbox contract. A broker's durable consumer position provides neither an LSF
state/effect transaction nor exactly-once external execution.

## Transaction ingress and acknowledgement

The explicitly installed [transaction HTTP profile](../development/transaction-http-v1.md)
maps direct command, fresh-query and original-result routes onto the same
runtime. Commands retain the original `Idempotency-Key`, canonical request and
edit preconditions; the host validates its bounded result representation before
durable completion. Current data permission is checked through response writes.
A lost HTTP reply cannot undo a committed command or authorize a new key.

The ordinary [NATS trigger](../runtime/nats-triggers.md) is a stateless delivery
profile and does not itself install transactional inbox/outbox semantics.
Transactional incoming identity and acknowledgement use their separately
installed [inbox owner](state-and-effects.md#incoming-identity-formats-and-linked-retention).
Neither a trigger acknowledgement nor an HTTP status proves deferred effect
delivery. Query/result reads start no outbox dispatch.

## Planned durable timers

A timer is durable metadata interpreted by a shared timer source. Waiting does not retain an activation, cell, component instance, or thread.

## Backpressure

Ingress must reject, defer, or pause sources when admission queues are full. It must not create new service-specific workers to absorb overload.
