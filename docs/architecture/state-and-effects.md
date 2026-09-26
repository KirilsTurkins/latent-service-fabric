# State and effect architecture

Current activations are stateless. Durable management receipts and audit journals
are operational records, not application state transactions. HTTP, blob and event
providers perform immediate capability operations and report acknowledgement or
uncertainty according to their provider contract.

Application transactions, durable effect outboxes, entity leases and durable
workflow suspension are planned. Their imports are unavailable in the runtime.
The designs below explain the distinction; use the
[current activation lifecycle](../activation-lifecycle.md) for supported behavior.

## State models

### Stateless

The activation consumes input and returns output. No state transaction is created.

### Planned transactional keyed state

The activation receives a namespace-scoped transaction. Reads record observed versions; writes and deletes are staged. Commit uses optimistic concurrency.

### Planned entity state

Operations are routed by entity key to an ephemeral ownership lane. The lane exists while work is queued or active, then releases its lease and disappears.

### Planned durable workflow

Long-running execution is compiled or authored as an explicit state machine. Suspension persists a continuation and releases the execution cell. Arbitrary native-stack checkpointing is not part of the model.

## External effect modes

LSF distinguishes immediate capability operations from transactional durable
effect intents. A receipt or audit observation from one mode must not be presented
as evidence from the other.

### Immediate capability operation

HTTP, blob and event providers perform activation-scoped calls directly
through the capability broker after current authority, budgets and provider
resources are established. They do not atomically commit application state and do
not create an application outbox.

Provider contracts preserve four outcome classes where the protocol can support
them:

- rejection before dispatch,
- provider acknowledgement,
- known provider failure, and
- uncertain outcome after possible dispatch.

A provider acknowledgement has provider-specific meaning. It is not proof of
consumer processing, application state commit or exactly-once execution. A local
cancellation, deadline or lost acknowledgement after possible dispatch cannot
prove that a remote mutation did not occur and does not justify automatic replay
of an uncertain mutation.

Provider-owned cleanup records are operational recovery state. For example, a
bounded multipart-upload cleanup inventory can outlive a cancelled caller while
actual cleanup finishes, but it is not a guest transaction or durable effect
outbox.

The HTTP, blob and event provider references specify how each implemented
protocol reports those outcomes. A successful call does not create an application
transaction or outbox.

### Transactional durable effect intent

The planned transactional model would combine application state and effect intents:

```text
begin state transaction
  → execute guest
  → validate read set
  → commit state mutations and effect intents
  → return commit receipt
```

A guest trap or cancellation before commit discards staged mutations and
uncommitted intents. After commit, a durable dispatcher may own delivery and
retry under explicit idempotency and retry rules. The commit receipt proves
local durable intent, not remote completion.

Planned durable effect intents include:

- deterministic effect identifier,
- activation identifier and sequence,
- provider and operation,
- payload or blob reference,
- stable idempotency key,
- deadline,
- retry classification,
- audit identity.

The portable guarantee remains durable intent plus stable idempotency identity.
LSF does not claim universal exactly-once execution against arbitrary external
systems. This retains [ADR-0014](../../adr/0014-do-not-promise-universal-exactly-once-external-effects.md)
while [ADR-0025](../../adr/0025-separate-immediate-capability-operations-from-transactional-effect-intents.md)
narrows ADR-0013's blanket statement that all external effects are journaled
intents.

## Current implementation boundary

[Outbound HTTP](../runtime/outbound-http.md), [S3 blobs](../runtime/s3-blobs.md)
and [NATS events](../runtime/nats-events.md) define protocol-specific immediate
operation semantics. The [async ownership substrate](../runtime/async-host-io.md)
keeps waits, buffers and cancellation cleanup bounded.

Application transaction records, atomic state/effect commit, durable dispatch
and effect retries are not implemented. Provider cleanup journals, invocation
status and audit observations do not substitute for that machinery.

## Compensation

Compensatable workflows define explicit compensating effects. Compensation is business logic, not an automatic rollback of an already visible external operation.
