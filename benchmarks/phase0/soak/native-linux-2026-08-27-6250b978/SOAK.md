# Phase 0 native-Linux resource plateau soak

**Status:** PASS
**Schema:** `latent.phase0.resource-soak.aggregate.v1`
**Generated:** 2026-08-27T17:01:21+00:00
**Aggregate:** `benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/aggregate.json`

> Observational Phase 0 evidence only. This is not a production SLO, capacity guarantee, or cross-machine claim.

## Final configuration and repetitions

- Final configuration/source commit: `6250b9782ffc4174676d2d72bd023dbfc38c39d7`
- Source tree: `65ba341221ea89e107a3e0e3c4b0aed7e26efd9b`
- Independent native-Linux processes: 3
- Final ordinary execution configuration: prepared cache enabled; Wasmtime allocator `on_demand`; initialized-memory COW `true`.
- Every process contains at least 1,000 excluded warm-up activations and 100,000 normal measured fresh-store activations; saturation activations are additional measured work.
- Every completed batch checks logical resources, topology, bounded cache/log/timing state, and the configured pool state before its raw interval sample is retained.

## Raw evidence

The raw paths below are losslessly retained in `raw-evidence.tar.zst`; verify its `raw-evidence.manifest.sha256` and extract it before inspection.

| Run | Raw file | SHA-256 | Component digest |
|---|---|---|---|
| run-01 | `runs/run-01/raw.json` | `sha256:ddc02b0cf61896b4a4a80249cb92add139abef392ba31993619f989b7ab6d130` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |
| run-02 | `runs/run-02/raw.json` | `sha256:0b7bad4ae32094637d9d8313cb3f8baa20c4b96fc7ac7b0ea9a3eef7dfd4c3f3` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |
| run-03 | `runs/run-03/raw.json` | `sha256:4f58c8941db0179bc837d95a38e96cbb9d11defbff92e704387e35f68a521fd9` | `sha256:1eaac4fc014071b09eae665bfbe093bf453b447128d0ca720ab2ec2ae798fa3b` |

Exact retained process commands:
- run-01: `/home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/release/phase0-soak --capsule /home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/phase0-resource-soak/staged-containment/capsule.json --output-json /home/slirik/IdeaProjects/latent-service-fabric/benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/runs/run-01/raw.json --run-index 1 --source-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7 --source-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --execution-commit e8fcc441ca96a0f4e66793733a334a6bd4b4eeac --execution-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --final-configuration-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7`
- run-02: `/home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/release/phase0-soak --capsule /home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/phase0-resource-soak/staged-containment/capsule.json --output-json /home/slirik/IdeaProjects/latent-service-fabric/benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/runs/run-02/raw.json --run-index 2 --source-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7 --source-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --execution-commit e8fcc441ca96a0f4e66793733a334a6bd4b4eeac --execution-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --final-configuration-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7`
- run-03: `/home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/release/phase0-soak --capsule /home/slirik/IdeaProjects/latent-service-fabric/target/phase0-resource-soak-work/phase0-resource-soak/staged-containment/capsule.json --output-json /home/slirik/IdeaProjects/latent-service-fabric/benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/runs/run-03/raw.json --run-index 3 --source-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7 --source-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --execution-commit e8fcc441ca96a0f4e66793733a334a6bd4b4eeac --execution-tree 65ba341221ea89e107a3e0e3c4b0aed7e26efd9b --final-configuration-commit 6250b9782ffc4174676d2d72bd023dbfc38c39d7`

## Post-warm-up plateau analysis

The raw interval series retains rolling ranges, peak, final-window delta, and a Theil-Sen robust late-window slope per run. RSS and PSS/private material-growth decisions use the matched #38 calibrated RSS noise band; PSS/private use that byte-scale band only because #38 did not collect a separate PSS/private reference.

| Metric | Availability | Peak median | Final-window delta median | Late slope median | Decision |
|---|---|---:|---:|---:|---|
| rss_bytes | available | 18116608.0 | 8192.0 | 364.2688 | pass |
| virtual_memory_bytes | available | 231780352.0 | 0.0 | 0.0000 | pass |
| pss_bytes | available | 15604736.0 | 8192.0 | 364.2688 | pass |
| private_bytes | available | 15421440.0 | 8192.0 | 364.2688 | pass |
| prepared_cache_source_bytes | available | 27616.0 | 0.0 | 0.0000 | observed |
| backend_timing_store_entries | available | 0.0 | 0.0 | 0.0000 | observed |
| active_leases | available | 0.0 | 0.0 | 0.0000 | observed |
| queue_depth | available | 0.0 | 0.0 | 0.0000 | observed |

## Run-level variability

Robust outliers are retained for review. A stable late-window series within its calibrated material-growth bound is observed variability, not evidence of a sustained leak.
- pss_bytes: run-03 (within calibrated late-window bound).

## Topology, descriptors, release, and shutdown

File descriptors: **PASS**; the final post-warm-up FD count must equal the first post-warm-up FD count in every independent process.
- process_count: **PASS**
- child_process_count: **PASS**
- thread_count: **PASS**
- open_socket_count: **PASS**
- listening_socket_count: **PASS**
- Every post-release snapshot has zero prepared-cache entries/bytes and zero logical runner/backend/pool/log/timing resources; every raw run also includes a clean runtime-shutdown check.

## Method and limits

- The command is explicit native-Linux soak work and intentionally does not run in shared PR smoke CI.
- The runner refuses WSL, containers, unavailable Linux probes, mismatched source trees, missing fixture/toolchain output, missing raw batches, and test-only output.
- The workload uses the real shared Phase 0 runtime, bounded fixed pool, Wasmtime backend, prepared cache, activation runner, fresh store per activation, and real at-capacity/bounded-queue lease coordination.
- Allocator-internal statistics are optional and are explicitly reported unavailable unless a safe allocator-specific probe is later configured.

## Conclusion

All three-or-more comparable native-Linux processes passed every hard invariant and showed no calibrated material RSS/PSS/private/VM growth, no unexplained net FD growth, and stable bounded topology. This is a Phase 0 plateau observation for the recorded final configuration, not a production claim.
