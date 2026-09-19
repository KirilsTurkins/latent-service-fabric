# Ingress and trigger architecture

Capsules never own listeners, queue-consumer loops, or timer threads. Shared ingress adapters and trigger sources translate external activity into activation envelopes.

The completed Phase 2 node exposes direct invocation RPC on its authenticated
loopback listener. Phase 3 provides [bounded local service calls](../runtime/local-service-invocation.md),
[shared NATS trigger delivery](../runtime/nats-triggers.md), and the
[bounded HTTP application mapping](../protocol/http-applications.md),
[durable HTTP routes](../reference/http-triggers.md) and an optional
[shared HTTP/TLS listener](../reference/http-ingress.md). HTTP selection pins the
publication, revision and policy snapshot before normal admission. Finite
connection, exchange, input, output and cleanup ownership applies to all routes.
Durable workflow timers belong to Phase 6; blob-trigger adapters also remain
future work. See the [roadmap](../roadmap.md).
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

Acknowledgement occurs only according to the trigger's delivery contract. Trigger events carry stable event and idempotency identifiers so duplicate delivery is safe where component logic supports it. A broker's durable consumer position does not provide an LSF state/effect transaction or exactly-once external execution.

## Planned durable timers

A timer is durable metadata interpreted by a shared timer source. Waiting does not retain an activation, cell, component instance, or thread.

## Backpressure

Ingress must reject, defer, or pause sources when admission queues are full. It must not create new service-specific workers to absorb overload.
