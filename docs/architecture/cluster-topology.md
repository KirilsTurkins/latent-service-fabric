# Cluster topology

## Control plane

Two or more `latent-control` instances may share PostgreSQL and an OCI registry. They expose management APIs and distribute route snapshots. A custom consensus system is not required for the initial architecture.

## Data plane

Every `latentd` node can execute any compatible release it can retrieve, verify, prepare, and admit under its trust and placement policies.

## Node identity

Node and control communication requires mutually authenticated transport. The architecture supports SPIFFE-compatible workload identities but does not require a specific identity provider in the interface scaffold.

## Remote invocation

A remote call carries the exact revision ID, release digest, contract, function, route generation, principal delegation, trace context, remaining deadline, delegated resource budget, and idempotency information.

The receiving node must execute that exact release or reject the call. It may not silently substitute a newer route.

## Availability

Availability is expressed as eligible nodes and cached artifact copies rather than running replicas:

```text
minimum cached copies
minimum zones
allowed trust classes
allowed architectures
required accelerators or CPU features
```

## Node failure

- unstarted queued work may be re-routed,
- stateless work may be retried only under retry policy,
- uncommitted state is discarded,
- committed state remains durable,
- effect intents in the outbox remain durable,
- entity leases expire,
- workflow continuations remain persisted.
