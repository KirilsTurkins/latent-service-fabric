<!-- LSF-WIKI-MANAGED -->
# Activation lifecycle

Phase 1 resolves and pins a route, admits bounded work, prepares immutable readiness before scheduler enqueue, leases a cell, creates fresh Store/host state, executes, records a terminal outcome and proves cleanup before reuse. Exact transitions and public status names are defined by the canonical lifecycle.

An activation owner keeps identity, quota, route generation, cancellation, deadline and accounting together. Caller IDs can be known before completion. Tenant scope controls status/cancel; caller lineage does not establish ancestor authority or retention.

Cancellation and expiry propagate through the same owner. After a transport disconnect, one fixed node cleanup supervisor continues polling admitted owners under their original deadlines. Capacity remains owned until cleanup is proven or conservatively quarantined. No per-service or per-disconnect worker is allocated.

A terminal receipt and completed native cleanup are distinct observations. Status is bounded and restart-local: not-found can mean absent, evicted, restarted or foreign scope. It never proves no work ran. An idempotency field does not promise invocation deduplication.

Stateless success returns output and accounting. Durable state commit, effect dispatch and workflow suspension remain future extensions.

Authorities: [activation lifecycle](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/activation-lifecycle.md), [invocation service](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/protocol/invocation-service.md), [resource budgets](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/runtime/resource-budgets.md).
