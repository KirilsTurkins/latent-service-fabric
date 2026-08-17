# State and effect architecture

## State models

### Stateless

The activation consumes input and returns output. No state transaction is created.

### Transactional keyed state

The activation receives a namespace-scoped transaction. Reads record observed versions; writes and deletes are staged. Commit uses optimistic concurrency.

### Entity state

Operations are routed by entity key to an ephemeral ownership lane. The lane exists while work is queued or active, then releases its lease and disappears.

### Durable workflow

Long-running execution is compiled or authored as an explicit state machine. Suspension persists a continuation and releases the execution cell. Arbitrary native-stack checkpointing is not part of the model.

## Transaction boundary

```text
begin state transaction
  → execute guest
  → validate read set
  → commit state mutations and effect intents
  → return commit receipt
```

A guest trap or cancellation before commit discards staged mutations and uncommitted intents.

## External effects

External operations are represented as durable effect intents with:

- deterministic effect identifier,
- activation identifier and sequence,
- provider and operation,
- payload or blob reference,
- stable idempotency key,
- deadline,
- retry classification,
- audit identity.

The portable guarantee is durable intent plus stable idempotency identity. LSF does not claim universal exactly-once execution against arbitrary external systems.

## Compensation

Compensatable workflows define explicit compensating effects. Compensation is business logic, not an automatic rollback of an already visible external operation.
