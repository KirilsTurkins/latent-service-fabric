# Ingress and trigger architecture

Capsules never own listeners, queue-consumer loops, or timer threads. Shared ingress adapters and trigger sources translate external activity into activation envelopes.

## Ingress adapters

An adapter terminates one protocol, authenticates or extracts a principal, maps protocol metadata to an invocation target, applies payload limits, and converts the activation outcome back into a protocol response.

Supported architectural protocol classes are HTTP, direct RPC, events, queues, timers, blobs, and internal calls. Implementations may support multiple concrete products behind one class.

## Trigger lifecycle

```text
trigger resource
  → shared source adapter
  → durable cursor
  → trigger event
  → activation mapping
  → activation dispatch
  → source acknowledgement
```

Acknowledgement occurs only according to the trigger's delivery contract. Trigger events carry stable event and idempotency identifiers so duplicate delivery is safe where component logic supports it.

## Timers

A timer is durable metadata interpreted by a shared timer source. Waiting does not retain an activation, cell, component instance, or thread.

## Backpressure

Ingress must reject, defer, or pause sources when admission queues are full. It must not create new service-specific workers to absorb overload.
