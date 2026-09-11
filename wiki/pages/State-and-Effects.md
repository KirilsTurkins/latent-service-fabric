<!-- LSF-WIKI-MANAGED -->
# State and effects: later-phase design

**Phase 1 is stateless.** Durable keyed state, effect outbox, entity ownership lanes, state transactions and durable workflow suspension are not exposed. Corresponding contracts/traits are design surfaces, not provider guarantees. Nonzero state/blob/effect/child-call budgets are rejected by Phase 1.

Phase 4 plans namespace-scoped transactions, optimistic concurrency, atomic state/effect-intent commit where supported, durable outbox dispatch, idempotency and entity-key routing. Phase 6 plans explicit workflow state machines, timers, awaited effects, replay and compensation.

The design does not promise universal exactly-once external effects. A provider can apply an operation and lose the response; recovery requires stable identity, status inspection, idempotency or compensation. Timeout never establishes nonexecution. This also informs current stateless outcome handling.

Future durable suspension persists explicit continuation state and releases the cell. Arbitrary native-stack checkpointing is outside the current model. Paging/fusion/continuation experiments remain optional and unpromoted.

Authorities: [state/effects architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/state-and-effects.md), [commit protocol](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/commit-protocol.md), [roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/roadmap.md).
