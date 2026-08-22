# State and Effects

> **Document role:** Semantic guide. The state architecture and commit protocol define the canonical guarantees.

## State models

### Stateless

The activation consumes input and returns output. No state transaction is created.

### Transactional keyed state

The activation receives a namespace-scoped transaction. Reads record observed versions; writes and deletes are staged. Commit uses optimistic concurrency.

### Entity state

Operations are routed by entity key to an ephemeral ownership lane. The lane exists while work is queued or active, then releases its lease and disappears.

### Durable workflow

Long-running execution is an explicit state machine. Durable suspension persists a continuation and releases the execution cell. Arbitrary native-stack checkpointing is outside the model.

## Transaction boundary

```text
begin state transaction
  → execute guest
  → validate read set
  → persist state mutations and effect intents
  → create commit receipt
```

A trap or cancellation before commit discards staged mutations and uncommitted intents.

## Effect intents

An external effect intent records:

- deterministic effect identifier;
- activation identifier and sequence;
- provider and operation;
- payload or blob reference;
- stable idempotency key;
- deadline;
- retry classification;
- audit identity.

The durable platform guarantee is the intent plus its stable identity. Dispatch may occur after the invocation result is committed.

## Atomicity

Where the selected backend supports it, state mutations and effect-outbox records commit atomically. When a backend cannot provide that boundary, the deployment must explicitly accept weaker semantics or select another coordinator/backend combination.

## Exactly-once boundary

LSF does not claim universal exactly-once execution against arbitrary external systems. A provider may apply an operation, lose the response, and receive a retry. Correctness depends on idempotency support, status inspection, or explicit compensation.

## Lost responses

A client timeout does not establish whether commit occurred. Recovery should inspect activation or commit status and distinguish:

- unknown;
- preparing;
- committed;
- aborted;
- recovery required.

Blind re-execution of a write is unsafe unless the operation contract permits it.

## Compensation

Compensation is explicit business logic. It is not an automatic rollback of an external effect that is already visible.

A workflow may define compensating effects, but those effects have their own failure and idempotency semantics.

## Child calls and budgets

A child invocation cannot exceed the parent's remaining deadline, CPU, fan-out, outbound-call, state, blob, log, or effect budgets. State and effect semantics should remain equivalent whether a provider binding is inline, isolated local, or remote.

## Design checklist

For every stateful or effectful operation, document:

- transaction scope and namespace;
- conflict behavior;
- commit level promised to the caller;
- idempotency identity;
- retry classification;
- status-inspection path;
- external provider guarantees;
- compensation logic;
- observability and audit requirements.

## Canonical sources

- [State and effect architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/state-and-effects.md)
- [Commit protocol](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/commit-protocol.md)
- [Activation lifecycle](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/activation-lifecycle.md)
- [ADR 0013: explicit transactions and effect intents](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/adr/0013-use-explicit-state-transactions-and-effect-intents.md)
- [ADR 0014: no universal exactly-once promise](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/adr/0014-do-not-promise-universal-exactly-once-external-effects.md)
