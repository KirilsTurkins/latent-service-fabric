# Precise budgets: controlled revision comparison

The candidate met the 99% useful-success target at 2 ms: **2,794/2,800 offers
(99.7857%)**, versus **2,634/2,800 (94.0714%)** for the control. All seven paired
repetitions improved. Neither variant completed useful work at 1 ms. Successful
warm-call latency improved modestly, while all-offered tails were mixed. The
separate lifecycle diagnostic observed no candidate extension of the original
arrival deadline and fewer manager wait guards, but running Wasm interruption
still produced several milliseconds of response delay after its native deadline.

This is the bounded [#103](https://github.com/KirilsTurkins/latent-service-fabric/issues/103)
experiment. It does not close the separate
[#119](https://github.com/KirilsTurkins/latent-service-fabric/issues/119)
requirement for cleanup and serving-capacity recovery after a running transport
disconnect.

## Sources and populations

| Role | Exact executed source |
| --- | --- |
| Control | `a30967f4a14bd3f49903cc23c74b7f8cb26ccd1f` |
| Candidate and common harness | `e25b60946c433e3a3f40908656ae0b4155ec5c08` |

Both variants execute LSF. The clean control contains the common measurement
instrumentation and preserves the earlier budget implementation. Exact common
client, collector, fixture, lockfile and build-policy inputs are retained and
matched across revisions. The candidate combines precise deadline propagation,
admission/accounting changes and manager wait changes; this experiment does not
isolate the cost of each change.

Seven independent pairs alternate control/candidate order. The external suite
contains 24,654 offers and 98 validated server/client process identities. Each
arm has one explicit prewarm, then 40 warmup and 400 measured offers at each of
1, 2, 5 and 10 ms. Its 22,400 measured offers exclude all 14 prewarms and 2,240
warmup offers, which remain in the raw evidence. The separate lifecycle suite
contains 322 offers and 798 commands in 14 supervised processes. The combined
population is **24,976 offers**; their timing and CPU populations are not pooled.

The external client uses one persistent connection per case and one outstanding
request. Each budget population starts with the actual component resident and
records no additional preparation miss, eviction or invalidation. The lifecycle
diagnostic uses a real node with a separate client runtime. Both use four cells,
64 queue slots, two invocation workers, four control workers, four preparation
slots and two compiler workers. Fuel, memory and log grants are 10 billion,
64 MiB and 16,384 bytes. The 512 MiB journal ceiling is conservative retention
accounting, not an allocated-memory measurement.

The recorded environment is Docker on WSL2 Linux
`6.6.87.2-microsoft-standard-WSL2`, x86-64, on an Intel Core i7-11850H with
16 logical CPUs. The observed cgroup allows four CPU equivalents
(`400000 100000`) and CPUs 0–15, with `memory.max=max`; reported host memory is
33,233,743,872 bytes. Builds use Rust/Cargo 1.97.1 and Wasmtime 47.0.3 with the
same pinned release recipe. CPU observations have 100 Hz tick resolution.
All 56 short-budget batch intervals recorded zero additional cgroup throttling
events/time. These shared cgroup observations do not establish an isolated host
or exclusive service resource attribution.

## External useful work and latency

Useful success means a semantically correct response observed by the client
within the original offered deadline. Every measured offer remains in its
denominator, including failed, undispatched and late responses. Each table cell
has 2,800 offers per variant.

| Budget | Control on-time successes | Candidate on-time successes | Control / candidate total successful responses |
| --- | ---: | ---: | ---: |
| 1 ms | 0 (0%) | 0 (0%) | 0 / 0 |
| 2 ms | 2,634 (94.0714%) | 2,794 (99.7857%) | 2,636 / 2,798 |
| 5 ms | 2,800 (100%) | 2,800 (100%) | 2,800 / 2,800 |
| 10 ms | 2,800 (100%) | 2,800 (100%) | 2,800 / 2,800 |

At 2 ms the control had 164 admission rejections and two late successful responses;
the candidate had two `grpc-1` transport failures and four late successful responses.
Per-process useful successes rose from 367–384/400 to 398–400/400. All seven
candidate repetitions individually exceeded 99%. At 1 ms the control had 2,667
admission rejections, 132 deadline-exceeded platform failures and one `grpc-1`
transport failure; the candidate had 2,800 admission rejections. The unchanged
1 ms minimum execution allowance leaves no headroom for
arrival/admission work inside a 1 ms request. Faster rejection is not successful
1 ms service. All 5 ms and 10 ms measured offers succeeded on time.

The following values are medians of the seven process statistics, in
milliseconds. Paired changes are medians of candidate-minus-control differences
within each repetition, not differences between the two arm medians.

| Budget | Successful RPC p50, control → candidate | Median paired p50 change | All-offered p99, control → candidate | Median paired p99 change |
| --- | ---: | ---: | ---: | ---: |
| 1 ms | unavailable | unavailable | 1.014067 → 0.957261 | −0.057427 |
| 2 ms | 0.607069 → 0.589437 | −0.017164 | 1.495096 → 1.446582 | **+0.027043** |
| 5 ms | 0.638423 → 0.611493 | −0.039283 | 1.564937 → 1.411979 | −0.139443 |
| 10 ms | 0.618681 → 0.605464 | −0.006256 | 1.482530 → 1.466169 | −0.070896 |

Successful p50 was lower in five of seven pairs at each of 2, 5 and 10 ms;
these distributions are conditional on success. At 2 ms successful p99 changed
from 1.392368 to 1.371815 ms, with a median paired change of −0.035370 ms.
All-offered elapsed time also includes dispatch delay and every failure. Its
2 ms p99 was higher in four of seven pairs, despite the lower candidate arm
median. The useful-success improvement therefore does not establish uniformly
better tails. At 5 and 10 ms, all-offered p99 improved in four of seven pairs.

Throughput in the aggregate uses first scheduled offer through last completed
attempt, rather than reciprocal latencies. Server/client resource intervals
include warmup and observer overhead; they are not measured-only per-call CPU.
No external timer counter is inferred.

## Deadline, queue and cancellation observations

Each lifecycle process retains 23 distinct offers, all 57 actual commands and
the bounded source event graph. The control has 198 events per process and the
candidate 202. Across the control's 161 diagnostic offers, 71 had at least one
deadline stage later than original ingress expiry: 174 stage observations, up
to 0.332597 ms of extension. The candidate had none. Neither variant recorded a
late Accepted/Completed terminal-decision check in this population. These are
actual stage observations, not deadlines reconstructed from RPC duration.

Both variants observed the 5 ms and 10 ms queue targets behind four running
holders in every repetition: 14 actual queued targets per variant. The 1 ms and
2 ms queued offers were rejected before queue ownership. All 28 delayed-body
offers per variant received transport responses before the scheduled body
release; none decoded a body or acquired an admitted ledger. Release delivery
was possible in three control cases and two candidate cases, after expiry.
This proves early transport termination with a withheld body, not successful
body processing followed by rejection.

At 2, 5 and 10 ms, all 21 runaway offers per variant actually reached Running
and ended deadline-exceeded. The seven 1 ms runaway offers per variant were
rejected before execution, so their native interruption latency is unavailable.
All 28 holder cancellations, 21 short running cancellations and seven positive
1,000 ms cancellations per variant were accepted; the seven 1 ms short-cancel
targets were already terminal after admission rejection. Every prewarm and
recovery call succeeded.

For runaway and short-cancel diagnostics, the native grant remains
1/2/5/10 ms but both caller absolute and gRPC timeout allow 1,000 ms. Queued,
delayed-body and external requests retain matching short transport budgets.
The table below measures the runaway's actual admitted native deadline, not
that longer transport allowance. Each cell is a median of seven observations,
in milliseconds.

| Native budget | Decision overshoot, control → candidate | Median paired decision change | Client response after native expiry, control → candidate |
| --- | ---: | ---: | ---: |
| 1 ms | unavailable: no admitted execution | unavailable | unavailable |
| 2 ms | 2.861290 → 4.021327 | **+0.146413** | 3.199841 → 4.321996 |
| 5 ms | 3.914092 → 3.855985 | −0.397875 | 4.180500 → 4.193730 |
| 10 ms | 4.107821 → 3.988610 | −0.252644 | 4.402105 → 4.289429 |

The 2 ms decision and response delays regressed in four of seven pairs.
The maximum candidate runaway response delay after native expiry was 5.509838 ms.
Removing manager polling did not eliminate running-Wasm interruption and
cleanup delay. A terminal-decision timestamp records the actual checked instant;
terminal-winner and lifecycle-phase events observe commits afterward. Client
response additionally includes cleanup and propagation. Missing control
pre-admission terminal-decision observations remain unavailable, not zero.

Observed manager wait guards fell from a median 75 armed to 43, and completed
waits/rechecks from 37 to 5; both decreased in all seven pairs. Maximum live
guards stayed at five and final live guards were zero. These counters describe
only manager-owned sleeps, not all Tokio, transport or operating-system timers.

Across the four short-budget batches, external server CPU totals were
6.47 → 6.30 s and client totals 4.18 → 4.04 s, summed over seven repetitions
per variant (seven servers and 28 budget clients).
The median paired server change was −0.02 s, lower in five of seven pairs.
The diagnostic's combined process CPU totaled 1.86 → 1.83 s, but its median
paired change was **zero ticks**: two lower, four equal and one higher. Fewer
observed waits therefore do not establish a consistent diagnostic CPU gain.
These coarse same-process user/system ticks include the node, client, controls
and observers through drain; they are not per-offer CPU.

Median per-process maximum observed server RSS was 28,819,456 → 28,565,504 bytes
externally (median paired change −323,584 bytes), and diagnostic RSS was
25,821,184 → 25,665,536 bytes (−118,784 bytes paired). Both were lower in five
of seven pairs. The largest external client observation across the four budget
cases in each repetition had the same 4,587,520-byte median.
These are sampled maxima, not instantaneous peaks or isolated runtime memory.
Both diagnostic variants observed at most 13 threads, 24 file descriptors,
eight socket references covering five unique sockets, and no descendants.
All runs passed actual shutdown, process reclamation and owned-data cleanup;
diagnostic quarantine and live transient ownership were zero, compiler workers
and runtime threads were joined. Bounded retained telemetry history remains
distinct from those live counters.

## Failed attempts and practical limits

The original source-bound functional debug attempt at `497…` offered 22
requests and retained 20 final offer rows before failing, with four quarantined
cells following same-deadline running transport disconnects. A subsequent
functional wrapper used a stale executable and is excluded for invalid source
binding. These attempts remain preserved; later functional fixtures are parser
correctness evidence, not release performance samples.

The first official external smoke at candidate/harness `3ce1a762…` and control
`f253fd6a…` failed before any server or Invoke: the runner attempted a second
exclusive write of its configuration file. The build and failed output remain
preserved. Both lifecycle arms at that source passed. The runner correction
constructs the configuration in memory and writes once; fresh exact-source
builds and both smoke/full populations use the revisions reported above.

The diagnostic's longer transport allowance permits native cleanup to be
observed; it does not establish post-disconnect capacity recovery. Quarantine
remains appropriate when safe reuse lacks proof, and
[#119](https://github.com/KirilsTurkins/latent-service-fabric/issues/119) remains
a separate P0 requirement for the final extension gate. Seven paired processes
provide descriptive same-host observations, not statistical significance,
arbitrary-duration leak freedom or a production SLO. This focused profile does
not replace the earlier full optimization baseline or scale/soak evidence.

## Reproduction and retained evidence

The clean Linux harness ran from `/workspace/project`. Build-only used
`--experiment budget --profile full --build-only`, the exact three refs above,
`--target-root /workspace/optimization-budget-builds`,
`--output /workspace/project/target/optimization-budget/build-only-external-02`
and `--backend-build-output /workspace/project/target/optimization-budget/build-only-lifecycle-02`.
Both untouched build graphs were copied to fresh `external-smoke-02`,
`external-full-02`, `lifecycle-smoke-02` and `lifecycle-full-02` before collection.
The [method](../../../../docs/testing/phase-1-measurements.md#short-budget-revision-experiments)
contains the full build and fresh-copy commands. Successful full commands were:

```sh
python tools/run_optimization_revision_benchmarks.py --experiment budget --profile full \
  --builds /workspace/project/target/optimization-budget/external-full-02/revision-builds.json \
  --target-root /workspace/optimization-budget-data
python tools/run_optimization_backend_revision.py --experiment budget --profile full \
  --builds /workspace/project/target/optimization-budget/lifecycle-full-02/backend-builds.json \
  --target-root /workspace/optimization-budget-data
```

The [external aggregate](external/aggregate.json) and
[lifecycle aggregate](lifecycle/aggregate.json) are derived from their complete
raw suites. Both archives retain original attempts/events, plans, component and
metadata bytes, exact binaries, common source/build inputs and resource/process
cleanup receipts. Packaging used `--compression-level 9 --split-archive` into
`target/optimization-budget/publication-e25b609/{external,lifecycle}`. The ordered
parts preserve the full logical gzip stream; no binary was stripped or omitted.

| Package | Retained files | Expanded bytes | Logical gzip bytes | Parts |
| --- | ---: | ---: | ---: | ---: |
| [External manifest](external/raw-evidence.manifest.json) | 1,661 | 481,646,146 | 103,938,284 | [3](external/raw-evidence.parts.json) |
| [Lifecycle manifest](lifecycle/raw-evidence.manifest.json) | 417 | 416,615,541 | 95,182,667 | [2](lifecycle/raw-evidence.parts.json) |

Logical gzip SHA-256:

- External: `ae03201f00cf04f919b5a26576b092faa15b9c4f7564d747ef50628c1a885717`.
- Lifecycle: `9a8edf1ca5d165b68427021b21b8911130fc8861677ff211053f4b2f9803b9b2`.

Both packages passed mandatory Linux full semantic replay and independent
Windows archive replay. Recheck them without executing any retained binary:

```sh
python tools/validate_phase1_archive.py \
  benchmarks/optimization/precise-budgets/2026-09-09-container-linux-e25b609/external
python tools/validate_phase1_archive.py \
  benchmarks/optimization/precise-budgets/2026-09-09-container-linux-e25b609/lifecycle
```
