<!-- LSF-WIKI-MANAGED -->
# Roadmap

| Phase | Status and scope |
| --- | --- |
| 0: feasibility | Complete; August 30 native-Linux receipt authorized its original Phase 1 handoff. |
| 1: single-node stateless | Complete September 8: catalogs/routing, budgets/admission/scheduling, Wasmtime, scoped capabilities/lifecycle/RPC, telemetry, Linux node and CLI. |
| 1 extension | Complete September 11: prioritized optimizations and actual Docker/Kubernetes comparisons; #110 closed as not planned. |
| 2: packaging/supply chain | Next: OCI push/pull, signatures, provenance, SBOM, trusted AOT cache, rollout orchestration, canary and rollback. |
| 3: capabilities | General brokers/grants/providers, HTTP/blob/secrets/events, shared application HTTP ingress with bounded Angular SSR/hydration, pooling/auditing and descendant budgets. |
| 4: state/effects | Transactions, optimistic concurrency, durable outbox, dispatch, idempotency and entity-key routing. |
| 5: cluster | Separate control plane, watches, direct node calls, mTLS identity, prefetch, state affinity and multi-zone placement. |
| 6: durable workflows | Explicit state machines, timers, continuations, awaited effects, replay and compensation. |
| 7: research | Optional paging, continuation eviction, fusion, shared blobs, native SFI and hardware capabilities; promotion requires accepted evidence/design. |

Local release/build foundations, atomic deployment/snapshot publication and deterministic weighted routing are already Phase 1. Local prepared-component caching is not yet trusted distributed AOT supply-chain support. A Kubernetes benchmark does not implement clustered LSF control.

The closed [extension milestone](https://github.com/KirilsTurkins/latent-service-fabric/milestone/5) ends this optimization cycle. Next feature delivery follows the [canonical roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/roadmap.md) and [Phase 2 milestone](https://github.com/KirilsTurkins/latent-service-fabric/milestone/4). Alpha packaging does not make later-phase declarations available runtime features.
