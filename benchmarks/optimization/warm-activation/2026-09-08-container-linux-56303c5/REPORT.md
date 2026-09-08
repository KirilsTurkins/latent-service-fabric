# Verified warm activation: before/after observations

Recorded 2026-09-08 for [#100](https://github.com/KirilsTurkins/latent-service-fabric/issues/100),
part of the Phase 1 performance extension.

The #100 candidate reduces external warm-echo median latency from **0.888 ms to
0.579 ms** and p99 from **1.854 ms to 1.366 ms** in this container experiment.
Compute and structured transformation also improve. The five-component working
set exceeds the four-entry cache and regresses: median refill-path latency rises
from **34.763 ms to 36.308 ms**, and p99 from **41.936 ms to 54.783 ms**.

The **99% on-time-success target at 2 ms remains unmet**: the candidate completes
2,664 of 2,800 measured offers successfully within the requested budget (95.14%).
At 1 ms neither revision returns a successful result. Passing collection and
semantic replay establish the completeness of these observations, not attainment
of that performance target.

## Evidence and revisions

Two independent full populations passed their collectors and strict suite
replay:

| Evidence | Population | Retained aggregate |
| --- | --- | --- |
| External persistent client | 46,130 offered calls, including warmup; 154 measured/seed server and load-client processes | [external/aggregate.json](external/aggregate.json) |
| Backend diagnostic through real RPC | 6,160 calls, including warmup; 14 independently supervised node/libtest children | [backend/aggregate.json](backend/aggregate.json) |

Both aggregates have `profile: full`, `status: complete`, and true
`population_complete` and `attempt_count_complete` fields. The tables below were
independently recomputed from their per-process observations, rather than copied
from a pooled latency distribution. Each package retains its own suite, raw
observations, exact executed binaries, fixtures, input metadata and source/build
receipts inside a logical `raw-evidence.tar.gz` stream, with a per-file manifest
and SHA-256 sidecar. The external stream is retained as three ordered parts;
the backend stream is one file. External and backend evidence replay separately.

| Role | Exact clean source | Tree |
| --- | --- | --- |
| Control, before verified warm acquisition | `e94c180fdb15d064570c2b90aceacb0d984b847e` | `4f84c0ea308342b6659bf481e65b6dcd2300616e` |
| Candidate | `56303c5b925d55683399bb210812888d998cad5d` | `1e5653de526069a57d905f3cf6a10035fb3e8cf5` |
| Shared client/CLI/fixture harness | `56303c5b925d55683399bb210812888d998cad5d` | `1e5653de526069a57d905f3cf6a10035fb3e8cf5` |

The same source identities apply to both experiments. Their retained Cargo.lock
digest is `sha256:fe3e93138d2ab6995d5583569a66dcd8361e7539f51b32ffadfcc8eafb422790`.
The external suite digest is
`sha256:481437610c090d07b52097d45d6a0db7e9b36c3be0dbcd06216e4c88d50e074e`;
the backend suite digest is
`sha256:5589daca12e3eea8f16221c59750b2a4f9e29e148818b9986f6ea5acb34fe2f8`.

The external suite records 169.844 seconds of measurement and 627.891 seconds
including its controlled builds. The backend suite records 41.950 seconds.
These whole-suite elapsed times are not invocation-latency statistics.

The observed host is an Intel Core i7-11850H, x86-64 Linux on a WSL2 kernel
`6.6.87.2-microsoft-standard-WSL2`, inside Docker. It exposes 16 logical CPUs;
`cpu.max` is `400000 100000`, equivalent to a four-CPU quota, with effective
cpuset `0-15`. The reported memory capacity is 33,233,743,872 bytes and the
cgroup memory ceiling is `max`. `LD_PRELOAD` and `MALLOC_CONF` are unset.
This is container evidence, not a native-host calibration or a dedicated-machine
isolation claim. Load and shared-cgroup observations remain in the raw receipts.

Both arms use Rust/Cargo 1.97.1, Wasmtime 47.0.3 and target
`x86_64-unknown-linux-gnu`. The pinned release recipe uses optimization level 3,
debug information level 1, 16 codegen units, no LTO or incremental compilation,
unwind panics, no stripping, and common path remapping. The recipe digest is
`sha256:16266aee2b730aac007d2ef6b7e5a74f8ce7391c69a0ffc1849011f30884414d`.
Retained common-source checks bind the client, CLI, workload, component ABI,
protobuf and release-build controls across revisions.

The collection commands below ran from a clean checkout of the recorded harness
in the owned Linux container. Both output directories must be absent; the build
parent is outside the checkout to prevent inherited Cargo configuration.

```sh
python3 tools/run_optimization_revision_benchmarks.py --profile full \
  --control-ref e94c180fdb15d064570c2b90aceacb0d984b847e \
  --candidate-ref 56303c5b925d55683399bb210812888d998cad5d \
  --harness-ref 56303c5b925d55683399bb210812888d998cad5d \
  --target-root /workspace/optimization-revision-builds \
  --output /workspace/project/target/optimization-revisions/warm-full-01 \
  --backend-build-output /workspace/project/target/optimization-backend-revisions/warm-full-01
python3 tools/run_optimization_backend_revision.py --profile full \
  --builds /workspace/project/target/optimization-backend-revisions/warm-full-01/backend-builds.json \
  --target-root /workspace/optimization-revision-builds
```

## What changed

The activation manager acquires a prepared activation from its repository.
The directory repository provides a sealed capability whose identity lookup and
verified fetch use one concrete owner. A compact stamp binds that owner's epoch,
component digest/size and normalized descriptor, manifest and contract metadata.
On a cache hit, the backend compares the complete identity and engine key before
returning an affine runtime pin. It does not reread/hash the component or walk
the full metadata. A miss verifies fresh bytes and metadata before compilation.
Generic repositories keep the fully verified fallback.

The identity is an admitted snapshot, not a live disk audit. Cached tokens retain
only a small epoch allocation, not the catalog lock. Index stamps, counters and
retained tokens have explicit byte charges. Routing, admission, budget accounting,
fresh stores, capability handles, cleanup and active-instance limits remain in
force. The production API regression tests separately prove unchanged warm
fetch/hash/fingerprint counters and rejection of corrupted disk content on
refill. Cache observations in this experiment are interval witnesses, not a
substitute for those deterministic checks. See the
[runtime contract](../../../../docs/runtime/wasmtime.md) and
[catalog contract](../../../../docs/development/local-release-catalog.md).

Cold fetch and compilation remain synchronous during materialization after
scheduler assignment. This change does not implement compile coalescing or a new
LRU policy; those remain [#101](https://github.com/KirilsTurkins/latent-service-fabric/issues/101)
and [#102](https://github.com/KirilsTurkins/latent-service-fabric/issues/102).

## External-client method

Seven independent pairs alternate control/candidate order. Each arm starts its
own server after a separately supervised seed server provisions and closes its
catalog. Each of nine cases then uses a separate persistent-connection Rust
load-client process against that server. The plan uses closed-loop concurrency
one, two client runtime workers, four server cells and four cache entries.
Both arms receive identical canonical payloads and the same five component
variants, each with a distinct content digest and matching published metadata.

Warm echo, compute, transform and each 1/2/5/10 ms budget case have 40 warmup and
400 measured offers per process. The working-set case has 5 + 100; the mixed
case has 10 + 100. This yields 3,295 offers per arm and 46,130 across 14 arms.
The 154 validated process owners comprise 14 seed servers, 14 measured servers
and 126 clients. Provisioning/inventory CLI helpers are separate overhead.

Non-budget cases request 1000 ms, ten billion fuel, 64 MiB memory and 16 KiB log
capacity. Compute uses seed 17 and 10,000 rounds. Transform uses a fixed label,
1,024 bytes and 64 integer values. No large catalog, long soak, native-reference
arm or broad concurrency/rate matrix is part of this nine-case profile.

Each attempt is retained, including platform/transport failures and warmup.
On-time success means a successful response completes by the exact client
monotonic budget deadline. The absolute wire deadline is rounded upward to whole
milliseconds and its quantization is recorded; precise remaining transport time
is also recorded. Successful responses after the requested client deadline are
not on-time successes.

The following values are **medians across seven per-process statistics**.
Latency is conditional on a successful response; p95/p99 are medians of each
process's p95/p99, not quantiles of pooled calls. Success throughput uses each
whole measured phase's elapsed time. No outlier or failed offer is discarded.

| Case | Median ms, control → candidate | p95 ms | p99 ms | Successful responses/s |
| --- | --- | --- | --- | --- |
| Warm echo | 0.888 → 0.579 | 1.556 → 1.013 | 1.854 → 1.366 | 884.7 → 1,287.4 |
| Compute | 1.073 → 0.709 | 1.688 → 1.244 | 2.095 → 1.551 | 756.7 → 1,070.2 |
| Transform | 1.372 → 0.971 | 2.213 → 1.569 | 2.502 → 1.960 | 609.8 → 825.5 |
| Budget 1 ms | unavailable: no successes | unavailable | unavailable | 0 → 0 |
| Budget 2 ms | 0.952 → 0.596 | 1.565 → 1.076 | 1.983 → 1.459 | 805.5 → 1,189.4 |
| Budget 5 ms | 0.961 → 0.619 | 1.619 → 1.049 | 2.077 → 1.338 | 816.3 → 1,210.4 |
| Budget 10 ms | 0.961 → 0.590 | 1.564 → 1.066 | 1.943 → 1.391 | 835.2 → 1,254.3 |
| Five-component working set | 34.763 → 36.308 | 39.862 → 44.444 | 41.936 → 54.783 | 28.4 → 26.4 |
| Mixed hit/refill | 17.071 → 16.624 | 41.234 → 40.335 | 45.964 → 44.233 | 50.5 → 52.9 |

Warm-echo process medians range from 0.856–0.977 ms in control and 0.541–0.643 ms
in candidate. Candidate-minus-control paired median differences range from
−0.409 to −0.245 ms, with median −0.295 ms; all seven pairs improve. Compute and
transform medians also improve in all seven pairs. Working-set medians regress
in all seven pairs, by 0.146–3.032 ms, with median paired increase 1.194 ms.
The mixed case improves in five pairs and regresses in two; its paired median
difference is −0.554 ms, spanning −1.484 to +0.238 ms. Seven pairs describe this
population's variability, not statistical significance or a general SLO.

### Every measured budget outcome

Each cell below counts all 2,800 measured offers per arm. Platform/transport
categories remain distinct; detailed codes and deadline/overshoot observations
are retained in the attempt rows.

| Budget | Control successes / platform failures / transport failures | Candidate successes / platform failures / transport failures | On-time successes, control → candidate |
| --- | --- | --- | --- |
| 1 ms | 0 / 2,792 / 8 | 0 / 2,796 / 4 | 0 → 0 |
| 2 ms | 2,650 / 144 / 6 | 2,665 / 135 / 0 | 2,611 (93.25%) → 2,664 (95.14%) |
| 5 ms | 2,800 / 0 / 0 | 2,800 / 0 / 0 | 2,800 → 2,800 |
| 10 ms | 2,800 / 0 / 0 | 2,800 / 0 / 0 | 2,800 → 2,800 |

At 2 ms, 39 control successes and one candidate success arrive after the client
budget deadline. The smaller success-conditioned latency therefore does not
establish the 99% target. All warm/compute/transform measured offers succeed
(2,800 per case per arm), as do all working-set and mixed offers (700 each per
arm). Every measured offer is dispatched; semantic mismatches are zero. There
are no other measured outcome categories in this population.

### Cache and memory observations

In every warm-echo process, the before-warmup/after-measured cache interval has
439 hits and one miss. Compute and transform each have 440 hits and no misses.
The 1 ms interval has neither hits nor misses; the failed offers do not establish
a warm preparation measurement. The five-service round-robin working set has
one hit, 104 misses and 101 evictions per process. Repeating each service twice
in the mixed case produces 55 hits, 55 misses and 55 evictions. These counts are
identical between revisions; invalidations are zero. The refill regression
cannot be described as a cache-hit improvement.

Cache witnesses are collected outside request timers and include warmup and
inventory-observation overhead. They verify idle cells and queues, zero pending
preparations, and occupancy/byte counters within configured ceilings. They do
not measure per-call disk reads or hash work.

For each measured server, taking the maximum of its sampled RSS across nine
batches gives a median of 29.10 MiB in control and 29.05 MiB in candidate.
Across processes the ranges are 28.86–29.32 and 28.25–29.57 MiB respectively.
This is effectively flat sampled memory, not evidence of a footprint reduction.
The fixed 100 ms observation hold follows all timed client work and permits a
live completion sample; it is excluded from the measured phase. Sampled RSS is
not an instantaneous peak, and shared-cgroup counters are not isolated server
measurements. No CPU saving is inferred by subtracting timing intervals.

## Separate backend diagnostic

This experiment uses the same current libtest/RPC diagnostic in both revisions,
with the maintained Echo component, two cells, three queue slots and a four-entry
cache. Each independent child makes 40 warmup plus 400 measured real RPCs.
The first RPC begins with an empty cache inside warmup; there is no manual
preparation before it. Every subsequent call reuses the one retained preparation.
All 6,160 calls pass typed outcome, retained-status, cache and cleanup checks.
The grant is ten billion fuel, 16 MiB memory, 1000 ms wall time and 16 KiB logs;
on-demand allocation, copy-on-write and a 10,000-fuel async yield interval are
the same in both arms.

Values below are medians across the seven per-process statistics, in
**microseconds**. They belong to this diagnostic and must not be substituted
for the external-client table.

| Interval | Median, control → candidate | p95 | p99 |
| --- | --- | --- | --- |
| Backend setup | 80 → 94 | 150 → 198 | 223 → 298 |
| Guest call | 75 → 87 | 147 → 200 | 220 → 307 |
| Host calls, within guest call | 20 → 23 | 39 → 58 | 60 → 84 |
| Subsequent host post-return accounting | 0 → 0 | 1 → 1 | 1 → 2 |
| Activation-resource reclamation | 33 → 36 | 61 → 96 | 87 → 136 |
| Outcome classification | 0 → 0 | 0 → 0 | 1 → 0 |
| Reusable proof | 0 → 0 | 0 → 0 | 0 → 1 |
| Backend total | 196.5 → 235 | 367 → 499 | 486 → 640 |
| Real RPC through terminal receipt | 1,532 → 1,126 | 2,466 → 1,926 | 2,910 → 2,267 |

There are two host calls per invocation in both arms. Guest-call time includes
automatic canonical post-return; the separately named post-return interval
measures subsequent host accounting. Host-call time is a subset, not an extra
interval to add. Zero microseconds reflects timer resolution, not zero work.

Backend-total process medians range from 174–235 µs in control and 214–255 µs in
candidate. All seven paired backend-total medians increase, by 12–45.5 µs
(median +40 µs), while all seven RPC medians decrease, by 332–599 µs
(median −409.5 µs). **Backend total begins after manager materialization and
preparation.** Neither subtracting it from RPC latency nor subtracting the two
changes isolates artifact hashing, CPU cost or another causal component.

The first empty-cache RPC is one warmup observation per process: its median is
38.312 ms in control and 37.092 ms in candidate, with ranges 36.750–54.345 and
34.834–46.387 ms. It includes preparation through terminal receipt and has no
400-call cold distribution. External parent-observed startup/first-response
timings additionally include client launch/connect and inventory overhead.

## Validation and limits

The integrated artifact/executor/node/Wasmtime/daemon checks passed 320 Rust
tests. All 31 generic-backend portable and real-component tests passed with
serial fixture execution, including zero-read warm reuse, corrupt refill,
delegated repository authority, optional imports and foreign-factory ownership.
After correcting the older Echo fixtures to use real component identities, all
four real Echo backend tests passed. The ordinary Phase 1 benchmark collector
also passed its bounded smoke run with the new repository-acquisition scope.
Focused Python checks cover raw replay, revision population and source binding,
process cleanup, archive tampering and unchanged historical replay.
All 64 archive tests passed on Linux, including symlink rejection and fully
rehashed semantic tampering of split transport.

Both full suite replays passed, including exact source/input associations,
complete attempted populations, semantic results, deadline accounting, bounded
cache witnesses and supervised cleanup. The backend package also passed mandatory
Linux archive extraction/replay and independent Windows replay of all 325 files.
Its compressed archive is 92,674,126 bytes with SHA-256
`e3542a047af52ab99f923a3a99cfe5988c084ea8c631be06934c630931bbfb85`.
The external package passed mandatory Linux replay and independent Windows
replay of all 2,209 files (508,491,972 expanded bytes). Its exact gzip stream is
104,832,759 bytes with SHA-256
`d4cae0a082b983d690eb690b983b0291d7859ff7e89dd7f5b50ade2c001c434d`.
It is stored as 50,000,000, 50,000,000 and 4,832,759-byte parts; the adjacent
parts manifest binds their order, individual hashes and complete stream hash.

The first gzip-level-6 packaging attempt exceeded the ordinary 99,000,000-byte
cap, as did the level-9 attempt. Explicit split transport preserves the complete
level-9 stream and every unchanged input file. Its separate limit is 198 MB
compressed in two to four parts of at most 50 MB. Ordinary archives keep their
99 MB cap; both transports retain the 1 GiB expanded, 5,000-file and 8 MiB
aggregate limits and mandatory semantic replay. These packaging attempts are
not new measurement populations or selectively replaced samples.

Local diagnostics remain outside these qualified tracked full archives:
`warm-smoke-01` stopped before any Cargo build or RPC because ancestor Cargo
configuration violated the controlled build policy. `warm-smoke-02` passed 314
external offers and 12 backend calls. Their original directories and logs are
retained locally; neither failed setup nor smoke results contribute performance
samples to the full aggregates. A later test-only Echo descriptor correction at
`05e613e` addresses CI fixture association, with no production changes after the
measured candidate. It is not relabeled as the measured source.

To replay a completed retained package, from the repository root:

```sh
python3 tools/validate_phase1_archive.py \
  benchmarks/optimization/warm-activation/2026-09-08-container-linux-56303c5/external
python3 tools/validate_phase1_archive.py \
  benchmarks/optimization/warm-activation/2026-09-08-container-linux-56303c5/backend
```

This report establishes a measured warm-path improvement with explicit cold
tradeoffs. It does not establish 99% on-time success at 2 ms, arbitrary-duration
leak freedom, 100k catalog/soak behavior, a native-host baseline, or a causal CPU
or memory saving. Historical Phase 1 and #98 native-comparison archives retain
their own exact sources, populations and timing scopes.
