# State and effect architecture

The completed Phase 2 node implements the stateless model below. Its durable
release/deployment receipts and audit journal do not constitute a guest state
transaction. Guest state, transactional effect outboxes and entity leases belong
to Phase 4; durable workflows belong to Phase 6. The runtime rejects their
unavailable imports, and ordinary stateless outcomes contain no committed state
versions or effect IDs. Phase 3 external providers use immediate capability
operation semantics: they must report provider acknowledgement and uncertainty
without claiming future transaction guarantees. See
[ADR-0025](../../adr/0025-separate-immediate-capability-operations-from-transactional-effect-intents.md),
the [current activation lifecycle](../activation-lifecycle.md) and
[roadmap](../roadmap.md).

## State models

### Stateless

The activation consumes input and returns output. No state transaction is created.

### Transactional keyed state

The activation receives a namespace-scoped transaction. Reads record observed versions; writes and deletes are staged. Commit uses optimistic concurrency.

### Entity state

Operations are routed by entity key to an ephemeral ownership lane. The lane exists while work is queued or active, then releases its lease and disappears.

### Durable workflow

Long-running execution is compiled or authored as an explicit state machine. Suspension persists a continuation and releases the execution cell. Arbitrary native-stack checkpointing is not part of the model.

## External effect modes

LSF distinguishes immediate capability operations from transactional durable
effect intents. A receipt or audit observation from one mode must not be presented
as evidence from the other.

### Immediate capability operation

Phase 3 HTTP, blob and event providers perform activation-scoped calls directly
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

These semantics are architectural constraints for the planned Phase 3 provider
work; they are not a claim that those providers are already merged.

### Transactional durable effect intent

Phase 4 owns atomic application state/effect intent creation:

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

## Evidence and delivery boundary

The Phase 3 provider tickets own their protocol-specific immediate-operation
semantics: outbound HTTP #211, S3-compatible immutable blobs #214 and JetStream
events #217. The [shared asynchronous ownership substrate](../runtime/async-host-io.md)
implements #205's bounded waiting, buffering and cancellation lifetime. The
integrated failure/uncertainty matrix belongs to #238 and the Phase 3
completion review to #240.

Phase 4 remains responsible for the application transaction/outbox records,
atomic commit, dispatcher, retries, reconciliation and effect-commit receipts.
Phase 3 provider cleanup journals, invocation status and audit observations do
not substitute for that future machinery.

## Compensation

Compensatable workflows define explicit compensating effects. Compensation is business logic, not an automatic rollback of an already visible external operation.
