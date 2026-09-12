<!-- LSF-WIKI-MANAGED -->
# State and effects

Guest execution remains stateless in Phase 2. Each activation receives fresh mutable guest and host state. Prepared-code reuse, native caching and dormant release metadata do not preserve a service heap between calls.

Durable release/deployment catalogs, lifecycle history, audit records and rollout plans are control state. Their atomic publication and operation receipts do not provide transactional guest storage or an effect outbox.

Context, accepted logs and clocks are the delivered host capabilities. Unsupported nonzero child-call, outbound, blob, state or effect dimensions remain denied according to the current runtime profile. A manifest declaration cannot activate an unimplemented provider.

Phase 3 plans explicit capability brokers and bounded provider families, including local child calls with descendant budgets. Each operation must define authorization, quota, cancellation and cleanup. External event delivery will have its own consumer/trigger semantics.

Transactional guest state and effects remain Phase 4. Cluster coordination belongs to Phase 5; durable workflow state machines and resumable orchestration belong to Phase 6. These are separate from the current operator rollout state machine.

An activation ID does not make effects exactly once. A timeout or Unknown result does not prove an external action did not occur. Future integrations must state their idempotency and recovery contracts rather than inferring them from transport cancellation.

Authorities: [capabilities](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/runtime/capabilities.md), [resource budgets](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/runtime/resource-budgets.md), [roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/roadmap.md).
