# Ingress and trigger architecture

Capsules never own listeners, queue-consumer loops, or timer threads. Shared ingress adapters and trigger sources translate external activity into activation envelopes.

The completed Phase 2 node exposes direct invocation RPC on its authenticated
loopback listener. Phase 3 plans HTTP ingress, event delivery and bounded local
service calls. Durable workflow timers belong to Phase 6; blob-trigger adapters
also remain future work. The trigger lifecycle below is an architectural
contract, not a current background service. See the [roadmap](../roadmap.md).
See the [invocation service](../protocol/invocation-service.md) for available calls.

## Ingress adapters

An adapter terminates one protocol, authenticates or extracts a principal, maps protocol metadata to an invocation target, applies payload limits, and converts the activation outcome back into a protocol response.

Planned protocol classes are HTTP, direct RPC, events, queues, timers, blobs, and internal calls. Future implementations may support multiple concrete products behind one class.

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
