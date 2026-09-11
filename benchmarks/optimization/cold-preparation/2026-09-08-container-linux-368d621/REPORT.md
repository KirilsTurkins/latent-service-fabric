# Bounded cold preparation: before/after observations

Historical raw archive payloads are omitted from this checkout. Results and
original validation records remain; recorded replay passes describe publication
checks. [Restore the exact historical package](../../../../docs/testing/benchmark-retention.md) before running raw
replay or extraction commands below. Set `restored_root` to its fresh restore
directory; manifests alone do not make the current directory replayable.

Recorded 2026-09-08 for [#101](https://github.com/KirilsTurkins/latent-service-fabric/issues/101).

The candidate keeps warm calls responsive during distinct cold preparation:
median per-process warm RPC p99 falls from **70.824 ms to 1.824 ms**, and
all-offered warm p99 from **72.065 ms to 2.964 ms**. It completes all 896 warm
offers in that phase; the synchronous control drops 134 at the client's
concurrency limit. Same-key cold fanout improves from **14/56 to 56/56**
successful calls, with one compilation per process in both arms.

These gains have costs. The candidate admits four of five distinct cold keys
per run, completing **28/35 cold calls** against the control's **35/35**. Fresh
RPC latency increases from **34.980 ms to 36.600 ms**, successful same-key cold
median latency from **37.784 ms to 42.461 ms**, and sampled RSS is higher. The
candidate compiles fewer jobs overall, so its lower total compilation CPU does
not establish a saving at matched completed work. This is evidence of improved
warm responsiveness and same-key fanout, not faster compilation overall.

## Evidence and exact controls

The [aggregate](aggregate.json) records `profile: full`, `status: complete`, and
true `population_complete` and `attempt_count_complete`. All **11,942 Invoke
attempts** and **24,206 commands** across seven alternating pairs and 14
independently supervised processes are retained, including rejections and
deliberate cancellations. All processes shut down cleanly and were reaped.
Collection took **33.445 seconds**, excluding builds; supervised arms took
1.943–2.115 seconds. These durations are not RPC latency statistics.

| Role | Exact clean source | Tree |
| --- | --- | --- |
| Synchronous control with common observation harness | `9187d6cae60ae313a00e1e5fa30f5cc8faba8efe` | `d707089d3e514890d174230e60e805ecb4d107d3` |
| Candidate and executed harness | `368d621b324c85d4e286b15615009c143b0bc015` | `12869bd1b4979b0db73c9b874cab00159e822676` |

The collector subtree, observer CPU helper/model, Echo source and ABI, build
recipe and toolchain match across the two revisions. Both retain Cargo.lock
digest `sha256:fe3e93138d2ab6995d5583569a66dcd8361e7539f51b32ffadfcc8eafb422790`.
The suite digest is
`sha256:220935f3c28597ceed1b9034bfaaca5b4722e6c282c8be342ff004568e596108`.

The host is an Intel Core i7-11850H, x86-64 Linux in Docker on WSL2 kernel
`6.6.87.2-microsoft-standard-WSL2`. It exposes 16 logical CPUs with cpuset `0-15`
and `cpu.max=400000 100000`, a **four-CPU quota**. Reported host memory is
33,233,743,872 bytes; the cgroup memory ceiling is **`max`**. Allocation overrides
`LD_PRELOAD` and `MALLOC_CONF` are unset. Retained cgroup `nr_throttled` does not
increase during any arm. These shared-cgroup and host observations do not prove
an otherwise idle dedicated machine or isolate compiler resource use.

Both builds use Rust/Cargo 1.97.1, Wasmtime 47.0.3 and target
`x86_64-unknown-linux-gnu`. The pinned release recipe uses optimization level 3,
debug information level 1, 16 codegen units, no LTO or incremental compilation,
unwind panics, no stripping and common path remapping. Its digest is
`sha256:16266aee2b730aac007d2ef6b7e5a74f8ce7391c69a0ffc1849011f30884414d`.
Both revisions use the same owned source and target paths during building.
Retained executable identities are:

| Executable | Bytes | SHA-256 |
| --- | ---: | --- |
| Control collector | 201,749,696 | `22f4bbde33550b1cd8a6808dae3189e0a3174c8b731792eda48b39e5f00c9b98` |
| Candidate collector | 202,774,608 | `2497b20f3705e90003202d1415c254c8b6d51fc09223f1c3139a42e6a69846bf` |

## Finite workload and measurement boundaries

Each process composes a real standalone node with two invocation workers, four
control workers, four cells and 64 queued activation slots. A separate fixed
two-worker client runtime offers requests through persistent loopback RPC. Both
arms allow four distinct preparations and eight resident cache entries. The
candidate has two compiler workers and capacity for two queued jobs; the control
compiles synchronously without a compiler pool. Caller and ready-owner limits
are 68. Grants are 10 billion fuel, 16 MiB memory, 1,000 ms wall time and 16 KiB
logs.

Eight releases execute the same deterministic Echo logic and input
`phase0 targeted warm echo` (25 UTF-8 bytes). K0 is the retained 24,754-byte
component with SHA-256
`23a911cd79e41ee98bb6431fde46844500109589eeaa9d0b25225a692109e233`.
K1–K7 append distinct valid four-byte custom sections. Actual component,
capsule, contract and deployment bytes are retained per key. Publication object
and catalog generations advance globally from 1 through 8. The eight-entry
cache avoids unintentionally evicting the warm key in this population.

| Per-process phase | Invoke attempts | Fixed population |
| --- | ---: | --- |
| Warmup | 40 | Sequential K0; first call starts with an empty prepared cache |
| Warm baseline | 400 | Sequential K0 after the predeclared warmup |
| Same-key cold burst | 136 | Eight K1 calls plus 128 scheduled K0 calls |
| Distinct cold burst | 133 | One call each to K2–K6 plus 128 scheduled K0 calls |
| Cancellation burst | 136 | Eight K7 calls plus 128 scheduled K0 calls; four Cancel commands |
| Healthy recovery | 8 | Sequential K0 |

Warm offers are spaced 2 ms apart; cold calls are due 16 ms after each stream
begins. The client allows at most 16 warm requests in flight and retains excess
offers as undispatched `client-overload`. One GetActivation responsiveness probe
runs in each burst. Cancellation starts from an actual observation of K7's
`component_new`, without an artificial compiler stall. Every burst drains its
owned preparation work and records idle state before the next phase.

Resource snapshots and large file writes precede the schedule anchor or follow
the burst. A declared 10 ms lead separates anchor recording from the first
offer. Detailed observer instrumentation is enabled in both arms; its overhead
belongs to this experiment. No per-call resource probe runs in the offered
streams. Success validation and retained activation status remain part of the
collected evidence, with no hidden Invoke retry.

## RPC latency and warm responsiveness

Control and candidate values below are **medians of seven per-process
statistics**, not percentiles pooled across processes. The last column is the
**median of seven paired candidate-minus-control differences**. It need not
equal the difference between the preceding columns. All values are ms.
Success-only latency is conditional on success; all-offered elapsed includes
dispatch lag and undispatched offers.

| Metric | Control | Candidate | Paired change |
| --- | ---: | ---: | ---: |
| First real RPC, including cold preparation | 34.9804 | 36.5999 | +1.9091 |
| Warm baseline success p50 | 0.6930 | 0.7065 | +0.0173 |
| Warm baseline success p99 | 1.4680 | 1.4721 | −0.0190 |
| Same-key burst: warm success p50 | 0.7866 | 0.8538 | +0.0233 |
| Same-key burst: warm success p99 | 1.9123 | 2.2449 | +0.0683 |
| Same-key burst: all-offered warm p99 | 3.7593 | 3.3326 | −0.1271 |
| Distinct burst: warm success p50 | 0.8980 | 0.8119 | −0.0406 |
| Distinct burst: warm success p99 | 70.8235 | 1.8236 | −68.7032 |
| Distinct burst: all-offered warm p99 | 72.0653 | 2.9637 | −68.5096 |
| Cancellation burst: warm success p50 | 0.7825 | 0.7405 | −0.0291 |
| Cancellation burst: warm success p99 | 1.9151 | 1.7974 | −0.1177 |
| Cancellation burst: all-offered warm p99 | 3.8504 | 3.6470 | +0.1779 |

The distinct-burst all-offered p99 improves in every pair, with paired changes
from −83.701 ms to −45.907 ms. Same-key paired changes range from −35.758 ms to
+1.263 ms, exposing a much slower control repetition that the median alone
would obscure. Cancellation all-offered p99 has a positive median paired change
despite the lower candidate median-of-process-values; its pair differences range
from −1.188 ms to +0.732 ms, with regressions in four of seven pairs. Seven pairs
provide descriptive variability, not
statistical significance or proof of equivalence.

Successful cold latency also changes, with different admitted populations:

| Conditional cold metric | Control | Candidate | Paired change |
| --- | ---: | ---: | ---: |
| Same-key success p50 | 37.7843 | 42.4612 | +3.8845 |
| Same-key success p99 | 37.9940 | 42.8662 | +4.0383 |
| Distinct-key success p50 | 74.2753 | 61.6807 | −13.5733 |
| Distinct-key success p99 | 109.1194 | 82.9619 | −31.5053 |

The same-key candidate completes more callers but is slower among successful
calls. Distinct-key improvement is conditioned on admitting four rather than
five keys; it must not be interpreted as equal-work cold throughput.

Overlap counts below require actual warm RPC intervals to intersect recorded
`component_new` intervals under the retained conservative observer/collector
clock mapping. A phase name or schedule alone is insufficient. All overlapping
warm RPCs in these counts succeeded.

| Burst | Control overlapping warm RPCs | Candidate overlapping warm RPCs | Pairs with overlap in both arms |
| --- | ---: | ---: | ---: |
| Same key | 128 | 143 | 7/7 |
| Distinct keys | 262 | 284 | 7/7 |
| Cancellation | 132 | 140 | 7/7 |

GetActivation probe median elapsed times are 1.943→0.495 ms for same-key
preparation, 74.405→0.472 ms for distinct preparation, and 1.853→0.473 ms during
cancellation. These are measured control RPC intervals, not inferred scheduler
latency. Throughput fields in the aggregate use first-scheduled-to-last-completed
observation intervals, not whole-process duration or compiler CPU.

## Admission, fanout and cancellation outcomes

All warmup, baseline and healthy-recovery calls succeed in both arms. Every
burst offer across the seven repetitions remains in these counts:

| Population | Control | Candidate |
| --- | --- | --- |
| Same-key warm, 896 offers | 894 success; 2 client-overload | 896 success |
| Same-key cold, 56 offers | 14 success; 42 unavailable | 56 success |
| Distinct warm, 896 offers | 762 success; 134 client-overload | 896 success |
| Distinct cold, 35 offers | 35 success | 28 success; 7 unavailable |
| Cancellation warm, 896 offers | 896 success | 896 success |
| Cancellation cold, 56 offers | 49 unavailable; 7 cancelled | 28 success; 28 cancelled |

Each arm compiles K1 once per same-key phase. The candidate serves all eight
callers from that compilation; this is improved fanout, not a reduction from
eight compilations to one. It records 14 coalesced waiters per process across
the same-key and cancellation bursts. Distinct preparation compiles five keys
in control and four in candidate in every run. The candidate's seven
`unavailable` responses remain visible beside its better warm responsiveness.
Its `queue_rejected` counter is zero; the public error code alone must not be
attributed to that particular internal counter.

All 14 cancellation triggers observed K7 compilation running. Of 28 Cancel RPCs
per arm, candidate accepts 28; control accepts 7 and reports 21 already terminal
with `dependency_failed`. Already-terminal responses are not accepted
cancellations. The candidate's four other K7 callers per run succeed using the
same compilation.

Overall, control records 5,737 successes, 136 undispatched client overloads and
98 platform failures. Candidate records 5,936 successes and 35 platform failures.
There are no semantic mismatches, transport failures or recorded deadline
overshoots. The aggregate's 234 versus 35 budget misses include every unsuccessful
offer, including deliberate cancellation; they do not denote elapsed-time
deadline overruns. Zero overshoot concerns the fixed one-second budget and does
not establish a tight-budget SLO.

## Compilation time, task CPU and resources

Elapsed values retain the median-of-seven-per-process-medians convention.
CPU totals sum actual paired Linux task user/system tick differences at
100 ticks/second. They are neither whole-process CPU nor allocations. Control
executes 56 jobs and candidate 49 because one distinct key is rejected per run.

| Preparation stage | Control elapsed ms | Candidate elapsed ms | Paired change ms | Task CPU total, control/candidate ms |
| --- | ---: | ---: | ---: | ---: |
| Repository fetch and verification | 0.3799 | 0.4368 | +0.0500 | 10/0 |
| Metadata validation | 0.0227 | 0.0239 | −0.0012 | 0/0 |
| Component::new | 34.0880 | 38.3361 | +1.8553 | 1,840/1,750 |
| Surface linking | 0.0597 | 0.0549 | −0.0043 | 10/0 |
| Cache adoption | 0.0040 | 0.0037 | +0.0000 | 0/0 |
| Whole preparation body | 34.7370 | 38.8606 | +1.8966 | 1,860/1,750 |
| Submitted-ready to worker pickup | Not present | 0.1058 | Not comparable | Unavailable |

WholeJob measures the synchronous body after worker pickup in candidate and
inline in control. Its nested stages overlap it and must not be added to it.
Fetch includes repository I/O, component hashing and metadata decoding;
Component::new includes Wasmtime validation. Cache adoption's median paired
change is +21.5 ns, rounded in the ms table. The observed per-job
Component::new CPU median is three ticks in control and four in candidate
(30 ms versus 40 ms), with coarse 10 ms resolution and different job populations.
The candidate does not show a measured per-compilation CPU improvement.

Zero-tick stages still perform work. QueueWait crosses threads and has unavailable
CPU for all 49 records. Its median per-process p99 is 41.300 ms, and the largest
actual interval is 45.510 ms. It includes assigned-worker wake delay as well as
waiting in the FIFO; it is one interval per distinct job, not per coalesced
caller. Compiler jobs bind release digests and task intervals, while RPCs bind
activation IDs. No per-caller prepare-ready latency is inferred by subtracting
backend timing from RPC time.

The initial K0 compilation is counted in warmup. Neither arm recompiles K0 in
baseline, bursts or recovery. Every compilation record is assigned to its actual
phase; none is left unattributed. All 56 control and 49 candidate observations
for each synchronous preparation stage have actual same-task CPU readings.

RSS below is the median of seven sampled process values, in MiB. The final sample
is also each process's largest retained RSS sample, not a continuous high-water
measurement.

| Checkpoint | Control RSS | Candidate RSS |
| --- | ---: | ---: |
| Empty prepared cache, node ready | 14.500 | 14.750 |
| After warm baseline | 25.121 | 26.359 |
| After recovery / before shutdown | 33.090 | 33.574 |

Actual process thread counts are 11 versus 13. The candidate's 20-row topology
inventory explicitly includes `wasmtime-compiler` with configured and active
counts 2/2; control has 19 rows and no compiler pool. All snapshots show one
listener and no descendants. Final sampled control cache occupancy is eight
entries and 814,976 attributed compiled-image bytes; candidate is seven entries
and 713,104 bytes. Neither evicts an entry. The smaller candidate cache population
does not yield lower measured RSS: final ranges are 32.598–33.559 MiB for control
and 33.289–33.891 MiB for candidate.

RSS includes the node, libtest, client runtime, journal, telemetry and observation
machinery. Compiled-image accounting is not a separate physical-memory
measurement, and no allocation profile was collected. Every phase drain records
zero transient preparation and activation ownership. Final shutdowns report zero
quarantined cells, active/queued activations, leases, reservations, live guest
stores/instances/host state, cancellation probes and preparation charges. Candidate
ready/document byte charges are zero and both compiler workers are quiescent and
joined. Telemetry retains 107 bounded entries, not zero. Invocation, control and
client runtimes join before child exit, followed by parent exit/reap/pipe-close
and data-removal receipts. These finite observations establish cleanup for the
recorded population, not long-term leak freedom.

Control also records 12,083 telemetry queue-full drops across the seven
processes (954–2,095 per process), against zero in candidate. Both bounded sinks
evict older entries. Successful RPCs and clean shutdown therefore do not imply
lossless telemetry delivery in the control; these drop counters remain part of
the evidence rather than being treated as zero after cleanup.

This experiment uses actual RPC with node and client inside one supervised
libtest process. The
[#100 external-client reference](../../warm-activation/2026-09-08-container-linux-56303c5/REPORT.md)
uses separately supervised standalone servers and clients, different offered
populations and different boundaries. Its numbers should not be subtracted from
these to claim another optimization delta. Functional tests separately force
compiler saturation and cancellation/shutdown races; the ordinary measured
compilations are not stalled to manufacture overlap.

## Archive, reproduction and earlier diagnostics

The [historical archive](https://github.com/KirilsTurkins/latent-service-fabric/blob/a432c51f9ed0a4eaf55473d80122bbb8e5a419cf/benchmarks/optimization/cold-preparation/2026-09-08-container-linux-368d621/raw-evidence.tar.gz) contains 755 original files totaling
442,057,781 bytes. The gzip stream is **94,759,089 bytes**, SHA-256
`71f52da001932cd83ced66e3ead5dfa9bc5715341fb44ca6b11bd8a7d68caee8`.
The [manifest](raw-evidence.manifest.json) binds every retained file, and the
[checksum sidecar](raw-evidence.tar.gz.sha256) binds the stream. Raw calls,
stages, binaries, fixtures, source/build records and ownership receipts are
preserved. Linux packaging and mandatory strict replay passed, and independent
Windows archive replay passed for all 755 files.

Exact release builds were reused byte-for-byte for smoke and full runs in
separate fresh output directories. From the clean recorded harness, the actual
full collection command was:

```sh
python tools/run_optimization_backend_revision.py --experiment cold --profile full \
  --builds /workspace/project/target/optimization-backend-revisions/cold-full-02/backend-builds.json \
  --target-root /workspace/project/target/cold-owned-data
```

The runner checks the retained build receipt, exact source identities, common
controls, executable/fixture hashes and completed build cleanup before any arm
starts. It refuses an output directory containing an earlier run. The aggregate
can be reproduced independently from the raw suite:

```sh
python tools/validate_optimization_backend_revision.py \
  /workspace/project/target/optimization-backend-revisions/cold-full-02/suite.json \
  --aggregate /workspace/project/target/optimization-backend-revisions/cold-full-02/aggregate.json
python tools/validate_phase1_archive.py \
  "${restored_root}/benchmarks/optimization/cold-preparation/2026-09-08-container-linux-368d621"
```

Archive replay never executes retained binaries. The package remains below the
unchanged 99,000,000-byte monolithic compressed cap, with limits of 1 GiB expanded
data, 5,000 files and 8 MiB aggregate. Packaging safely extracts and reproduces the
aggregate before publishing the package.

Earlier attempts remain separate. Smoke01 failed before any Invoke because an
inherited flat-file supervisor watch rejected nested fixture directories; the
child was killed and reaped. A bounded opt-in tree watch fixed that harness
failure. Smoke02 completed 154 calls but initially failed offline analysis because
replay expected each publication's object generation to be 1. Correcting replay
to the actual global sequence 1–8 validated those unchanged raw receipts without
rerunning them. A subsequent production shutdown correction required fresh-source
smoke/full evidence.

The first full dataset at `9065ab413081e97ed8304935d7c07ffd03070950` passed its
population and cleanup checks but lacked the compiler-worker topology row. Its
94,796,102-byte package, SHA-256
`f0a6a91bb28654caa0e8ead8fcf79316b631b49d248c1a5e310dc83e54e52dfa`, and report
were retained at publication as local audit diagnostics under
`target/phase1-extension/issue101-full01-package` in the original audit workspace; continued local availability is not promised.
This published dataset reruns the
complete population after that inventory correction. None of its metrics is
carried forward from the first full run, and no earlier attempt is silently
counted among these seven pairs.
