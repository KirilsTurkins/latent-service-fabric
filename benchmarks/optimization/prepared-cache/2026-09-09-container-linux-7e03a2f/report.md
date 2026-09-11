# Prepared-cache lookup and runtime ownership

Historical raw archive payloads are omitted from this checkout. Results and
original validation records remain; recorded replay passes describe publication
checks. [Restore the exact historical package](../../../../docs/testing/benchmark-retention.md) before running raw
replay or extraction commands below. Set `restored_root` to its fresh restore
directory; manifests alone do not make the current directory replayable.

The [#102 comparison](https://github.com/KirilsTurkins/latent-service-fabric/issues/102) completed both full populations. Candidate cache lookup used less elapsed time and actual thread CPU in **41 of 42 normal process pairs**. Separately profiled hits changed from **one allocation / 14 bytes per get to zero**, with verified attribution in every profiled process. The real-node experiment confirmed resident versus evicted-but-still-owned runtime accounting and final retirement. Its warm baseline improved slightly, while churn latency was mixed and observed node RSS increased slightly.

These are two distinct experiments: [lookup results](lookup/aggregate.json) measure the actual generic cache with tagged values; [behavior results](behavior/aggregate.json) exercise compiled Echo components through a real node and RPC client. The lookup results do not establish allocation-free complete invocations, and neither experiment establishes a general RSS reduction or a production SLO.

## Sources, controls and populations

The clean control is `654efbefcadb2314e69875ad058bdec919a1aaea`; candidate and collection harness are `7e03a2fafe1d3b2e42546140c8c22113a6998638`. Both exact commits were built without overlays at the same owned physical source/target paths. All 81 retained common build/collector inputs match by hash and length across both arms and the harness. Source checks before and after building/collection and owned build-directory cleanup passed. Product cache implementation and runtime/error cleanup ordering are the declared treatment.

| Experiment | Full population | Measured work |
| --- | --- | --- |
| Cache lookup | 3 capacities × 2 traces × 2 modes × 2 arms × 7 repetitions = **168 probe processes** | 128 warmup and 16,384 measured gets per process: **21,504 warmup and 2,752,512 measured gets** |
| Node behavior | **7 alternating pairs / 14 node processes** | 802 RPC offers and 1,617 counted commands per process: **11,228 offers / 22,638 commands**, plus **14 direct executions** |

Order alternates by repetition. Lookup normal and Heaptrack modes each have 84 processes; profiler/tool helper processes are additional to the 168 probes. All planned children and offers are retained, including intentional failures. Every measured child has a unique bound PID/start identity, successful exit, closed output and parent reap receipt.

Actual builds use rustc/Cargo 1.97.1, Wasmtime 47.0.3 and `x86_64-unknown-linux-gnu`: release optimization 3, debug 1, 16 codegen units, no LTO or incremental compilation, unwind panics and no stripping, with matched path remapping. Both use Cargo.lock SHA-256 `37e33344e6c4017bd68e70e676a8a99d440fcedcc5688965f13169a2a16536e5`. Exact executable, component, recipe and source identities are retained in each archive.

The host is an Intel i7-11850H under Docker/Linux on WSL2 kernel 6.6.87.2, with 16 visible logical CPUs and 33,233,743,872 B visible memory. The resolved shared runner cgroup has `cpu.max = 400000 100000` (four CPU-equivalents of quota), cpuset `0-15` and `memory.max = max`. This does not provide exclusive physical cores or native-Linux calibration. `LD_PRELOAD` and `MALLOC_CONF` are unset. Heaptrack/heaptrack_print are 1.4.0, GNU nm is 2.40 and zstd is 1.5.4.

All table arm values below are medians of seven process summaries. **Paired delta** means the median of seven within-pair candidate minus control differences; it need not equal subtraction of the displayed arm medians. Lower-pair counts describe the observed repetitions, not statistical significance.

## Actual cache lookup

The identical `cache::measurement::cache_lookup_collector` prepopulates a real `PreparedCache<u16>` at capacities 4, 64 and 4,096. It uses an MRU-hot trace and a seeded-uniform trace with seed `0x4c53464341434845`; replay regenerates every retained little-endian u16 trace. Entries have fixed-length keys and synthetic source/metadata/image costs of 2/3/4. Capacity 4,096 means tagged cache entries, not 4,096 compiled components or guest instances.

The non-inlined `latent_wasmtime::cache::measurement::measured_cache_hits` frame includes cache get/promotion, returned `Arc` handling/drop, writes into a preallocated tag array and checksum accumulation. Construction, key/trace generation, warmup, verification, resource probes and the two 100 ms observation holds are outside the measured batch. Every tag, checksum, occupancy and hit delta matches; there are no measured misses, evictions or invalidations.

Values below are **ns/get batch averages**, not individually timed hits or per-hit tail percentiles. Thread CPU uses actual `CLOCK_THREAD_CPUTIME_ID` readings, bound to the same PID/TID/start identity, with reported 1 ns resolution. Its bracket also encloses the elapsed-clock reads. Coarse task ticks and whole-child CPU remain separately labeled in the evidence.

| Entries / trace | Elapsed control | Elapsed candidate | Paired elapsed delta | CPU control | CPU candidate | Paired CPU delta | Lower pairs, elapsed / CPU |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 / hot | 83.26 | 47.19 | −46.43 | 83.48 | 47.68 | −46.74 | 7/7 / 7/7 |
| 4 / uniform | 79.54 | 39.99 | −23.23 | 79.75 | 40.21 | −23.21 | 6/7 / 6/7 |
| 64 / hot | 177.09 | 45.24 | −149.82 | 177.32 | 45.53 | −149.86 | 7/7 / 7/7 |
| 64 / uniform | 136.11 | 40.63 | −91.24 | 136.35 | 40.83 | −91.36 | 7/7 / 7/7 |
| 4,096 / hot | 7,952.79 | 41.13 | −7,919.66 | 7,952.18 | 41.46 | −7,919.21 | 7/7 / 7/7 |
| 4,096 / uniform | 4,970.03 | 106.89 | −4,871.98 | 4,967.65 | 107.12 | −4,869.35 | 7/7 / 7/7 |

The retained regression is repetition 3 at capacity 4/uniform: 76.25 → 86.87 ns/get (+13.92%). At capacity 4,096/hot, seven process elapsed averages range from 7,639.39–10,773.82 ns/get control and 31.28–107.89 ns/get candidate. These results support removing the promotion scan; the candidate uniform trace still costs more at 4,096 entries than at 4 or 64. Expected O(1) algorithmic work does not imply equal hardware cost at every capacity.

### Separately profiled allocations and memory

Every profiled control batch attributes 16,384 allocations / 229,376 B to the measured frame; every candidate batch attributes zero. Across 42 profiled processes per arm this is **688,128 allocations / 9,633,792 B → 0 / 0**, or **1 allocation / 14 B → 0 / 0 per measured get**. All 84 attribution results are available with zero unresolved allocation frames.

Raw and demangled nm output from the exact executable are associated by code address and symbol type. Attribution recognizes the verified Rust v0 name and demangled name in the selected probe module; interpreted records and folded stacks, including their actual source-file suffixes, agree. Missing, crossed or unresolved proof is unavailable, not inferred zero. Complete profiles and tool receipts remain archived.

Whole profiled-process allocation counts and allocated bytes decrease in all 42 pairs, but these include setup and warmup. Peak live allocator bytes increase at small capacities and decrease at 4,096:

| Entries / trace | Peak live bytes, control | Candidate | Paired delta |
| --- | ---: | ---: | ---: |
| 4 / hot | 193,672 | 193,764 | +92 B |
| 4 / uniform | 193,686 | 193,778 | +92 B |
| 64 / hot | 207,738 | 208,549 | +811 B |
| 64 / uniform | 207,752 | 208,564 | +812 B |
| 4,096 / hot | 1,243,363 | 1,200,461 | −42,902 B |
| 4,096 / uniform | 1,243,377 | 1,200,476 | −42,901 B |

Every process has three remaining allocations / 928 B at exit in both arms; this is not a zero-leak result. Normal completion RSS and kernel high-water RSS match in all 84 normal processes, with two threads and three FDs. RSS differences are mixed: at 4,096/hot the median paired difference is **+148 KiB**, and at 4,096/uniform **+20 KiB**, despite lower profiled heap peaks. Profiled timings/RSS are not substituted for normal performance.

## Five components in four cache slots

Both arms run the common `standalone::measurements::comparison::cache::phase1_cache_collector`: an actual `StandaloneNode`, bound loopback RPC transport and persistent client on a separate runtime in the same libtest process. This differs from the separate-process external client in the [warm-activation comparison](../../warm-activation/2026-09-08-container-linux-56303c5/REPORT.md); it includes common node/client/libtest overhead.

Both configure four cells, queue 64, four admitted preparation jobs, two compiler workers, two invocation workers, four control workers, two client workers and four cache entries. Source/metadata/image cache ceilings are 128/64/512 MiB. Invocation grants are 10 billion fuel, 16 MiB memory, 1,000 ms wall and 16 KiB logs. Both use on-demand allocation, COW, fuel async yield interval 10,000, hostcall transfer fuel 131,072 and Wasm/async stack ceilings 512 KiB/2 MiB.

K0–K4 are actual Echo components distinguished by inert custom sections. K5 is an eight-byte empty Component with retained Echo declarations, intentionally rejected as `incompatible-contract` during preparation surface validation. Six publication/application pairs establish route generation 6. The typed Echo text is `phase0 targeted warm echo` (25 bytes).

| Phase | Offers per process | Offers per arm over seven processes | Component compilations per arm |
| --- | ---: | ---: | ---: |
| Warmup, excluded | 40 | 280 | 7 |
| Resident K0 baseline | 400 | 2,800 | 0 |
| Round-robin warmup, excluded | 5 | 35 | 28 |
| K0–K4 round-robin | 100 | 700 | 700 |
| Locality warmup, excluded | 10 | 70 | 35 |
| K0,K0,K1,K1,…,K4,K4 locality | 100 | 700 | 350 |
| Held ownership / failed refill | 7 | 49 | 49 |
| Concurrent warm/cold | 132 | 924 | 28 |
| Healthy recovery | 8 | 56 | 0 |
| **Total** | **802** | **5,614** | **1,197** |

Each arm has **5,607 successful RPCs and seven intentional incompatible-contract rejections**. Every other failure class is zero, including transport failure, timeout, client overload, undispatched expiry, declared error and invalid response. All ordinary successful requests are within budget. The aggregate counts intentional non-successes as budget misses; these fourteen records are not deadline expirations. Every Invoke has a matching retained-status identity and consumption check, with no retries or replacement offers.

Per process, baseline has 400 hits / 0 misses; round-robin 0 hits / 100 misses / 100 evictions; locality 50 hits / 50 misses / 50 evictions; concurrent 128 hits / 4 misses. These match in both arms. The LRU change preserves the eviction behavior: five cyclically accessed components still do not fit in four slots.

### RPC latency and concurrent work

Successful-response latency is dispatch through response observation, conditional on success. Values are milliseconds. Warmups and the functional ownership sequence are excluded; the concurrent row includes only its 128 warm calls per process.

| Population | Control p50 | Candidate p50 | Paired p50 delta | Control p99 | Candidate p99 | Paired p99 delta | Lower p99 pairs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Resident baseline | 0.725 | 0.709 | −0.020 | 1.508 | 1.399 | −0.146 | 5/7 |
| Round-robin | 36.374 | 36.234 | −0.252 | 53.275 | 54.366 | +2.141 | 2/7 |
| Locality | 17.471 | 17.686 | +0.214 | 49.082 | 50.382 | +0.382 | 3/7 |
| Concurrent warm | 0.847 | 0.843 | −0.042 | 1.855 | 1.724 | −0.116 | 5/7 |
| Healthy recovery | 0.871 | 0.987 | +0.166 | 1.757 | 1.612 | +0.078 | 3/7 |

Baseline p50 is lower in 6/7 pairs, with −19.667 µs median paired change (−2.700% median paired percentage). Churn is mixed: round-robin p99 is worse in 5/7 pairs; locality p50 is worse in 6/7. Locality mixes exactly 50 hits and 50 misses, so its median lies between different populations. One candidate locality process has p99 96.599 ms versus a control process-p99 maximum of 53.727 ms. The healthy suffix has only eight calls per process, making p99 its maximum; its median paired p99 change is positive despite lower marginal medians. These observations do not support a general churn speedup.

All-offered elapsed time starts at the scheduled offer and includes producer/dispatch delay. Its p99 values retain that wider boundary:

| Population | Control p99 (ms) | Candidate p99 (ms) | Paired delta (ms) | Lower pairs |
| --- | ---: | ---: | ---: | ---: |
| Resident baseline | 1.512 | 1.404 | −0.144 | 5/7 |
| Round-robin | 53.283 | 54.372 | +2.138 | 2/7 |
| Locality | 49.087 | 50.401 | +0.381 | 3/7 |
| Concurrent warm | 3.492 | 3.394 | −0.228 | 4/7 |
| Healthy recovery | 1.767 | 1.616 | +0.074 | 3/7 |

The concurrent phase schedules 128 warm offers every 2 ms and four cold offers at a 16 ms offset, following a declared 10 ms lead. All 896 warm and 28 cold calls per arm succeed. Actual other-key compilation conservatively overlaps 300/896 control and 285/896 candidate successful warm RPC intervals, with overlap present in every process. This uses actual compilation intervals and clock-offset brackets, not scheduled coincidence. It is not a matched-overlap-population latency comparison or a measurement of individual readiness waits.

### Preparation CPU and observed resources

Every process records 171 component compilations, including the expected surface-validation failure: **2,394 compilation intervals / 16,744 stage records** overall, with none unattributed. All 1,196 stage records per process were exported in contiguous sequence. The final bounded ring contains 256 entries with 940 overwritten entries, without losing archived records.

| Stage | Observations per arm | Median process stage-p50, control → candidate | Summed observed CPU, control → candidate |
| --- | ---: | ---: | ---: |
| Component compilation | 1,197 | 33.525 → 33.629 ms | 40.18 → 40.81 s |
| Whole job | 1,197 | 34.399 → 34.453 ms | 40.47 → 41.20 s |
| Cache adoption | 1,190 | 0.083 → 0.083 ms | 0.04 → 0.17 s |
| Queue wait | 1,197 | 0.079 → 0.077 ms | unavailable |

CPU is actual same-thread user/system ticks at 100 Hz (10 ms quantization), not elapsed time. Zero-tick short stages do not imply zero work; nested stage totals must not be added to whole-job CPU. Median paired process whole-job CPU changes by +0.07 s and component-compilation CPU by +0.05 s. There is no compilation-CPU saving.

There are 21 fixed node-process samples per process, 294 overall, including concurrent-phase samples. They include common client/runtime/libtest overhead and are neither continuous sampling nor kernel high-water measurements.

| Observed resource | Control | Candidate |
| --- | ---: | ---: |
| Median of process maximum observed RSS | 35.586 MiB | 35.715 MiB |
| Largest fixed-sample RSS | 35.641 MiB | 35.953 MiB |
| Threads / tasks | 13 / 13 | 13 / 13 |
| Open FDs, observed range | 23–28 | 23–28 |
| Socket FD references / unique sockets | 8 / 5 | 8 / 5 |
| Listening TCP sockets / descendants | 1 / 0 | 1 / 0 |

Median paired maximum-observed RSS increases by **135,168 B / 0.129 MiB**; six of seven candidate maxima are higher. Sampling can miss transient peaks. Shared cgroup memory also includes other data/file cache and cannot be assigned to these node processes.

## Resident and evicted-live ownership

Each process performs two direct readiness acquisitions, one materialization, one successful contained direct execution returning `Reusable`, and nine explicit releases. Seven releases invalidate resident entries; two find already-absent entries. The direct execution has no invented RPC route or journal receipt.

All seven candidate graphs have the following actual ownership transitions. One runtime has source-associated cost 24,754 B, metadata charge 8,674 B and compiled-image span 101,872 B. Multiple ready/active owners share that unique runtime charge.

| Checkpoint | Ready owners | Active instance permits | Resident runtimes | Evicted-live runtimes | Total live runtimes | Live image span (B) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Two ready owners | 2 | 0 | 1 | 0 | 1 | 101,872 |
| One ready and one active | 1 | 1 | 1 | 0 | 1 | 101,872 |
| Evicted, ready and active held | 1 | 1 | 4 | 1 | 5 | 509,360 |
| Active execution finished, ready held | 1 | 0 | 4 | 1 | 5 | 509,360 |
| New resident and old evicted runtime | 1 | 0 | 4 | 1 | 5 | 509,360 |
| Last old ready owner released | 0 | 0 | 4 | 0 | 4 | 407,488 |
| After final node/factory retirement | 0 | 0 | 0 | 0 | 0 | 0 |

Eviction preserves the held runtime. Recompiling the same release creates a new resident lifetime while the old evicted lifetime stays charged. Dropping its last owner refunds exactly its unique cost, without changing the new resident. The intentional incompatible-surface refill preserves previous resident counts/bytes and leaks no owner. It is not a test of rejection after successful runtime construction; separate invariant tests cover that publication path.

Control unique-runtime accounting is **unavailable**, not measured zero. In every candidate run, the independent final observer reports zero count/source/metadata/image cost for all four populations: live, unpublished, resident and evicted-live. These are ownership charges and Wasmtime image spans, not source-buffer retention, allocator live bytes, RSS or unique physical mappings.

All fourteen shutdowns are clean, with no quarantined cell or transient activation, instance/store, quota, compiler-document or ready reservation. Both compiler workers are quiescent and actually joined, the epoch helper is joined, and client/control/invocation runtime monitors reach zero. Node and parent data removal receipts pass. Telemetry is flushed and still retains 107 bounded history entries before final sink disposal; historical counters are not claimed to be zero.

## Reproduce collection

Use Linux with the pinned build environment and profiler tools described above.
The builder and collectors must execute from the **clean measured harness commit
`7e03a2f`**, because their source identity is checked against the build receipts.
The following example starts from a repository containing both exact refs. All
named reproduction directories must be new. The external build parent avoids
an ancestor Cargo configuration; the builder rejects hidden configuration.

```sh
set -eu
git worktree add --detach /workspace/issue102-harness-reproduction \
  7e03a2fafe1d3b2e42546140c8c22113a6998638
cd /workspace/issue102-harness-reproduction

python3 tools/build_optimization_cache_benchmarks.py --profile full \
  --control-ref 654efbefcadb2314e69875ad058bdec919a1aaea \
  --candidate-ref 7e03a2fafe1d3b2e42546140c8c22113a6998638 \
  --harness-ref 7e03a2fafe1d3b2e42546140c8c22113a6998638 \
  --lookup-output target/issue102-reproduction/build-only/lookup \
  --behavior-output target/issue102-reproduction/build-only/behavior \
  --target-root /workspace/issue102-builds-reproduction

# Copy both build-only graphs before any measurement; copytree refuses reuse.
python3 - <<'PY'
from pathlib import Path
from shutil import copytree

root = Path("target/issue102-reproduction")
targets = [(profile, kind) for profile in ("smoke", "full")
           for kind in ("lookup", "behavior")]
if any((root / profile / kind).exists() or
       (root / profile / kind).is_symlink() for profile, kind in targets):
    raise SystemExit("reproduction output already exists")
for profile, kind in targets:
    copytree(root / "build-only" / kind, root / profile / kind)
PY

python3 tools/run_optimization_cache_lookup.py --profile smoke \
  --builds target/issue102-reproduction/smoke/lookup/cache-builds.json
python3 tools/run_optimization_backend_revision.py --experiment cache --profile smoke \
  --builds target/issue102-reproduction/smoke/behavior/cache-builds.json \
  --target-root /workspace/issue102-owned-data-reproduction

python3 tools/run_optimization_cache_lookup.py --profile full \
  --builds target/issue102-reproduction/full/lookup/cache-builds.json
python3 tools/run_optimization_backend_revision.py --experiment cache --profile full \
  --builds target/issue102-reproduction/full/behavior/cache-builds.json \
  --target-root /workspace/issue102-owned-data-reproduction
```

Run these serially with no other build, test, profiler or benchmark load. Smoke
checks 24 lookup probes and 160 behavior RPC offers; full retains the separate
populations reported above. Each collector writes beside its supplied build
receipt and refuses an already measured directory. Preserve failed attempts;
use a new destination copied from the untouched build-only graph for a retry.

The clean `7e03a2f` collector emits its original derived aggregate. Use the
current publication replayer, including the `ed5a105` compaction change, from a
separate checkout for the compact behavior summary and archive validation.
Write that derived output into fresh publication staging, retaining the original
suite, raw files and original aggregate. A later replayer does not change the
source identity of the executed measurement harness.

## Retained evidence and replay

Both packages passed mandatory Linux packaging/replay and independent Windows archive replay, including all hashes, safe extraction, exact derived aggregate equality, source controls, complete populations and cleanup. Replay does not execute retained binaries. Each package uses explicit split transport; its manifest binds the logical concatenated gzip and every raw member, and its parts index binds ordered part lengths/hashes.

| Package | Archived files | Expanded bytes | Logical gzip bytes | SHA-256 |
| --- | ---: | ---: | ---: | --- |
| [Lookup manifest](lookup/raw-evidence.manifest.json) / [parts](lookup/raw-evidence.parts.json) | 2,252 | 393,577,894 | 78,533,487 | `14bf2fcb9efa2875f7a471e13ec53d3e086a189a1d39b2dc81c83eb89c91b0d9` |
| [Behavior manifest](behavior/raw-evidence.manifest.json) / [parts](behavior/raw-evidence.parts.json) | 731 | 488,293,682 | 100,015,117 | `846d25224ccf5720a0abe38b06f9ade5b0923c3420aa5a3c05bd61d3c1188c87` |

From the repository root:

```sh
python3 tools/validate_phase1_archive.py \
  "${restored_root}/benchmarks/optimization/prepared-cache/2026-09-09-container-linux-7e03a2f/lookup"
python3 tools/validate_phase1_archive.py \
  "${restored_root}/benchmarks/optimization/prepared-cache/2026-09-09-container-linux-7e03a2f/behavior"
```

The historical archives contain exact executables, source/build controls, components and metadata, plans, traces, every original raw result/stage/resource record, profiler records, tool logs and ownership receipts. All failures and outliers remain in the populations. The first official smoke's allocation attribution incorrectly reported zero control allocations because it did not recognize the actual Rust v0 symbol and folded source suffix. Those original diagnostics remain unchanged and are superseded for allocation conclusions by the corrected symbol proof and this fresh full collection.

The original full behavior aggregate was 12,361,740 B because it duplicated raw stage and node arrays. It was preserved in local ignored diagnostics at publication. Publication analysis at `ed5a105` produces a 1,179,332 B aggregate with derived stage/job counts and observed resource summaries; every original raw array is still archived and strictly replayed. This is a derived-output compaction from the unchanged suite, not a workload rerun or a measurement of a later product revision. Original measurements and recorded validation outcomes are unchanged; archive availability follows the retention notice above.
