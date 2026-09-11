<!-- LSF-WIKI-MANAGED -->
# Execution cells and ownership

Phase 1 uses one process with fixed configured in-process class pools. A generic cell supplies admission/scheduling capacity; a fresh Wasmtime Store and host state belong to each activation. Pools do not grow once per deployment.

Prepared components live in bounded node caches. Eviction drops cache ownership, but in-flight owners can retain entries. Old route/catalog generation pins also extend lifetime. A cache slot is not a cell lease, and active working set differs from dormant catalog count.

Proven cleanup releases capacity; uncertain cleanup quarantines it. The fixed disconnect supervisor retains the same admitted owner and original deadline without per-disconnect tasks.

Keep the on-demand/speed default unless a measured workload justifies pooling's cold compilation, RSS and image-charge costs. Cold admission protects warm execution but can reject more work; fewer completions do not prove faster matched compilation. Queues remain finite and tenant scheduling retains its documented winner scan.

Future trust-class process isolation can use a configured fixed process set. Current in-process class pools do not supply that stronger boundary. Durable workflow suspension and general asynchronous capability providers are later work.

Authorities: [execution cells](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/execution-cells.md), [scheduling](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/scheduling.md), [Wasmtime](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/runtime/wasmtime.md), [measured tuning](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/phase-1-extension-completion.md).
