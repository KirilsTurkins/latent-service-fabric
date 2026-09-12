<!-- LSF-WIKI-MANAGED -->
# Activation lifecycle

An activation pins one selected revision and route generation, owns its admitted budget and ends only after execution and cleanup ownership are accounted for.

1. Authenticate and validate bounded input; resolve the tenant-scoped route.
2. Select and pin the exact revision, lifecycle capability and applicable signed eligibility.
3. Admit finite running/queue capacity and the supported resource ledger.
4. Prepare through the bound catalog and cache/compilation path before leasing a cell.
5. Recheck current eligibility at the guarded invocation start.
6. Run in a fresh Store with the pinned deadline and supported host state.
7. Publish terminal accounting, reclaim owned work and reuse or quarantine the cell.

A cache hit cannot skip eligibility. Queued or prepared pins are not accepted starts. A policy, lifecycle or authority change can deny old work before start; calls already accepted by the final authority fence may finish.

Deadline, explicit cancellation and disconnect cleanup retain the real owner until work retires. The fixed disconnect supervisor avoids one cleanup worker per request. Cancellation acknowledgement does not prove that a child, native image, queue reservation or guest resource has already been reclaimed.

Canary capture attributes selected revisions without changing admission budgets. The sample has one terminal owner. Lost, abandoned or unattributed observations stay visible and can only reduce coverage. A sealed promotion window requires a complete interval and drained frontier; a snapshot or a live count is not promotion permission.

Activation IDs support correlation and bounded retained status. Retention and restart can make activation status unknown; durable control operation receipts are a different surface. They do not make invocation effects exactly once or preserve a guest heap.

See [Execution cells](Execution-Cells), [Deployment and routing](Deployment-and-Routing) and [State and effects](State-and-Effects).

Authorities: [invocation protocol](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/protocol/invocation-service.md), [resource budgets](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/runtime/resource-budgets.md), [canary observation](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-canary-observation.md), [release lifecycle](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/release-lifecycle.md).
