<!-- LSF-WIKI-MANAGED -->
# Execution cells and code ownership

Execution cells are configured shared resources. A dormant service owns no cell, guest heap, dedicated thread or listener. Each admitted call receives a fresh Store and activation host state; reuse preserves runtime infrastructure, not the previous guest's mutable memory.

Preparation finishes before the cell lease. The configured compiler workers, admission queues and class pools are bounded. Broken or unsafe-to-reuse state is quarantined rather than silently returned to service.

| Resource | Ownership and limit |
| --- | --- |
| Prepared runtime | Bounded resident cache plus ready/active pins; eviction does not invalidate a live owner. |
| Raw package blob | Storage-only cache pin/read/write allowances; catalog and evidence ownership remain separate. |
| Isolated compilation | Reserved job, input/document/output allowances and an owned child until kill/reap completes. |
| Native receipt | Small bounded locator record; untrusted until authenticated by the protected host authority. |
| Native image | Independent image/mapping allowance held through runtime and active pins. |
| Guest execution | Fresh Store, cell lease and admitted ledger until reclamation. |

Optional trusted AOT launches one approved compiler job in a Linux sandbox. It compiles portable input without instantiating a guest. Native loading requires the exact authenticated output, configuration and source binding plus current eligibility. This compiler child is not a general isolated guest execution host.

The producer defaults to two reserved/running jobs and a 30-second whole-job deadline. One component is capped at 64 MiB; native output defaults to 128 MiB. Integrated cache/image limits can be tighter, and aggregate byte allowances can exhaust before job or entry counts. These are reservation domains, not measured RSS ceilings.

Native cache hits still check their source and receipt; resident prepared hits retain compact current-catalog checks. Neither path upgrades an old lifecycle capability. Missing or rejected cache content permits at most one isolated refill; trust, source, cancellation, deadline and resource failures remain failures.

Shutdown and cancellation signal work and retain ownership until actual completion. A timed-out join does not refund a running job. Input bytes can overlap a native mapping during copying; snapshots distinguish loading subsets from totals to avoid double-counting.

Historical engine-profile and memory comparisons retain their original configurations in [Performance and infrastructure](Performance-and-Infrastructure). They do not establish current Phase 2 throughput or universal latency targets.

Authorities: [Wasmtime runtime](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/runtime/wasmtime.md), [isolated AOT and native cache](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/runtime/trusted-aot.md), [raw cache](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/reference/raw-artifact-cache.md).
