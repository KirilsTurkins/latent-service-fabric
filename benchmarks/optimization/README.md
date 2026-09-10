# Phase 1 optimization measurements

The [Phase 1 extension](https://github.com/KirilsTurkins/latent-service-fabric/issues/97)
uses a separate native Rust/tonic service and a standalone `latentd` process.
Both execute the same pure Rust Echo, bounded compute and structured transform
logic from `tools/optimization-workloads`. The maintained Wasm component wraps
those functions; the native reference uses their JSON framing adapter. The same
external client sends the same protobuf requests over one persistent connection
per case. Native means native code in the recorded environment, not bare metal.

The [clean pre-optimization reference](reference/2026-09-08-container-linux-8bbc1fd/REPORT.md)
retains seven alternating pairs and all 88,326 attempts. Its report includes
unmet latency/budget targets and links to the separately retained rejected
configuration attempt. Verify the complete archive with:

```sh
python3 tools/validate_phase1_archive.py \
  benchmarks/optimization/reference/2026-09-08-container-linux-8bbc1fd
```

Run the bounded smoke profile on Linux, including a declared Linux container:

```sh
python3 tools/run_optimization_benchmarks.py --profile smoke
```

The runner builds the pinned binaries and real component, publishes five actual
component identities, and starts independent measured servers. It owns all child
processes, bounds output and execution time, records clean shutdown, and retains
failed attempts and original logs. Output directories must be new and empty.
CI runs smoke; smoke validates the protocol and cannot establish performance.

Explicit full collection requires a clean source checkout:

```sh
python3 tools/run_optimization_benchmarks.py --profile full
python3 tools/validate_optimization_evidence.py target/optimization-benchmarks/full-.../suite.json \
  --check-aggregate target/optimization-benchmarks/full-.../aggregate.json
```

The full profile collects seven independent pairs, alternating arm order. Each
server serves the same fixed ordered case matrix: warm Echo, compute, transform,
64 KiB and near-transfer-limit payloads,1/2/5/10 ms deadlines, concurrency4/16/64,
scheduled arrivals at250/1000/4000 requests per second, and a five-component
working set against four cache slots. Closed-loop throughput uses whole-batch
elapsed time. Scheduled load records dispatch lag and explicit client overload
or expired arrivals; it never silently reduces the attempted population.

The120 KiB near-limit string stays below the current128 KiB Component Model
lifting allowance. The standalone RPC ceiling is1 MiB and the JSON string cap
is256 KiB. These are different limits. Results state effective configuration;
the benchmark does not raise product limits to make a payload succeed.

The first invocation after durable restart includes preparation. Process-to-first
response is a parent-observed upper bound that includes readiness observation,
client startup and connection setup. Raw client startup/connect and per-call
timings remain separate. This does not measure pure compiler time or image pull
time. Subsequent warm samples follow explicit warmup. The working-set case uses
five distinct valid component binaries with identical code and different custom
sections, so it exercises actual cache replacement.

Each attempt retains identity, outcome, response identity/hash, deadline and
timings, including failures and outliers. RPC latency begins after request
construction and includes channel readiness, encoding, network and server work;
client response hashing and output writing occur afterward. Scheduled-to-complete
latency also includes dispatch delay and retains undispatched offers. Successful
responses, all dispatched attempts and individual failure classes have separate
distributions. Paired successful-call deltas never substitute fast rejections
for successful responses. Resource snapshots distinguish the
server and client;100 ms RSS observations are sampled maxima. Shared local
cgroup CPU/memory/pressure counters are retained as raw observations and are not
attributed wholly to one service. CPU ticks and wall latency are distinct.

After completing and persisting its timed work, the client holds for100 ms so
the parent can sample its live memory before it exits. The parent ends the
resource interval when it receives that completion event. This observation
window is excluded from request and batch timings. Controller counters come
from the resolved runner cgroup; the recorded leaf limits do not establish
effective limits imposed by ancestors.

The fixture uses four cells and64 queue slots. Its512 MiB journal allowance
accommodates conservative accounting for68 reservations; this is a finite
retention ceiling, not a512 MiB allocation or RSS measurement. The runner clips
all measured child lifetimes to a shared execution deadline and reserves their
bounded output before starting each batch. Build time has a separate one-hour
watchdog. Source, lockfile and recipe identities are checked before/after build
and again after collection.

The native reference has authentication, bounded invocation admission and
deadline checks. LSF additionally performs catalog/routing, fresh Wasm isolation,
capability enforcement, fuel/memory accounting, scheduling and lifecycle/status
retention. These treatment differences are part of the comparison. They are not
silently equated. No failure data is discarded to claim a faster successful-call
latency. Valid workload outputs must match across both arms.

Cases run in a fixed order on the same server within each arm. Cache contents,
journal entries and any quarantined cells can therefore affect later cases.
Clean shutdown establishes reclaimed ownership; the retained quarantine count
separately describes lost serving capacity. Process resource intervals include
client startup, connection setup and warmup through the completion observation,
so their CPU deltas are not measured-only per-call costs. Native admission uses
four executing slots and two runtime workers; LSF also has64 queue slots and two
control workers. These configurations describe the compared systems explicitly.

This protocol supplies the baseline for optimization tickets. Real Docker and
Kubernetes deployment comparisons are tracked separately in
[#111](https://github.com/KirilsTurkins/latent-service-fabric/issues/111) and
[#112](https://github.com/KirilsTurkins/latent-service-fabric/issues/112).
Original Phase0 and Phase1 evidence remains immutable under `benchmarks/phase0`
and `benchmarks/phase1`. Engineering targets and their final evaluation belong to
the extension epic and final gate; protocol validation alone is not an
optimization result or a production capacity claim.

## Artifact identity and catalog recovery

The retained [2026-09-08 comparison](artifact-identity/2026-09-08-container-linux-95a53b1/REPORT.md)
completed all 252 full measurements. With 64 MiB components, median artifact
recovery fell from 309 ms to 53 ms and combined recovery/catalog loading from
861 ms to 104 ms. Candidate profiled peak heap for these operations was 0.12 MiB
and 0.20 MiB respectively. The report distinguishes normal CPU/RSS from separately
profiled heap usage and links the complete replayable evidence.

The [artifact identity comparison](https://github.com/KirilsTurkins/latent-service-fabric/issues/99)
uses the identical auxiliary Rust probe on clean control and candidate commits.
On Linux with Heaptrack 1.4 and zstd installed, set `CONTROL_REF` and
`CANDIDATE_REF` to their full commit hashes, and `COMPONENT`, `CAPSULE` and
`CONTRACTS` to one matching generated optimization component and its metadata:

```sh
python3 tools/run_artifact_identity_benchmarks.py --profile full \
  --control-ref "$CONTROL_REF" --candidate-ref "$CANDIDATE_REF" \
  --component "$COMPONENT" --capsule "$CAPSULE" --contracts "$CONTRACTS" \
  --output target/artifact-identity/full-reference
python3 tools/validate_artifact_identity_evidence.py \
  target/artifact-identity/full-reference/suite.json \
  --check-aggregate target/artifact-identity/full-reference/aggregate.json
```

Fixture generation runs separately, validates the actual component, and appends
legal custom sections to produce exact 16 MiB and 64 MiB variants alongside the
original small fixture. Each fixture has one published release and deployment.
Seven alternating pairs cover byte-slice hashing, artifact repository recovery,
and combined artifact recovery plus deployment catalog reopening/compilation.
Normal and separately instrumented allocation runs total 252 measured processes.
`--profile smoke` uses one pair and the small fixture to check the protocol.

Hash input reads occur before its timer; full hash runs repeat the operation up
to 4,096 times to amortize short durations. Repository operations run once per
process. Timing excludes post-operation identity checks and the 100 ms live
observation hold. CPU is whole-process user/system time, RSS includes process
libraries and input buffers, and Heaptrack allocation/peak records come from
separate processes. Files receive a declared sequential read before every run;
this is best-effort warm filesystem evidence, not a cold-disk benchmark.

Package a qualified full comparison into a new destination and replay it without
executing any retained binary:

```sh
python3 tools/package_phase1_evidence.py \
  --source target/artifact-identity/full-reference \
  --output target/artifact-identity/reference-package
python3 tools/validate_phase1_archive.py target/artifact-identity/reference-package
```

The archive retains original binaries, fixtures, profiles and receipts with exact
hashes. Packaging requires successful full-population replay and does not add a
measurement policy or a historical comparison from another protocol. Existing
Phase 0, Phase 1 and optimization baseline evidence remains unchanged.

## Bounded cold preparation

The [retained cold preparation comparison](cold-preparation/2026-09-08-container-linux-368d621/REPORT.md)
accounts for 11,942 Invoke attempts across seven alternating process pairs.
Same-key cold success changed from 14/56 to 56/56. During distinct cold bursts,
median per-process successful warm p99 changed from 70.824 ms to 1.824 ms, while
the candidate rejected 7/35 cold offers at its preparation bound. The report
retains those rejections, cancellation outcomes, compiler task CPU, the added
worker threads and slightly higher RSS; it does not claim faster compilation.

This separate `--experiment cold` protocol uses matched release binaries and a
common in-process RPC client/observer. It is distinct from the standalone
external-client baseline. The report provides exact source/build identities,
collection and replay commands, limitations and the complete raw archive.

## Prepared cache lookup and runtime ownership

The [retained prepared-cache comparison](prepared-cache/2026-09-09-container-linux-7e03a2f/report.md)
contains 168 lookup probe processes and 14 real-node behavior processes. Lookup
elapsed time and thread CPU are lower in 41/42 normal pairs; separately verified
measured-hit allocations change from one allocation / 14 bytes to zero. The
five-component/four-slot experiment confirms held-runtime accounting and final
retirement. Warm baseline p50 changes from 0.725 ms to 0.709 ms, while churn
latency is mixed and observed node RSS is slightly higher.

The report separates lookup, complete invocation, allocator and process-resource
boundaries. Both archives retain complete raw evidence and passed Linux and
independent Windows replay. Replay them without executing retained binaries:

```sh
python3 tools/validate_phase1_archive.py \
  benchmarks/optimization/prepared-cache/2026-09-09-container-linux-7e03a2f/lookup
python3 tools/validate_phase1_archive.py \
  benchmarks/optimization/prepared-cache/2026-09-09-container-linux-7e03a2f/behavior
```

## Precise budget experiments

The [retained precise-budget comparison](precise-budgets/2026-09-09-container-linux-e25b609/README.md)
completed 24,976 offers across separate external and lifecycle populations.
At 2 ms, useful successes rose from 2,634/2,800 to 2,794/2,800, meeting the 99%
target. The report retains the unsuccessful 1 ms population, mixed tail latency,
remaining native interruption delay and the separate disconnect-cleanup limit.

The [#103 protocol](https://github.com/KirilsTurkins/latent-service-fabric/issues/103)
uses `--experiment budget` on the existing revision and backend runners. Both
variants execute LSF. A shared external client measures useful short-budget
work; a separate 23-offer node diagnostic records actual deadline lineage,
queueing, interruption, cancellation and owned wait guards. The
[collection method](../../docs/testing/phase-1-measurements.md#short-budget-revision-experiments)
describes one exact-source build, fresh smoke/full copies and independent replay.

Full collection has 24,654 external offers and 322 diagnostic offers across
seven alternating pairs. External prewarm and warmup remain retained but are
excluded from the four measured populations. The 2 ms target requires at least
2,772 of all 2,800 measured offers per variant to return a semantically correct
response observed on time. Successful replay and target attainment are separate
results; failures and late successes remain in the denominator.

| Evidence | Plan | Builds | Suite | Aggregate |
| --- | --- | --- | --- | --- |
| External RPC | [plan](budget-plan.schema.json) | [builds](budget-builds.schema.json) | [suite](budget-suite.schema.json) | [aggregate](budget-aggregate.schema.json) |
| Lifecycle diagnostic | [plan](budget-lifecycle-plan.schema.json) | [builds](budget-lifecycle-builds.schema.json) | [suite](budget-lifecycle-suite.schema.json) | [aggregate](budget-lifecycle-aggregate.schema.json) |

The schemas provide structural bounds; replay additionally checks all offered
attempts, source/artifact identities, deadlines, ownership and cleanup. Diagnostic
runaway and short-cancel cases use a 1,000 ms transport allowance around their
1/2/5/10 ms native wall grants. External requests and queued/delayed-body cases
retain their short transport deadlines. This distinction does not resolve
[#119](https://github.com/KirilsTurkins/latent-service-fabric/issues/119), which
tracks bounded cleanup and capacity recovery after a running transport disconnect.

## Transport interruption recovery

The [retained transport-cleanup comparison](transport-cleanup/2026-09-09-container-linux-ee10b02/README.md)
shows 30/30 successful recovery calls versus 5/30 in the control, without a node
restart. Its seven warm pairs have mixed timing changes and retain the observed
RSS increase; both complete evidence packages passed Linux and Windows replay.

The [#119 protocol](https://github.com/KirilsTurkins/latent-service-fabric/issues/119)
uses `--experiment recovery` on the existing revision runners. Its external warm
profile retains 6,174 offers across seven pairs to observe ordinary request
overhead. A separate single recovery pair retains 122 offers, including repeated
short expiry/disconnect attempts, five planned Running-triggered disconnect cases per arm,
explicit cancellation and thirty same-process recovery calls per arm. Neither
arm restarts its four-cell node or enlarges the pool during this population.

| Evidence | Plan | Builds | Suite | Aggregate |
| --- | --- | --- | --- | --- |
| External warm RPC | [plan](transport-warm-plan.schema.json) | [builds](transport-warm-builds.schema.json) | [suite](transport-warm-suite.schema.json) | [aggregate](transport-warm-aggregate.schema.json) |
| Recovery diagnostic | [plan](recovery-plan.schema.json) | [builds](recovery-builds.schema.json) | [suite](recovery-suite.schema.json) | [aggregate](recovery-aggregate.schema.json) |

The [collection and replay method](../../docs/testing/phase-1-measurements.md#transport-interruption-recovery)
defines source controls, fixed populations and the separate transport, native
cleanup and resource boundaries. Structural schemas do not replace strict raw
replay. Historical budget evidence remains unchanged, and functional debug
fixtures do not qualify as release benchmark results.

## Request ownership experiments

The [retained request-ownership comparison](request-ownership/2026-09-09-container-linux-2bd2452/README.md)
proves raw-vector release before guest dispatch and lower near-limit context
setup time. It accepts an explicit ownership tradeoff: across two RPC campaigns,
warm Echo's paired p50 increases by 37.451 us (9/14 pairs higher), and observed
warm server CPU rises 5.7%. All twelve selected allocation attributions remain
unavailable. The report retains both campaigns, the whole-process allocation
results and the unresolved warm-performance concern carried into #105/#106.

The [#104 protocol](https://github.com/KirilsTurkins/latent-service-fabric/issues/104)
uses `--experiment ownership` on the existing revision runners. It separates
three unchanged external payload cases from direct Wasmtime invocations, two
observed pending-future proofs and independently profiled allocation children.
Full collection retains 16,096 calls; smoke retains 164. There is no additional
prewarm invocation or candidate-adapted input.

| Evidence | Plan | Builds | Suite | Aggregate |
| --- | --- | --- | --- | --- |
| External payload RPC | [plan](ownership-rpc-plan.schema.json) | [builds](ownership-rpc-builds.schema.json) | [suite](ownership-rpc-suite.schema.json) | [aggregate](ownership-rpc-aggregate.schema.json) |
| Direct ownership and allocations | [plan](ownership-plan.schema.json) | [builds](ownership-builds.schema.json) | [suite](ownership-suite.schema.json) | [aggregate](ownership-aggregate.schema.json) |

The [collection and replay method](../../docs/testing/phase-1-measurements.md#request-ownership-experiments)
defines the exact source controls, control-generated context fixtures and the
distinct timing, logical ownership, allocator and process-memory boundaries.
The schemas bound structure; strict replay and the linked report establish
the retained populations and qualified results.

## Typed codec experiments

The [retained typed-codec comparison](typed-codec/2026-09-09-container-linux-9a2749f/README.md)
reports lower warm Echo p50 and server CPU against its matched control, with
mixed payload/tail results and higher sampled RSS. Its separate codec batches
show lower decode CPU for structured values while preserving small string
regressions. The report separates batch averages, RPC quantiles, selected
allocator traffic and process memory, and retains the first incomplete
collection's limit failure.

The [#105 protocol](https://github.com/KirilsTurkins/latent-service-fabric/issues/105)
uses `--experiment codec` on the existing revision runners. Five unchanged
external cases retain 140 calls in smoke or 25,256 across seven full pairs.
A separate no-guest codec collector covers six fixed value families in normal
and profiled children: 24 children/432 codec operations in smoke, or
168 children/449,680 operations in full. Preflight, warmup and measured calls
remain separately counted.

| Evidence | Plan | Builds | Suite | Aggregate |
| --- | --- | --- | --- | --- |
| External RPC | [plan](codec-rpc-plan.schema.json) | [builds](codec-rpc-builds.schema.json) | [suite](codec-rpc-suite.schema.json) | [aggregate](codec-rpc-aggregate.schema.json) |
| Codec batches and allocations | [plan](codec-plan.schema.json) | [builds](codec-builds.schema.json) | [suite](codec-suite.schema.json) | [aggregate](codec-aggregate.schema.json) |

The [collection and replay method](../../docs/testing/phase-1-measurements.md#typed-codec-experiments)
defines exact source controls, independent fixture reconstruction, actual batch
CPU/elapsed boundaries and selected allocation-origin attribution. Batch
averages are separate from RPC latency quantiles; unavailable frame attribution
is never reported as zero. These schemas describe the protocol and do not
establish a measured performance result.

Codec-only evidence explicitly allows a 2 GiB retained root and 12,000,000
interpreted profile records, preserving its full fixed population after the
first incomplete collection exceeded the original limits. Other experiments,
including codec RPC, retain the 1 GiB/4,000,000-record defaults. Archive selection
binds the bounded outer codec aggregate to the archived kind and full replay;
256 MiB files and the existing compressed transport caps remain unchanged.

## Engine profile experiments

The [retained engine-profile comparison](engine-profiles/2026-09-09-container-linux-fbb6e26/README.md)
contains 6,160 external RPC calls and 27,790 matrix calls, including every
intentional fault. Pooling/speed reduced warm setup by a paired 16–29 us across
the four workloads, with all seven pairs lower. It increased first-call latency,
sampled RSS and compiled-image charges while reducing virtual-memory high-water
usage. Speed-and-size did not reduce image charges for these fixtures. The
on-demand/speed default remains unchanged; the report retains mixed external
tails, execution-order effects and all earlier failed attempts.

The [#106 protocol](https://github.com/KirilsTurkins/latent-service-fabric/issues/106)
uses `--experiment engine` on the existing exact-revision runners. A separate
external warm Echo comparison retains 32 calls in smoke or 6,160 across seven
full pairs. The matrix uses one old default and four candidate allocator/compiler
profiles per block, with fixed rotation and reversal. Each owner retains
52/794 Invokes in smoke/full, including all 24 functional calls; full matrix
collection contains 35 owners and 27,790 Invokes. Three configuration contrasts
share each block's actual candidate D0 baseline.

| Evidence | Plan | Builds | Suite | Aggregate |
| --- | --- | --- | --- | --- |
| External warm RPC | [plan](engine-warm-plan.schema.json) | [builds](engine-warm-builds.schema.json) | [suite](engine-warm-suite.schema.json) | [aggregate](engine-warm-aggregate.schema.json) |
| Engine profile matrix | [plan](engine-plan.schema.json) | [builds](engine-builds.schema.json) | [suite](engine-suite.schema.json) | [aggregate](engine-aggregate.schema.json) |

The [collection and replay method](../../docs/testing/phase-1-measurements.md#engine-profile-experiments)
defines fixed source/configuration controls, functional reset and reclamation
proofs, and distinct RPC, backend, CPU and memory boundaries. Measurement-local
virtual/resident observations retain unavailable reasons. Both evidence kinds
keep the 1 GiB root and existing archive caps. These protocol schemas do not
establish measured performance results or a universal SLO.

## Catalog memory experiments

The [#107 protocol](https://github.com/KirilsTurkins/latent-service-fabric/issues/107)
uses `--experiment catalog` on the backend build, run and validation tools.
Both sources publish the same distinct releases, with separate distinct-service
and shared-service shapes. Full collection grows each catalog through 100,
1,000, 10,000 and 100,000 deployments, then updates a pinned generation and
reopens the same durable state in a new process. It has one matched pair per
shape; smoke has three tiny pairs per shape.

| Evidence | Plan | Builds | Suite | Aggregate |
| --- | --- | --- | --- | --- |
| Catalog growth, reopen and resolver allocations | [plan](catalog-plan.schema.json) | [builds](catalog-builds.schema.json) | [suite](catalog-suite.schema.json) | [aggregate](catalog-aggregate.schema.json) |

The [collection method](../../docs/testing/phase-1-measurements.md#catalog-memory-experiments)
separates primary idle RSS, artifact-only memory, pinned generations, sampled
compilation peaks, public resolver latency and tiny allocation profiles.
The full campaign contains 596,720 counted API operations and zero Invokes.
The 25% RSS reduction and 1.75 GB reference-shape ceiling are separate targets;
successful semantic replay does not establish either target or a universal
infrastructure capacity claim.
