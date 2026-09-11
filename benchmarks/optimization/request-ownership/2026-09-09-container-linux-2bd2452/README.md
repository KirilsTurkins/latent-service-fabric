# Request ownership: earlier release with an observed warm-RPC cost

Historical raw archive payloads are omitted from this checkout. Results and
original validation records remain; recorded replay passes describe publication
checks. [Restore the exact historical package](../../../../docs/testing/benchmark-retention.md) before running raw
replay or extraction commands below. Set `restored_root` to its fresh restore
directory; manifests alone do not make the current directory replayable.

[#104](https://github.com/KirilsTurkins/latent-service-fabric/issues/104) is accepted
as a memory and ownership tradeoff. The candidate releases the raw input vector
before guest dispatch and avoids copying the full invocation context. Actual
pending-future proofs show 65,536 B of live raw-vector capacity in the control
and zero in the candidate while the guest Store remains live. Near-limit context
setup improves in all seven normal pairs, and separately profiled whole-process
allocated bytes decrease.

**Warm-RPC performance remains an unresolved cost.** Across the primary campaign
and one predeclared replication, warm Echo's median paired p50 increases by
**37.451 us**, with **9/14 pairs higher**. Its observed server CPU totals increase
from **4.18 s to 4.42 s (+5.7%)**. The larger-payload timing changes reverse in the
replication; this does not establish equivalence or eliminate the original
regression. The retained concern carries into
[#105](https://github.com/KirilsTurkins/latent-service-fabric/issues/105) and
[#106](https://github.com/KirilsTurkins/latent-service-fabric/issues/106).
This report makes no general RPC speedup, CPU, RSS or whole-process peak-heap
improvement claim. Selected constructor/poll allocation attribution is
**unavailable in all 12 profiles**.

The primary [RPC aggregate](rpc/aggregate.json),
[direct backend aggregate](backend/aggregate.json), and additive
[RPC replication aggregate](rpc-diagnostic/aggregate.json) retain separate
populations. [Detailed analysis](analysis.md) supplies all process quantiles,
paired directions, construction/setup/reclamation measurements and execution-order
strata. Every original raw call, profile, executable, input and ownership receipt
remains in its corresponding archive.

## Sources and measurement boundaries

| Role | Exact measured source |
| --- | --- |
| Control | `1f01544586fccee29da3423133928324ea2b0a5f` |
| Candidate and executed harness | `2bd245269ae113600f591492d2780ac4bc4467ed` |

Both arms include the prepared cache and bounded transport cleanup. The common
collectors, observer, input generators, external client/CLI, lockfile and build
recipe are byte-identical across the controlled sources. Candidate production
changes consume the validated context with bounded capacity normalization,
release request/raw-input ownership earlier, borrow sorted function lookups and
avoid temporary import collections. No cache, deadline, payload or engine policy
is changed to make these measurements succeed. The later CLI display-only fix
at `2372c6bc36f2ad6a69d3de558e40f691db046335` changes the printed ownership count after successful replay; it does
not relabel the measured binaries or alter raw data or semantic validation.

The build uses Rust/Cargo 1.97.1, Wasmtime 47.0.3 and the pinned release recipe:
optimization level 3, 16 codegen units, no LTO, debug information retained, panic
unwind, no stripping, and recorded path remapping. The host is an Intel
Core i7-11850H with 16 logical CPUs, Linux 6.6.87.2 under WSL2/Docker, with a
4-CPU cgroup quota (`400000 100000`), effective CPU set `0-15`, no configured
cgroup memory maximum and 33,233,743,872 B reported host memory. Normal allocator
overrides are unset. Heaptrack 1.4 runs only in the separate allocation children.

The three external cases use actual loopback RPC with the unchanged client.
Each arm has four cells and 64 queue slots; prepared-cache entries and total
preparations are four, with two compiler workers. All three cases share one
measurement server per arm, in fixed order. Direct calls instead use one actual
Wasmtime factory per child, without a node, listener or RPC. Large direct
contexts exceed ordinary RPC metadata limits and are not represented as remotely
accepted inputs. Their outputs validate the exposed metadata, claims, baggage,
identity, deadline and remaining-budget projection.

| Population | Pairs / children | Retained calls | Timing denominator |
| --- | --- | ---: | --- |
| Primary external RPC | 7 pairs; 70 seed/server/client owners | 12,936 | Per arm: 2,800 warm Echo, 2,800 64 KiB, 280 near-limit measured calls; 588 warmups |
| RPC replication | Same 7-pair plan and binaries; 70 owners | 12,936 | Same independent per-arm populations |
| Normal direct | 7 pairs; 14 children | 3,052 | Per shape/arm: seven distributions of 32 measured calls; four warmups per shape/child; two proofs per child |
| Separate allocation | 1 pair per shape; 12 children | 108 | One warmup plus eight measured calls per child; no proofs |

The original full population is 16,096 calls; the additive replication brings
published calls to 29,032. Smoke retains 164 calls. Context-fixture generation
runs once on the control: one actual capabilities preparation, at most 20
host-only charge checks, zero Invokes/guest Stores, and actual factory joins.
Its frozen near-limit context has 512-1,024 B validated headroom with fixed-width
call IDs. The candidate uses those exact inputs. Normal direct children prepare
three maintained components once each; allocation children prepare only the
selected component. There is no hidden prewarm Invoke; the first external
warmup includes cold preparation.

## RPC results, including the replication

All 25,872 external offers succeeded with matching identity, payload and media,
and no nominal-deadline overshoot. Each campaign preserves seven alternating
pairs. The replication followed a predeclared 60 s period without owned
build/test/profiler/archive jobs, using the same exact binaries and protocol in
a fresh output root. This does not establish thermal or shared-host isolation.
No campaign, pair, offer or tail is removed.

Each arm value below is a median of process-level p50 values. The paired change
is the median of candidate-minus-control differences within matched pairs;
it is not the difference between arm medians. Combined statistics use all 14
pairs across the two campaigns, without pooling individual calls.

| Case | Primary paired delta p50, us | Replication paired delta p50, us | Combined control -> candidate p50, ms | Combined paired delta p50, us | Higher / 14 |
| --- | ---: | ---: | --- | ---: | ---: |
| Warm Echo | +50.9345 | +23.9675 | 0.6027605 -> 0.6301945 | +37.451 | 9 |
| 64 KiB payload | +129.5835 | -61.7425 | 1.04741775 -> 1.082378 | +85.55275 | 8 |
| Near-limit payload | +148.663 | -178.9875 | 1.56256275 -> 1.629616 | +61.82325 | 8 |

| Case | Combined paired delta p95, us | Combined paired delta p99, us | All-offered paired delta p99, us | Paired successful responses/s change |
| --- | ---: | ---: | ---: | ---: |
| Warm Echo | +46.2925 | +41.207 | +39.563 | -38.381890 |
| 64 KiB payload | +94.2995 | +101.714 | +176.8725 | -52.240621 |
| Near-limit payload | +37.1185 | -32.068 | -9.0755 | -17.264726 |

Warm p95 is higher in 11/14 pairs. Near-limit p99 has seven lower and seven
higher pairs, despite its negative median paired change. Successful latency
starts at actual dispatch; all-offered elapsed starts at the scheduled offer
and includes producer delay. Throughput spans the first scheduled measured
offer through the last completion. Warmups remain retained but outside these
latency distributions.

The order strata do not remove the warm concern: combined warm p50 changes are
+57.3 us in eight control-first pairs and +16.89625 us in six candidate-first
pairs. Larger-payload results vary materially by campaign and order; their
complete strata remain in the analysis. Across both campaigns, all-case observed
server CPU is 11.34 -> 11.90 s (+4.9%), and client CPU is 6.32 -> 6.60 s. The
warm-only server totals above are 4.18 -> 4.42 s. These are batch observation
windows including warmup and observation work, at 100 ticks/s, not measured-call
CPU. All 84 batch cgroup windows show zero additional throttling events/time.
Frequency, migration, allocator state and host/VM scheduling are not isolated,
and no retained observation establishes the cause of the regression.

Combined median paired sampled-server RSS changes are -122,880 B, -176,128 B
and -98,304 B for the three cases. These are observed batch maxima on shared
server processes, not continuously observed peaks or a general memory saving.
They must not be summed across cases or equated with raw-vector capacity.

## Direct calls and ownership

All 3,160 direct calls are accounted for: 3,132 successes, 14 acknowledged
cancellations with reusable disposition, and 14 explicit pending-future drops
with no fabricated return value or timing. Normal timing excludes these proof
calls and all separately profiled calls.

The table reports full direct-call arm p50 medians and paired differences in
microseconds, based on seven independent 32-call distributions per shape/arm.
Full call includes request/future construction through contained report and
future destruction. Setup is its actual backend stage and excludes outer context
validation. Moving destruction before guest dispatch also moves that work into
the setup interval; a setup change is not a pure context-builder measurement.

| Shape | Full call p50 control -> candidate, us | Paired full-call delta p50, us | Paired full-call delta p95, us | Paired setup delta p50, us |
| --- | --- | ---: | ---: | ---: |
| Warm Echo | 69.1235 -> 82.121 | +10.358 | -22.171 | +3 |
| 64 KiB payload | 185.8405 -> 186.2975 | +0.4225 | -13.315 | +1 |
| Near-limit payload | 284.1985 -> 292.5615 | +8.7575 | +6.770 | +8 |
| Small context | 122.7495 -> 98.3135 | -9.469 | -88.710 | -2 |
| 64 KiB context | 116.108 -> 111.337 | -2.531 | -0.647 | -1 |
| Near-limit context | 154.405 -> 125.3155 | -30.9185 | +40.561 | -20 |

Near-limit context setup p50 changes from 53.5 to 33.5 us, with a -20 us paired
median and all seven pairs lower. Its setup p95 paired change is -25 us, lower
in six pairs. Its full-call p95 nevertheless increases in four pairs. Direct
payload timing and request-construction/reclamation spans remain mixed.

Every one of the 28 proofs observes actual guest dispatch followed by `Pending`,
with a live invocation, Store, HostState and component instance. All 14 control
proofs retain one raw vector with 65,536 B capacity at that observation. All 14
candidate proofs have zero live raw owners/capacity because actual destruction
precedes `BeforeCallExport` and guest dispatch. This observes ownership and
polling state, not an executed-instruction count. Seven proofs per arm then
cancel through acknowledgement; seven destroy the pending future directly.
Both arms finish with zero live raw owners and capacity, with no observer loss.
The ordinary timing/profile calls keep this detailed observer disabled.

Every direct child joins both compiler workers and finishes with no live native
owner, preparation reservation or resident/evicted-live/unpublished compiled
runtime charge. The actual Heaptrack probe and its wrapper have separate PID
identities and ownership receipts. Both RPC campaigns retain clean node
shutdowns, joined compiler/cleanup owners, full cell recovery, actual process
exit/reap and data-directory removal. The direct drop proof itself is not a
standalone cell-reuse measurement; a separate actual supervised-RPC regression
covers that boundary.

Normal direct process CPU includes preparation, validation, warmup, measured
calls, proofs and holds. Its median paired change is -6.598 ms (four pairs
lower), while total CPU across seven children rises from 1.473127 to 1.550678 s.
Median paired observed RSS and kernel high-water RSS both increase by 286,720 B.
These results cannot establish a general CPU or RSS improvement.

## Allocation evidence and its limit

These are complete **whole-process** Heaptrack totals from one independent pair
per shape, including its preparation, nine calls, evidence writing and runtime
lifetime. They are not per-invocation totals and must not be divided by nine to
claim attributed invocation savings.

| Shape | Allocation count control -> candidate | Allocated bytes control -> candidate | Difference, B | Peak live bytes control -> candidate |
| --- | --- | --- | ---: | --- |
| Warm Echo | 57,869 -> 57,645 | 28,952,933 -> 28,935,295 | -17,638 | 2,780,262 -> 2,780,270 |
| 64 KiB payload | 57,855 -> 57,631 | 33,669,084 -> 33,651,463 | -17,621 | 2,780,270 -> 2,780,278 |
| Near-limit payload | 57,855 -> 57,631 | 37,568,816 -> 37,551,173 | -17,643 | 2,780,298 -> 2,780,306 |
| Small context | 87,174 -> 86,932 | 45,679,032 -> 45,659,437 | -19,595 | 3,087,092 -> 3,087,100 |
| 64 KiB context | 87,165 -> 86,923 | 47,246,451 -> 46,638,169 | -608,282 | 3,087,084 -> 3,087,092 |
| Near-limit context | 87,167 -> 86,925 | 56,586,847 -> 52,129,471 | -4,457,376 | 3,087,112 -> 3,087,120 |

Peak live heap increases by 8 B in every pair. All profiles end with the same
423 tracked allocations / 63,364 B; this process-level accounting is distinct
from the separately verified zero backend-owner gauges. One pair per shape
provides no distribution or repeatability claim for allocation totals.

Both exact constructor/poll symbols have retained raw and demangled `nm`
address/type proofs, but Wasmtime fiber ancestry leaves 36 allocation records
unresolved in each payload profile and 882 in each context profile. Therefore
all 12 selected-frame results are **unavailable**, with null counts, allocated
bytes, simultaneous peaks and remaining bytes. Partial named-frame observations
are not complete attribution, and unavailable is not zero. Whole-process
allocated-byte reductions and actual raw-vector release remain valid distinct
observations; a complete invocation-only allocation reduction is not established.

## Reproduction, archives and checks

Use a clean checkout at the measured harness SHA for new collection. The
[current method](../../../../docs/testing/phase-1-measurements.md#request-ownership-experiments)
explains finite output bounds, source checks and cleanup. Existing destinations
must not be reused. The actual build took 463.901053776 s; primary RPC/direct
collection took 37.968771894 / 80.193634631 s, and RPC replication took
35.674141699 s. These are separate stage times and exclude other setup,
packaging and the predeclared idle interval.

```sh
set -eu
export CONTROL_REF=1f01544586fccee29da3423133928324ea2b0a5f
export CANDIDATE_REF=2bd245269ae113600f591492d2780ac4bc4467ed
export HARNESS_REF="$CANDIDATE_REF"
export OWNERSHIP_ROOT=/workspace/project/target/optimization-ownership-reproduction
python3 tools/run_optimization_revision_benchmarks.py --experiment ownership \
  --profile full --build-only --control-ref "$CONTROL_REF" \
  --candidate-ref "$CANDIDATE_REF" --harness-ref "$HARNESS_REF" \
  --target-root /workspace/optimization-ownership-builds \
  --output "$OWNERSHIP_ROOT/build-only-rpc" \
  --backend-build-output "$OWNERSHIP_ROOT/build-only-backend"
python3 - <<'PY'
import os, shutil
from pathlib import Path
root = Path(os.environ['OWNERSHIP_ROOT'])
for kind in ('rpc', 'backend'):
    for profile in ('smoke', 'full'):
        shutil.copytree(root / ('build-only-' + kind), root / (kind + '-' + profile))
shutil.copytree(root / 'build-only-rpc', root / 'rpc-diagnostic')
PY
for profile in smoke full; do
  python3 tools/run_optimization_revision_benchmarks.py --experiment ownership \
    --profile "$profile" --builds "$OWNERSHIP_ROOT/rpc-$profile/revision-builds.json" \
    --target-root /workspace/optimization-ownership-data
  python3 tools/run_optimization_backend_revision.py --experiment ownership \
    --profile "$profile" --builds "$OWNERSHIP_ROOT/backend-$profile/backend-builds.json" \
    --target-root /workspace/optimization-ownership-data
done
# For the declared additional RPC campaign, first end owned background jobs.
sleep 60
python3 tools/run_optimization_revision_benchmarks.py --experiment ownership \
  --profile full --builds "$OWNERSHIP_ROOT/rpc-diagnostic/revision-builds.json" \
  --target-root /workspace/optimization-ownership-data
```

Copy build-only directories before any measurements; never copy a completed
smoke root. Collection uses independent 7,200 s stage deadlines, excluding build.
Build commands are at most 3,600 s, normal children 90 s, allocation children
180 s and extraction tools 120 s, clipped to remaining stage time. The measured
harness's ownership validator printed the wrong count key after successful
standalone semantic replay; the display-only fix permits the current CLI to
finish normally. Canonical function replay of the measured suites already
passed, and all publication replays use the corrected CLI or archive validator.

The three packages use bounded split transport; the hashes below identify each
logical concatenated gzip archive. Every package passed mandatory full semantic
replay during Linux packaging and independent full Windows replay. Replay reads
retained data and does not execute retained binaries.

| Package / manifest | Files | Expanded bytes | Logical gzip bytes / parts | SHA-256 |
| --- | ---: | ---: | --- | --- |
| [rpc](rpc/raw-evidence.manifest.json) | 1,395 | 473,013,590 | 104,007,239 / 3 | `e97184d6bf6dbe4a5a606f1d41d67fe4bba981b168d9bdf044e553fa8107e8c0` |
| [backend](backend/raw-evidence.manifest.json) | 721 | 603,025,717 | 148,988,050 / 3 | `ccee2d914729d1490d689635202eb5773c04fe2a6bacd6887c9bdff1de7d3ed7` |
| [rpc-diagnostic](rpc-diagnostic/raw-evidence.manifest.json) | 1,395 | 473,012,101 | 104,005,362 / 3 | `41a3e4c26ccb411018e2bee47181f6cb5ec2d3934e735c80ade94f798f7113b9` |

```sh
for package in rpc backend rpc-diagnostic; do
  python3 tools/validate_phase1_archive.py \
    "${restored_root}/benchmarks/optimization/request-ownership/2026-09-09-container-linux-2bd2452/$package"
done
# To package fresh qualified full roots, use a new publication directory:
python3 tools/package_phase1_evidence.py --source "$OWNERSHIP_ROOT/rpc-full" \
  --output "$OWNERSHIP_ROOT/publication/rpc" --compression-level 9 --split-archive
python3 tools/package_phase1_evidence.py --source "$OWNERSHIP_ROOT/backend-full" \
  --output "$OWNERSHIP_ROOT/publication/backend" --compression-level 9 --split-archive
python3 tools/package_phase1_evidence.py --source "$OWNERSHIP_ROOT/rpc-diagnostic" \
  --output "$OWNERSHIP_ROOT/publication/rpc-diagnostic" --compression-level 9 --split-archive
```

Before publication, 303 distinct affected Rust checks passed: 250 Wasmtime/wire
checks, 52 actual native-fixture checks and the actual supervised RPC ownership
regression. The existing cross-tenant check was also rerun. Full Python discovery
passed 695 tests at measured `2bd2452`; the later display-only CLI change passed
five focused tests. These counts are separate; no unperformed full 700-test
local run is implied. Source/fixture and replay checks reject crossed identities,
erased ownership events, invalid outputs, unresolved-as-zero attribution and
inconsistent artifact/aggregate data.

Earlier failed attempts remain in local ignored development diagnostics. Debug
functional attempts 01/02 stopped before preparation because the debug binary
exceeded the inherited helper fingerprint bound; subsequent debug runs use an
explicit bounded debug launcher and do not qualify as release evidence. The
first release backend smoke completed its first allocation collector/profiler
but failed compression at the inherited 64 MiB folded-stream bound: the actual
stream was 93,464,548 B. The common ownership harness then declared 128 MiB,
with matching collection/compression/replay and unchanged historical defaults,
line/row/stack/file/root bounds. Fresh exact-source builds and smoke/full roots
produced the published results. The later standalone validator display failure
after successful semantic replay is preserved too; it did not require changing
or rerunning the successful measurement. Unresolved fiber attribution is an
explicit limitation of these complete profiles, not a failed profile discarded
from the population. Original optimization archives and earlier ticket results
remain unchanged.
