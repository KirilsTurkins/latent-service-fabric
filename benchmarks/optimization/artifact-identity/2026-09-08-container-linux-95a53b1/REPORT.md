# Artifact identity optimization: measured comparison

Historical raw archive payloads are omitted from this checkout. Results and
original validation records remain; recorded replay passes describe publication
checks. [Restore the exact historical package](../../../../docs/testing/benchmark-retention.md) before running raw
replay or extraction commands below. Set `restored_root` to its fresh restore
directory; manifests alone do not make the current directory replayable.

Recorded 2026-09-08 for [#99](https://github.com/KirilsTurkins/latent-service-fabric/issues/99), part of the Phase 1 extension.

The candidate replaces padding-copy SHA-256 with the pinned SHA-256 implementation and streams verified component bytes through 64 KiB scratch. Repository recovery and catalog compilation retain verified metadata without retaining a component buffer. COMPLETE, metadata, digest, size, requested-release and publication checks remain active.

## Sources and collection

- Control: `523af147e691fbf1cd50fe4171a858bcfb8dcc81`, tree `63c58cb54354740eaed622dc64fb1140d2ed3e13`. This is the pre-optimization development source with the same additive benchmark probe and its locked dependencies.
- Candidate: `95a53b135cb02b0a93db533df3eb48b773e57744`, tree `f500373dfea1ba764d888202752120cb506f9eb7`.
- Both commits were clean before and after their release build. Probe sources, probe Cargo manifest, toolchain, Cargo configuration and release recipe match. Both builds use one physical source/target path and the committed path-remapped release recipe.
- Host: 11th Gen Intel(R) Core(TM) i7-11850H @ 2.50GHz; 16 visible logical CPUs with a shared four-CPU cgroup quota (`cpu.max: 400000 100000`); 30.951 GiB reported Linux memory. The local cgroup memory limit was `max` (no local ceiling). These are shared runner limits, not per-probe allocations or a claim about ancestor limits. CPU frequency policy was not recorded. All host observations are retained in the suite.
- Recorded tools: Rust/Cargo 1.97.1, Heaptrack/heaptrack_print 1.4.0 and zstd 1.5.4.
- Kernel: `Linux 0db06bb1a2d4 6.6.87.2-microsoft-standard-WSL2 #1 SMP PREEMPT_DYNAMIC Thu Jun  5 18:30:46 UTC 2025 x86_64 GNU/Linux`.
- Virtualization: WSL detected `True`, Docker marker `True`. These are container/WSL2 Linux measurements, not bare-metal Linux or a Docker/Kubernetes application comparison.
- Seven alternating control/candidate pairs; three sizes; three operations; normal and separately profiled processes: **252 successful measured processes**, with no discarded runs. All probe identities, zero exit statuses, launcher reaping and owned worktree removal replay successfully.
- Small component: 24,641 bytes. The other components are exactly 16 MiB and 64 MiB, produced with legal custom-section padding and validated before measurement. Padding exercises byte-size costs; it does not simulate a larger application instruction graph.
- Each fixture contains one published release, one deployment and two routes. This is not the 100,000-registration catalog-memory test.

## Normal timing and CPU

Each table entry is the median of seven independent process samples. Hash timing divides each measured batch by its declared hash count; repository operations run once. The aggregate retains every sample distribution and paired candidate-minus-control distribution. Percent reductions below compare the two medians. Seven-sample maxima/p99 are not invocation-tail latency estimates.

| Component | Operation | Control wall ms/op | Candidate wall ms/op | Wall reduction | Control process CPU ms | Candidate process CPU ms |
|---|---|---:|---:|---:|---:|---:|
| small | Byte-slice SHA-256 | 0.085 | 0.014 | 83.6% | 234.294 | 39.961 |
| small | Artifact recovery | 6.061 | 4.618 | 23.8% | 3.314 | 2.846 |
| small | Artifact + catalog open/compile | 9.071 | 7.512 | 17.2% | 4.771 | 4.052 |
| 16m | Byte-slice SHA-256 | 62.147 | 10.312 | 83.4% | 262.657 | 53.678 |
| 16m | Artifact recovery | 84.590 | 22.392 | 73.5% | 78.780 | 15.974 |
| 16m | Artifact + catalog open/compile | 220.339 | 33.652 | 84.7% | 213.854 | 29.783 |
| 64m | Byte-slice SHA-256 | 261.902 | 39.543 | 84.9% | 296.590 | 75.967 |
| 64m | Artifact recovery | 309.282 | 53.012 | 82.9% | 296.405 | 48.752 |
| 64m | Artifact + catalog open/compile | 860.842 | 103.637 | 88.0% | 841.433 | 99.858 |

Hash input file reads occur before its operation timer. Catalog timing includes artifact recovery followed by deployment open/compilation. Output identity/routing oracles and the 100 ms live observation hold occur after every operation timer. CPU is separately observed whole-process user plus system time, including startup, input reads, checks and cleanup; it is not isolated operation CPU. The small, 16 MiB and 64 MiB hash processes perform 2,723, four and one hashes respectively. Their CPU columns cover those entire batches, while the wall columns are normalized per hash.

Every fixture receives a sequential 64 KiB read before each child. These are best-effort warm filesystem observations; no OS cache flush or cold-disk claim is made.

## Peak memory and allocations

Heaptrack peaks come from separate instrumented processes and represent exact whole-process live heap bytes. Normal VmHWM comes from the actual uninstrumented probe while still alive. RSS includes mappings, libraries, stack and input buffers; heap and RSS are distinct measures. Table entries are medians of seven process peaks.

| Component | Operation | Control heap peak MiB | Candidate heap peak MiB | Control normal VmHWM MiB | Candidate normal VmHWM MiB |
|---|---|---:|---:|---:|---:|
| small | Byte-slice SHA-256 | 0.122 | 0.101 | 3.250 | 3.000 |
| small | Artifact recovery | 0.161 | 0.120 | 3.875 | 3.875 |
| small | Artifact + catalog open/compile | 0.223 | 0.202 | 4.375 | 4.375 |
| 16m | Byte-slice SHA-256 | 32.075 | 16.077 | 35.207 | 19.000 |
| 16m | Artifact recovery | 32.114 | 0.120 | 35.875 | 3.875 |
| 16m | Artifact + catalog open/compile | 32.176 | 0.202 | 36.141 | 4.375 |
| 64m | Byte-slice SHA-256 | 128.075 | 64.077 | 131.000 | 67.125 |
| 64m | Artifact recovery | 128.114 | 0.120 | 131.750 | 3.875 |
| 64m | Artifact + catalog open/compile | 128.176 | 0.202 | 132.230 | 4.250 |

For both 16 MiB and 64 MiB fixtures, the candidate artifact-recovery heap peak was exactly 126,229 bytes and the combined catalog-open heap peak was 212,164 bytes in all seven profiled repetitions. These observations show no artifact-size-proportional recovery heap growth for the selected fixtures; direct hashing still retains its input buffer.

The aggregate also retains total allocations, total allocated bytes, sampled RSS and completion RSS. Heaptrack remaining allocations are unsuppressed process-exit counters, not automatic leak findings. The fixed 64 KiB verifier scratch is stack storage and is therefore outside the heap-allocation counter.

Offline replay parses the retained interpreted Heaptrack stream and cross-checks exact allocation/peak totals against complete folded profiles. Folded profiles are losslessly compressed with a bounded 64 MiB expansion limit. The compressed original Heaptrack trace and successful zstd helper receipt are retained as provenance; offline Python replay does not independently decompress that zstd file.

## Validation and limits

- 179 focused Rust tests passed across artifact storage, catalog compilation and benchmark probes; one existing heavy test stayed ignored. Corruption, size limits, interrupted/truncated/growing streams, generic repository fallback, release association, publication gates and unchanged routing/recovery all pass.
- 57 focused Python tests passed on Linux, including owned-process failure/timeout cleanup, complete population, rehashed evidence tampering, exact allocation replay and bounded profile decompression. All 34 archive tests passed.
- The first smoke completed all 12 operations but exposed a 16 MiB folded-text replay limit. Its raw output is preserved; the corrected bounded parser replays it. The second smoke passed collection and replay with compressed profiles. The full comparison uses only the final complete run.
- This ticket measures identity verification and one-release catalog recovery. Warm invocation, cold compilation scheduling, request budgets, 100k catalog footprint and infrastructure density remain separate extension tickets. No end-to-end latency target is claimed from these microbenchmarks.

## Retained evidence

The historical package contained the actual binaries, shared fixtures, every process receipt, raw logs and allocation profiles. Its manifest, checksum and aggregate remain in this checkout. After restoring that package, replay without executing its binaries:

```sh
python3 tools/validate_phase1_archive.py "${restored_root}/benchmarks/optimization/artifact-identity/2026-09-08-container-linux-95a53b1"
```
