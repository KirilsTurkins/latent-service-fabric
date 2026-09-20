# Renderer memory and shared storage qualification

Both actual Angular resource profiles passed on source `543facdb` on 21 September 2026 (local date), using the protected T1 node, signed fixture exporters, and exact CLI/node/compiler identities in the [build receipt](phase3-resource-evidence/2026-09-21-renderer-memory-11-build.json). The [matrix receipt](phase3-resource-evidence/2026-09-21-renderer-memory-11-matrix.json) binds both runs. The Docker Desktop container had three CPUs and 6 GiB on a shared host; timings describe these observations only.

| Observation | One-cell smoke | Two-cell campaign |
| --- | ---: | ---: |
| Admitted dormant deployments | 2, 4 | 2, 4, 8 |
| OS/runtime observations | 48 | 59 |
| Cold preparation | 21.53 s | 21.83 s |
| Cold render including CLI | 93.77 ms | 245.74 ms |
| Warm render including CLI | 88.34 ms | 242.65 ms |
| Per-invocation Wasm memory high-water mark for successful renders, exceptions and recovery | 22,413,312 bytes | 22,413,312 bytes |
| Configured per-invocation memory ceiling | 268,435,456 bytes | 268,435,456 bytes |

The memory observations come from the runtime's `BudgetConsumption.peakMemoryBytes`, which tracks aggregate Wasm linear-memory growth and includes the JavaScript engine's heap. They are distinct from process RSS and do not isolate JavaScript allocator live bytes. Summing invocation peaks would not measure simultaneous memory. Cancelled activation status does not retain consumption: all two/four cancellation records keep that value unavailable. Rejected or unfinished churn/overload calls retain their actual zero or unavailable values and are never counted as successful renders.

All seven checks passed in each profile: requested deployment populations, dormant process/thread/listener plateaus, observed active renderer cells, return of active ownership after churn, and prepared-cache plateau. The node shut down cleanly, was reaped, temporary outputs were removed, and signed fixture bytes remained unchanged. Explicit cancellation and client disconnect both reached the required cancelled terminal state; cell/queue observations, not an assumed heap value, establish cleanup.

## Component, package, publication and storage counts

Each fresh catalog admitted **one component, two packages, and two independent publications**. The second publication shares component bytes while retaining its own package/evidence identity. Dormant storage measurements include the owned node directory and audit metadata; they are bounded, non-atomic file-stat observations.

| Dormant storage observation | Four deployments | Eight deployments |
| --- | ---: | ---: |
| Files / unique inodes | 101 / 63 | 109 / 71 |
| Logical bytes across file names | 73,659,933 | 73,686,453 |
| Logical bytes across unique inodes | 24,588,953 | 24,615,473 |
| Allocated filesystem bytes | 24,768,512 | 24,821,760 |

The 49,070,980-byte difference between named and unique-inode logical storage is shared physical content, not a reduction in application count. Increasing dormant deployments added metadata while the number of processes, threads and listeners stayed fixed. These results make no Docker/Kubernetes or single-hot-service throughput comparison.

## Retained records and limits

- [One-cell observations](phase3-resource-evidence/2026-09-21-renderer-memory-11-web-smoke.json) and [fixture export](phase3-resource-evidence/2026-09-21-renderer-memory-11-web-smoke-export.json).
- [Two-cell observations](phase3-resource-evidence/2026-09-21-renderer-memory-11-web-campaign.json) and [fixture export](phase3-resource-evidence/2026-09-21-renderer-memory-11-web-campaign-export.json).
- [Earlier failed collector run](phase3-resource-evidence/2026-09-21-renderer-memory-10-web-smoke.json) and its [failed matrix](phase3-resource-evidence/2026-09-21-renderer-memory-10-matrix.json) remain unchanged. It incorrectly required a consumption value from cancelled status. The corrected collector explicitly reports that unsupported field as unavailable; actual rendered memory remains mandatory and bounded.

Every JSON has a SHA-256 sidecar. The receipt still marks full ticket acceptance pending. OCI token/resolver/redirect measurements remain required for #239. The [provider checkpoint](phase3-resource-events.md) and [standalone provider profiles](phase3-resource-recovery.md) separately establish their measured resource populations. Actual browser journeys are retained by the Angular reference qualification.
