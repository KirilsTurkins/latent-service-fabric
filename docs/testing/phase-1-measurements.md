# Phase 1 scale, soak and benchmark measurements

These collectors exercise the actual standalone composition separately from the
[bounded conformance profile](phase-1-conformance.md). The default `smoke`
profile validates the collectors. Full evidence requires explicit `--profile full`.
Neither a smoke report nor a passing benchmark closes the Phase 1 gate by itself.

## Build and run

Use Linux and the [pinned toolchain](../development/toolchain.md). Build the
maintained echo, generic and capabilities components first:

```sh
unset CARGO_INCREMENTAL
bash tools/build_phase1_measurement_fixtures.sh
python3 tools/run_phase1_measurements.py
```

The default runs each collector once with small fixtures. Required contracts CI
also runs this smoke profile after the existing component and conformance tests.
Missing fixtures, failed builds, exceeded bounds, incomplete raw output and
failed cleanup are failures, with available diagnostics retained.

Select a full category explicitly:

```sh
python3 tools/run_phase1_measurements.py --profile full --kind scale
python3 tools/run_phase1_measurements.py --profile full --kind soak
python3 tools/run_phase1_measurements.py --profile full --kind benchmark
```

`--kind all` runs all three sequentially. Each invocation creates a new
`target/phase1-measurements/<profile>-*` directory. `--output PATH` accepts a new
or empty directory, and `--target-root PATH` selects the Cargo target directory
containing the built fixtures. Evidence is never overwritten. `--repetitions`
can increase independent repetitions, up to 21; it cannot reduce full-profile
minimums.

| Category | Smoke | Full |
| --- | --- | --- |
| Scale | 2 and 4 releases/deployments; 16 route samples per checkpoint | 100, 1,000, 10,000 and 100,000; 10,000 route samples per checkpoint |
| Soak | 4 warmup and 20 measured Invokes | 1,000 warmup and 100,000 measured Invokes per independent process |
| Benchmark | 4 samples per repeated boundary | 400 samples per repeated boundary |
| Independent processes | One per category | Scale: one; soak: three; benchmark: seven |
| Build | Debug collector, release guest fixtures | Pinned release collector and guest fixtures |

The benchmark includes multiple boundaries and fault/recovery scenarios, so its
sample count is not its total Invoke count. The raw report records actual work. A benchmark process attempts 85 Invokes in
smoke and 8,440 in full. A soak process attempts 24 or 101,000 respectively,
including warmup. Scale issues no Invokes; its full setup and lookups count
140,004 commands. Command counts cover dispatched RPCs and explicit scale
publish/apply/resolve calls; snapshots and backend preparation/release have
separate bounded samples.
The existing conformance limits of 64 Invoke attempts and 256 commands continue
to apply to that separate profile.

The explicit [Phase 1 measurements workflow](../../.github/workflows/phase1-measurements.yml)
defaults to smoke. It can select a full category or run categories in separate
jobs. Hosted CI measurements retain their host identity and are observations;
they do not establish a native reference or enforce latency thresholds. Reports
and failure diagnostics are retained for 30 days.

## Ownership and measurement boundaries

The ignored Linux collector assembles the same standalone node as product
startup. Test instrumentation retains its real catalogs, resolver, manager,
scheduler and backend; no measurement RPC or product configuration bypass is
added. The test process also owns its persistent generated RPC client. Its
fixed libtest/client overhead is included in process resources and identified
separately from node inventory. It must not be described as an external client
or a process containing only `latentd`.

Each independent collector runs in a disposable process group supervised by the
Python parent. Logs are capped at 4 MiB. Structured evidence is capped at 8 MiB
for smoke and 128 MiB for full. Smoke has a 90-second execution watchdog; full
has a six-hour watchdog per process. The build has a separate one-hour bound.
Failure terminates and reaps the owned process; successful completion also
requires the actual node shutdown evidence.

The parent owns a separate temporary data root outside the evidence directory.
After shutdown the collector explicitly removes its catalog directory; after
reaping the process the parent removes the remaining temporary root, including
on failure. Raw reports retain both cleanup witnesses and the parent's actual
PID/start-time/exit receipt. Large catalog files are not uploaded as diagnostics.

Scale registration uses the actual durable artifact and deployment stores.
Bounded deployment batches avoid rebuilding the route snapshot once per entry.
This is trusted local setup, with its own timing; management publish/apply RPC
latency is measured separately. Route lookup times the actual resolver, rather
than using the management snapshot RPC as a proxy. Samples report fixed
node-owned topology, dormant-service ownership, cells, queue, caches, RSS,
descriptors, threads, sockets and descendants. Persisted catalog metadata can
grow with registration count; zero dormant execution allocation does not mean
zero storage or catalog memory.

Soak uses repeated mixed outcomes through the generated RPC client, with a
bounded number of outstanding calls. Warmup and measured work are distinct.
Resource checkpoints are taken after batches have drained. The report retains
work counts, terminal outcomes, consumption and observations used to assess
reclamation. Missing OS measurements are unavailable evidence, never zeroes.
Actual cancellation registrations, journal occupancy/reservations, observer
correlations and bounded telemetry retention are sampled between batches.
No general kernel timer counter is invented.

The initial [reclamation policy](../../benchmarks/phase1/measurement-policy.json)
uses the retained Phase 0 allowances: idle RSS at most 64 MiB above the fully
warmed baseline and at most two additional descriptors. All transient owner
counts must still return to zero. Full warmup covers the complete mixed cycle;
analysis retains every batch, peaks and first/last ten-batch observations.
These are explicit observational limits, with no outlier removal or claim of
arbitrary-duration leak freedom. Smoke reports do not qualify a memory plateau.

Benchmark boundaries distinguish RPC elapsed time, scheduler/admission work,
backend preparation, guest execution and cleanup. One initial engine-cold compilation is separate from repeated cache-reset
preparation and warm cache hits. Startup records catalog opening, node startup
with open catalogs, and client connection separately; fixture loading and outer
runtime creation are excluded.

Current preparation samples call `ExecutionBackend::prepare_from_repository`
against the published directory source. Their raw `benchmark-prepare` records
set `scope` to `repository-acquisition-including-verified-refill`: a cold sample
includes checked repository refill and preparation; a hit measures acquisition
of the verified cached snapshot. Fixture comparison reads occur outside that
timer. Earlier archives retain their original direct-artifact preparation
boundary and source identity; the new scope must not be retroactively assigned
to those samples.

Backend intervals, including `backend_total_micros`, begin inside execution and
exclude activation materialization. RPC elapsed includes the wider path. The
separate #100 current/current backend diagnostic uses
`phase1_revision_backend_collector` and `tools/run_optimization_backend_revision.py`:
its first real RPC starts with an empty prepared cache and belongs to the declared
warmup population. It performs no manual preparation before that call. Its
`warmup_method` is `first-rpc-empty-cache-in-declared-warmup`; its distinct schema
keeps it separate from the historical/current comparison. Cold materialization
is visible in that RPC interval, not in a fabricated backend-total interval.

The retained [verified warm activation comparison](../../benchmarks/optimization/warm-activation/2026-09-08-container-linux-56303c5/REPORT.md)
contains seven paired external-client runs and a separate seven-pair backend
diagnostic. It reports warm latency gains, cache-refill regressions and the
remaining tight-budget failures. Its two archives replay independently; these
observations do not replace the original Phase 1 scale and soak evidence.

`tools/package_phase1_evidence.py` retains gzip level 6 by default and accepts
`--compression-level 9` for denser lossless packaging. `--split-archive` stores
the same gzip stream in two to four parts of at most 50 MB, bounded to 198 MB
total. Ordinary archives retain their 99 MB cap. Both forms keep the 5,000-file
limit and require full evidence replay. The expanded default remains 1 GiB;
only the explicitly identified [codec-only evidence](#typed-codec-experiments)
permits 2 GiB. The validator checks ordered part identities, the reconstructed
archive and the aggregate that selects the bound before extraction.

The two-call batch records offered concurrency. The queue batch proves two
running holders and three queued waiters, then cancels the holders to release
the waiters. Scheduler observations are actual grant/wait counter deltas for
the complete batch. They are not per-call scheduling quantiles. Batch throughput
uses measured elapsed time, including control and retained-status validation.
Management timings cover idempotent publication and durable reapplication, with
an independent on-disk checksum/generation witness outside the RPC timer.
Individual cell-disposition time is unavailable and is not derived by
subtracting unrelated timings. Timing observations are not release promises.

## Evidence and comparison

Each process writes bounded `measurements.jsonl` records and a convenience
`summary.json`. The parent retains its exact plan, source commit/tree and dirty
state, Cargo lock digest, collector/fixture digests, build recipe, host
observations and logs. `suite.json` binds raw files and auxiliary artifacts by
hash. Nine small canonical capsule/contract/deployment files bind the metadata
actually supplied to the collector, alongside hashes of the loaded components.
The schemas live under [benchmarks/phase1](../../benchmarks/phase1).

The full collector reuses the retained Phase 0 build helper's pinned release
recipe. This does not change the historical receipts or make a Phase 1 run a
Phase 0 run. A dirty checkout is recorded as dirty and cannot establish an
unmodified published revision.

Aggregate selected categories, including runs collected on different hosts:

```sh
python3 tools/aggregate_phase1_evidence.py \
  --suite /evidence/scale/suite.json \
  --suite /evidence/soak/suite.json \
  --suite /evidence/benchmark/suite.json \
  --output /evidence/aggregate.json
```

Completeness is evaluated per category. A benchmark reference requires seven
compatible independent benchmark processes. Scale and soak evidence can retain
their own environments without being averaged into benchmark measurements.
Small profiles, missing runs and failed invariants cannot qualify as full
evidence.

The retained August 30 Phase 0 reference was measured on a native Ryzen 3 3200G
Linux machine. A matched comparison requires compatible host, toolchain, build,
inputs, configuration, units and metric boundaries. The comparison retains
both observations and explicit incompatibility reasons when these differ; it
does not manufacture a productionization delta from unrelated measurements.
The generic Phase 1/RPC composition also changes some boundaries deliberately.
Those changes remain visible in the comparison and completion report.

The separate [controlled historical/current experiment](phase-1-controlled-comparison.md)
runs the original runtime and current node on one observed environment, using
identical maintained Echo source and fixed semantic workloads. It measures the
declared production changes while preserving the August reference and this
comparator's strict compatibility rules. Unmatched historical observations alone
do not satisfy the gate's requested productionization comparison.

Validate retained artifacts again, or produce the comparison from a benchmark
aggregate and the checked-in Phase 0 aggregate:

```sh
python3 tools/validate_phase1_evidence.py --aggregate /evidence/aggregate.json
python3 tools/compare_phase1_evidence.py \
  --phase1 /evidence/aggregate.json \
  --phase0 benchmarks/phase0/calibration/native-linux-2026-08-30-52ac4754/aggregate.json \
  --output /evidence/comparison.json
python3 tools/validate_phase1_evidence.py --comparison /evidence/comparison.json
```

Use the actual retained reference path in the checkout. The optional
`--phase0-runs /path/to/extracted/runs` revalidates historical raw runs to derive
matching warm-echo populations; the published Phase 0 aggregate pools some
outcomes. Keep the candidate aggregate under the comparison output's parent.
The comparison copies and hashes its Phase 0 reference there. Validation
recomputes derived statistics from bound inputs, including on replay.

## Short-budget revision experiments

Issue [#103](https://github.com/KirilsTurkins/latent-service-fabric/issues/103)
adds a separate `--experiment budget` profile to the existing revision runners.
The external experiment uses the unchanged optimization client and component
against two LSF revisions. The lifecycle experiment uses the same bounded
23-offer diagnostic collector and generic component on both revisions. Their
[schemas](../../benchmarks/optimization/README.md#precise-budget-experiments),
raw populations and aggregates are separate from the earlier warm, cold and
cache profiles.

Start from the clean declared harness checkout. Set `CONTROL_REF`,
`CANDIDATE_REF` and `HARNESS_REF` to full 40-character commits whose common
collector, client, fixture and build-policy inputs match. The build-only mode
builds each server and optional diagnostic binary once, plus the shared client,
CLI and required components. Its build parent must be outside the repository
and any ancestor with a hidden Cargo configuration. All output paths below must
be absent before use.

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment budget --profile full \
  --control-ref "$CONTROL_REF" --candidate-ref "$CANDIDATE_REF" --harness-ref "$HARNESS_REF" \
  --target-root /workspace/optimization-budget-builds \
  --output target/optimization-budget/build-only-external \
  --backend-build-output target/optimization-budget/build-only-lifecycle --build-only

# Copy both complete build graphs before either smoke writes observations.
python3 - <<'PY'
from pathlib import Path
from shutil import copytree
root = Path("target/optimization-budget")
for kind in ("external", "lifecycle"):
    for profile in ("smoke", "full"):
        copytree(root / f"build-only-{kind}", root / f"{kind}-{profile}")
PY

python3 tools/run_optimization_revision_benchmarks.py --experiment budget --profile smoke \
  --builds target/optimization-budget/external-smoke/revision-builds.json \
  --target-root /workspace/optimization-budget-data
python3 tools/run_optimization_backend_revision.py --experiment budget --profile smoke \
  --builds target/optimization-budget/lifecycle-smoke/backend-builds.json \
  --target-root /workspace/optimization-budget-data
```

Both smoke suites must pass complete semantic replay before full collection.
Smoke checks 65 external and 23 diagnostic offers per variant; it does not
qualify the performance target. Run the fresh full copies serially:

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment budget --profile full \
  --builds target/optimization-budget/external-full/revision-builds.json \
  --target-root /workspace/optimization-budget-data
python3 tools/run_optimization_backend_revision.py --experiment budget --profile full \
  --builds target/optimization-budget/lifecycle-full/backend-builds.json \
  --target-root /workspace/optimization-budget-data
python3 tools/validate_optimization_revision_evidence.py \
  target/optimization-budget/external-full/suite.json \
  --aggregate target/optimization-budget/external-full/aggregate.json
python3 tools/validate_optimization_backend_revision.py \
  target/optimization-budget/lifecycle-full/suite.json \
  --aggregate target/optimization-budget/lifecycle-full/aggregate.json
```

Prebuilt collection validates the exact retained build graph and executed
harness identity. It refuses reused measurement directories. Preserve failed
attempts; use a fresh copy of the untouched build-only graph for a retry.
Package each qualified full root independently with
`tools/package_phase1_evidence.py` and replay each package with
`tools/validate_phase1_archive.py`. The existing archive bounds and explicit
split transport apply; replay never executes retained binaries.

Each full external arm has one explicit prewarm, then 40 warmup and 400 measured
offers at each of 1, 2, 5 and 10 ms: 1,761 offers per arm and 24,654 across seven
pairs. The explicit prewarm and all warmup remain in raw evidence. The target
is at least 99% semantically successful, client-observed on-time responses among
all 2,800 measured 2 ms offers per variant. Failed, undispatched and late offers
are not removed. Complete replay establishes evidence validity; the aggregate's
separate target result establishes whether that threshold was attained.

Conditional successful-response latency, all-dispatched latency and all-offered
elapsed time remain distinct. Throughput uses first scheduled offer through last
completed attempt. Server and client CPU/RSS are observed separately over the
batch including warmup and observer overhead, so these are not measured-only
per-call CPU costs. RSS is a sampled maximum; cgroup counters describe the shared
runner. External timer counts are unavailable.

The lifecycle diagnostic contributes 23 offers and 57 commands per process,
322 offers and 798 commands across seven pairs. It requires actual queued
targets behind four running holders, delayed body release after observed ingress
expiry, running interruption, positive running cancellation, recovery and owned
cleanup. A phase label or early rejection cannot substitute for those witnesses.
The recorder bounds identities to 23 and events to 512; missing lineage or
overflow cannot qualify. Terminal-decision times are actual checked instants;
lifecycle and terminal-winner events observe transitions after they commit.

Runaway and short-cancel diagnostics retain 1/2/5/10 ms native wall grants but
allow 1,000 ms for both transport and caller absolute deadlines. This permits
native interruption to acknowledge cleanup. Queued/delayed-body diagnostics and
the external population keep matching short transport deadlines. Outer response
overshoot, actual admitted-deadline decision overshoot and client response after
native expiry are separate observations; missing observations remain unavailable.

Wait counters cover only the observed manager-owned sleep guards, not all
Tokio, transport or operating-system timers. Process CPU ticks span the complete
diagnostic population, controls and drain, including the node, client and
observers; they are not divided into per-offer CPU. Bounded retained telemetry
history is distinguished from live ownership and joined threads. Seven pairs
provide descriptive measurements rather than a production SLO or significance
test.

A failed same-deadline functional diagnostic exposed serving-capacity loss after
running transport disconnects. Its failed evidence remains retained. The longer
diagnostic transport allowance does not demonstrate that
[#119](https://github.com/KirilsTurkins/latent-service-fabric/issues/119) is fixed:
bounded owned cleanup and capacity recovery are a separate requirement, while
quarantine remains necessary when safe reuse lacks proof.

## Transport interruption recovery

Issue [#119](https://github.com/KirilsTurkins/latent-service-fabric/issues/119)
adds the explicit `--experiment recovery` profile. It reuses the exact-reference
builder, unchanged external client, process supervision and bounded archive
transport. The original budget profiles and receipts retain their original
meaning. Set the three full SHA references from a clean harness checkout; the
common collectors, recorder, fixture, client and build inputs must match across
the selected references. Use new output directories throughout:

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment recovery --profile full \
  --control-ref "$CONTROL_REF" --candidate-ref "$CANDIDATE_REF" --harness-ref "$HARNESS_REF" \
  --target-root /workspace/optimization-recovery-builds \
  --output target/optimization-recovery/build-only-warm \
  --backend-build-output target/optimization-recovery/build-only-recovery --build-only

python3 - <<'PY'
from pathlib import Path
from shutil import copytree
root = Path("target/optimization-recovery")
for kind in ("warm", "recovery"):
    for profile in ("smoke", "full"):
        copytree(root / f"build-only-{kind}", root / f"{kind}-{profile}")
PY

python3 tools/run_optimization_revision_benchmarks.py --experiment recovery --profile smoke \
  --builds target/optimization-recovery/warm-smoke/revision-builds.json \
  --target-root /workspace/optimization-recovery-data
python3 tools/run_optimization_backend_revision.py --experiment recovery --profile smoke \
  --builds target/optimization-recovery/recovery-smoke/backend-builds.json \
  --target-root /workspace/optimization-recovery-data
```

After both smoke suites replay successfully, run the fresh full copies serially:

```sh
python3 tools/run_optimization_revision_benchmarks.py --experiment recovery --profile full \
  --builds target/optimization-recovery/warm-full/revision-builds.json \
  --target-root /workspace/optimization-recovery-data
python3 tools/run_optimization_backend_revision.py --experiment recovery --profile full \
  --builds target/optimization-recovery/recovery-full/backend-builds.json \
  --target-root /workspace/optimization-recovery-data
python3 tools/validate_optimization_revision_evidence.py \
  target/optimization-recovery/warm-full/suite.json \
  --aggregate target/optimization-recovery/warm-full/aggregate.json
python3 tools/validate_optimization_backend_revision.py \
  target/optimization-recovery/recovery-full/suite.json \
  --aggregate target/optimization-recovery/recovery-full/aggregate.json
```

Package each full root independently with `tools/package_phase1_evidence.py`;
`--compression-level 9 --split-archive` is available within the existing caps.
Replay each published directory with `tools/validate_phase1_archive.py`, which
extracts bounded temporary files and never executes the retained binaries.
Failed attempts remain separate; retries require fresh build-only copies.

The warm profile offers one explicit prewarm, then 40 warmup and 400 measured
Echo calls per arm, all at 1,000 ms. Seven alternating pairs retain 6,174 offers;
only the 5,600 measured offers enter the main latency populations. Smoke retains
17 offers per arm. Measured owners are 14 servers and 28 clients; the validator
also counts 14 seed servers. Successful-response latency, all-offered completion
time and all failure counts remain separate. Server/client CPU and RSS include
warmup and observer overhead; external timer counts are unavailable.

The recovery diagnostic has exactly one pair for either profile, 61 offers and
125 commands per arm. It prewarms the generic component, repeats expiry and
attempted disconnect at each of 1/2/5/10 ms three times, and follows every such
attempt with a healthy identify request. Five further 1,000 ms spin calls wait
for actual Running observations before aborting and joining the client task;
each is followed by another identify. One positive explicit Cancel and final
identify complete the fixed population. All original envelopes remain in raw
evidence. A short request rejected before Running is not counted as Running
interruption coverage, and a response racing the planned abort remains a
response. The longer positive cases do not establish 1 ms Running execution.

Both variants retain the same four cells, 64 queue slots, cache configuration
and separate fixed invocation/control/client runtimes. The old reference may
lose reusable capacity, but still attempts all sixty-one requests. Candidate
qualification requires the five actual Running drops, all thirty successful
recovery calls and full reusable capacity without restarting the node.

The bounded recorder retains at most 64 identities and 2,048 events. Exact
token/slot/generation events mark the start of transferring the owned lifecycle
and reserved cleanup slot, before queue commit or polling by the driver. Their
`cancelled` cause denotes raw transport disconnect, not an accepted Cancel RPC.
Terminal decisions, actual native cleanup logs and final affine ownership are
checked separately; a handoff event or increased counter alone cannot prove
safe reuse. A terminal publication can precede destruction of the completed
future and refund of its supervisor slot. Transient snapshots preserve those
live charges; final cleanup requires the driver joined, no live slots and every
handoff completed without timeout, panic or fallback. The control's absent
supervisor fields mean unavailable observation, not zero work.

The actual cleanup grace is 100 ms; its fixed handoff ceiling is 200 ms. The
independent 250 ms acknowledgement observation does not extend the guest budget
or cleanup allowance. Original deadline lineage, actual abort/join timestamps,
terminal winners and correlated release/revision/generation identities remain
in `recovery.json`. CPU ticks cover the diagnostic population, controls and
drain, not individual requests. Manager sleep counters cover their own guards,
not all runtime, transport or OS timers. Sampled whole-process RSS and retained
bounded telemetry history are distinct from live ownership. This single pair
proves a finite recovery population; it is not a statistical performance claim.
## Request ownership experiments

The fixed `--experiment ownership` profile compares exact control/candidate
revisions with byte-identical common collectors and an identified shared harness.
Both revisions include the supported generic prepared cache and transport
cleanup. The external client is unchanged. A build-only pass builds the two
servers and two `latentd` libtest collectors at the same owned source/target
paths, plus the shared client/CLI and three maintained components. No unused
native server, Echo collector or additional Rust benchmark client is built.

The two evidence packages have distinct boundaries:

| Population | Smoke calls | Full calls | Boundary |
| --- | ---: | ---: | --- |
| External `warm-echo`, `payload-64k`, `payload-near-limit` | 76 | 12,936 | Actual loopback RPC, including retained warmup; no additional prewarm |
| Six direct shapes and two pending-future proofs | 52 | 3,052 | One Wasmtime factory per child; no node, listener or RPC |
| Six independent allocation pairs | 36 | 108 | One shape per Heaptrack child, including its explicit warmup |
| Total | 164 | 16,096 | All calls remain retained |

There are seven normal pairs in full and one in smoke. Direct shapes use the
three payloads above and small, 64 KiB and near-limit contexts. Each normal child
prepares optimization, capabilities and generic exactly once, then executes
four warmup plus 32 measured calls per shape in full (one plus three in smoke)
and two generic pending-future proofs. Each allocation child prepares only its
selected component and runs one warmup plus eight measured calls in full (one
plus two in smoke). Allocation profiles use one pair per shape, not seven
normal timing repetitions. Every returned output is validated outside the
timed invocation interval.

Inputs are generated once by the retained neutral control. Fixture generation
performs exactly one capabilities preparation, at most 20 borrowed context
charge checks, zero Invokes and zero guest Stores, then joins its factory and
compiler workers. It retains the actual charge and 512–1,024 B of near-limit
headroom. Fixed-width invocation IDs preserve sizing across calls. The candidate
uses these exact files; Python does not reproduce the Rust charge formula or
resize inputs after observing results. Direct contexts deliberately exceed
ordinary RPC metadata limits and are not presented as remotely accepted input.

Request construction includes the owned request and boxed backend future.
Direct invocation runs from the first poll through its contained report and
future destruction. The retained backend timing excludes outer context
validation. Its reclamation spans measure actual destruction separately from
outcome classification. The capabilities output contains dynamic deadline and
remaining-budget values: replay checks the actual retained output, exposed
claims/baggage/metadata and its bounded budget rather than demanding identical
whole-output hashes between revisions.

Raw-input observation is disabled for normal timing and profiled calls. The two
proof IDs enable a fixed 8-identity/64-event recorder, observe actual guest
dispatch and `Pending`, then either signal cancellation through acknowledgement
or destroy the pending future. Replay binds raw capacity, release reason and
invocation retirement to that exact ID and capture interval. Direct future
destruction proves backend reclamation. A separate maintained standalone test
covers the real transport handoff and affirmative cell reuse.

Heaptrack 1.4 profiles remain separate from normal CPU/RSS observations. Exact
raw and demangled `nm` records bind constructor and monomorphic poll symbols to
the same retained executable by code address and type. Interpreted and folded
allocation streams must agree. An allocation containing both selected frames
counts once in their union; later frees refund its original selected ownership.
Peak selected bytes are the maximum simultaneously live bytes, never the sum
of frame peaks. Missing symbols or unresolved frames produce unavailable
attribution, not zero. Logical Rust capacity, allocated bytes, selected live
heap, guest linear memory and process RSS remain separate quantities.

The ownership suite declares a 128 MiB expanded limit per folded stream. The
first release smoke produced a valid 93,464,548-byte folded allocation report
and stopped at the inherited 64 MiB compression bound after its collector and
profiler completed. That failed attempt remains retained. Ownership collection,
lossless compression, whole-process totals and selected-frame replay now use
the same explicit limit; historical experiments keep 64 MiB. The 64 KiB line,
100,000-row, 512-frame, 256 MiB file and 1 GiB evidence-root limits are unchanged.
Extraction compresses and verifies each complete folded stream before removing
its temporary expanded copy. Retained gzip streams remain subject to the root
limit; a later overflow fails the collection and cannot discard a shape.

Normal process CPU uses serial `RUSAGE_CHILDREN` deltas around the owned child
and includes setup, validation and observation holds; it is not per-call CPU.
Normal RSS includes actual live samples and the kernel high-water mark.
Profiled probe resources are explicitly instrumented, and the Heaptrack wrapper
has a distinct owned PID. Both readiness and completion have a fixed 100 ms
hold outside timed invocations. Build-only and each subsequent smoke/full
collection have independent 7,200 s deadlines. A build command is bounded to
3,600 s, a normal child to 90 s, a profiled child to 180 s and an extraction tool
to 120 s, always clipped to its enclosing stage's remaining time. Reports retain
actual stage and total elapsed times; 7,200 s is not a shared campaign bound.

From the clean, identified measurement harness, supply full 40-character refs:

```sh
python tools/run_optimization_revision_benchmarks.py --experiment ownership \
  --profile full --control-ref "$CONTROL_SHA" --candidate-ref "$CANDIDATE_SHA" \
  --harness-ref "$HARNESS_SHA" --target-root /workspace/ownership-builds \
  --output target/ownership/build-only-rpc \
  --backend-build-output target/ownership/build-only-direct --build-only

# Make all four fresh copies before collection. Existing destinations are errors.
test ! -e target/ownership/rpc-smoke && cp -a target/ownership/build-only-rpc target/ownership/rpc-smoke
test ! -e target/ownership/rpc-full && cp -a target/ownership/build-only-rpc target/ownership/rpc-full
test ! -e target/ownership/direct-smoke && cp -a target/ownership/build-only-direct target/ownership/direct-smoke
test ! -e target/ownership/direct-full && cp -a target/ownership/build-only-direct target/ownership/direct-full

python tools/run_optimization_revision_benchmarks.py --experiment ownership --profile smoke \
  --builds target/ownership/rpc-smoke/revision-builds.json --target-root /workspace/ownership-data
python tools/run_optimization_backend_revision.py --experiment ownership --profile smoke \
  --builds target/ownership/direct-smoke/backend-builds.json --target-root /workspace/ownership-data
python tools/run_optimization_revision_benchmarks.py --experiment ownership --profile full \
  --builds target/ownership/rpc-full/revision-builds.json --target-root /workspace/ownership-data
python tools/run_optimization_backend_revision.py --experiment ownership --profile full \
  --builds target/ownership/direct-full/backend-builds.json --target-root /workspace/ownership-data
```

Each suite replays independently through the existing revision/backend validator
CLI and the existing Phase 1 archive packager. The direct package retains all
raw ownership documents, full allocation traces, exact executable/source inputs
and helper receipts under the existing 1 GiB/file-count/8 MiB document limits.
Use the existing explicit split transport when needed; historical archives and
their limits remain unchanged. Failed attempts are retained and cannot qualify
as a complete population. Functional debug fixtures are semantic parser inputs,
not release performance evidence.

## Typed codec experiments

The fixed `--experiment codec` mode reuses the exact-revision builder, unchanged
external client, owned process supervisor and archive replay. A build-only pass
builds two standalone servers and two `latent-wasmtime` libtest collectors, plus
the shared client/CLI and optimization component. The common collector, type
fixture, CPU reader, dependency lock and build recipe must match across refs.
The production codec and its test registration are outside that equality set.

The external package retains `warm-echo`, `compute`, `transform`, `payload-64k`
and `payload-near-limit` with their existing client semantics and populations:
140 offered calls in smoke, or 25,256 across seven alternating pairs in full.
Warmup remains retained and separate from measured outcomes. Successful-response
latency, all-offered completion time, throughput and whole server/client CPU and
RSS remain separate observations. A codec-only gain cannot establish an RPC
gain or resolve the warm regression retained in the request-ownership report.

The separate codec package runs six fixed families. Input and canonical output
bytes are independently reconstructed by Python and Rust; neither arm adapts
them to observed results. Each child owns and drops its engine, component and
selected types. It constructs no guest Store or instance and performs no Invoke.

| Family | Input bytes | Canonical output bytes | Full measured calls per direction |
| --- | ---: | ---: | ---: |
| Scalar parameters | 131 | 123 | 4,096 |
| Byte list | 14,627 | 14,627 | 573 |
| Nested record | 2,850 | 2,850 | 2,943 |
| 64 KiB string | 65,540 | 65,540 | 127 |
| Near-limit string | 122,884 | 122,884 | 68 |
| Escaped Unicode | 98,308 | 49,156 | 85 |

Each child performs three decode and three encode semantic preflight calls
outside timing: the stable public path, its diagnostic path and the explicit
legacy implementation. All must match the fixed canonical output. Both arms
retain legacy-produced values as the encoding input, keeping their allocation
capacity provenance common. The observed preflight path is `legacy-only` for
the control and `typed-success` for the candidate. Successful candidate batches
rely on the source invariant that accepted input cannot silently fall back to a
successful legacy decode; strict replay does not invent per-call path events.

Each direction then performs two warmup and four measured calls in smoke, or
20 warmup and the table's measured count in full. Normal and separately profiled
children use the same calls, with one pair per family/mode in smoke and seven in
full: 24 and 168 owned children respectively. Total codec operations are 432 in
smoke and 449,680 in full. The full total includes 1,008 preflight, 6,720 warmup
and 441,952 measured operations; these are not guest invocation counts.

`measured_decode_and_drop` and `measured_encode_and_drop` each run once per child
and contain the complete measured loop. Their boundaries include the actual
codec, `black_box`, constant-time outcome/arity or output-length checks and
result destruction. Warmup and semantic preflight bypass these named frames.
There is no per-call hashing or re-encoding inside the timed loop. Retained
batch elapsed time and actual `CLOCK_THREAD_CPUTIME_ID` readings support batch
totals and arithmetic per-operation averages, not individual latency quantiles.
Coarse `/proc` readings bind the same actual task before and after each batch.
Both clocks must remain monotonic across decode and encode. Readings bracket
the batch, so their scope includes the small clock-reading boundary overhead.

Normal process CPU and RSS additionally include type setup, preflight, warmup,
validation, teardown and the two fixed 100 ms observation holds. Heaptrack
profiles are independent children. Raw and demangled `nm` proofs bind both
selected symbols by actual code address/type to the retained executable.
Interpreted and folded streams must agree; an allocation containing both frames
counts once in their union, and later frees refund its original ownership.
Missing or unresolved frames mean unavailable attribution, not zero. Available
selected totals can be divided by the declared contained codec-call count;
simultaneous peak bytes cannot be summed across frames or divided into a
per-operation peak. Whole-process allocation totals remain separately labeled.

Build-only and each later smoke/full collection have independent 7,200 s
bounds. Per-build commands have 3,600 s, normal children 90 s, profiled children
180 s and extraction tools 120 s, each clipped to its enclosing stage. The
codec suite explicitly permits 128 MiB expanded folded streams; historical
defaults stay at 64 MiB. The existing 64 KiB line, 100,000-row, 512-frame,
256 MiB file and 4,096 retained-file limits remain. Codec alone declares a
2 GiB evidence-root limit and 12,000,000 interpreted profile records; other
experiments retain the 1 GiB root and 4,000,000-record defaults. The 250,000-entry
profile table limits remain unchanged. Whole-profile and selected-origin
replay enforce the same declared record limit. Raw codec documents are bounded
to 8 MiB. Failures retain their completed work and owned cleanup receipts, fail
population qualification and require fresh output roots for retries.

The first full codec attempt stopped after 59 children at the original root
reservation; its retained profiles also exceeded the original record limit.
The observed maximum was 9,831,105 records in a 59,457,687-byte text
profile, and complete paired repetitions retained approximately 188 MB each.
That incomplete attempt remains diagnostic evidence. The explicit larger
codec limits preserve all 168 children and 449,680 operations. Subsequent
collection uses fresh roots and exact source/build receipts; the already
completed external RPC population retains its original identity and protocol.

Archive packaging selects the 2 GiB expanded allowance only from the bounded
outer codec aggregate, binds those exact bytes to the archived aggregate, and
requires the same archived kind and complete semantic replay. All codec members
remain bounded to 256 MiB; the archive entry cap is 5,000. Other evidence kinds,
including codec RPC, keep 1 GiB. The 99 MB monolithic and 198 MB split compressed
limits are unchanged; a size overflow fails publication rather than dropping
evidence or adding an unbounded archive option.

From a clean identified harness, supply full 40-character refs:

```sh
python tools/run_optimization_revision_benchmarks.py --experiment codec \
  --profile full --control-ref "$CONTROL_SHA" --candidate-ref "$CANDIDATE_SHA" \
  --harness-ref "$HARNESS_SHA" --target-root /workspace/codec-builds \
  --output target/codec/build-only-rpc \
  --backend-build-output target/codec/build-only-direct --build-only

# Copy all four fresh roots before collection; existing destinations are errors.
test ! -e target/codec/rpc-smoke && cp -a target/codec/build-only-rpc target/codec/rpc-smoke
test ! -e target/codec/rpc-full && cp -a target/codec/build-only-rpc target/codec/rpc-full
test ! -e target/codec/direct-smoke && cp -a target/codec/build-only-direct target/codec/direct-smoke
test ! -e target/codec/direct-full && cp -a target/codec/build-only-direct target/codec/direct-full

python tools/run_optimization_revision_benchmarks.py --experiment codec --profile smoke \
  --builds target/codec/rpc-smoke/revision-builds.json --target-root /workspace/codec-data
python tools/run_optimization_backend_revision.py --experiment codec --profile smoke \
  --builds target/codec/direct-smoke/backend-builds.json --target-root /workspace/codec-data
python tools/run_optimization_revision_benchmarks.py --experiment codec --profile full \
  --builds target/codec/rpc-full/revision-builds.json --target-root /workspace/codec-data
python tools/run_optimization_backend_revision.py --experiment codec --profile full \
  --builds target/codec/direct-full/backend-builds.json --target-root /workspace/codec-data

python tools/validate_optimization_revision_evidence.py target/codec/rpc-full/suite.json \
  --aggregate target/codec/rpc-full/aggregate.json
python tools/validate_optimization_backend_revision.py target/codec/direct-full/suite.json \
  --aggregate target/codec/direct-full/aggregate.json
```

Package the two full roots independently with `tools/package_phase1_evidence.py`
and replay each publication with `tools/validate_phase1_archive.py`. Packaging
requires full semantic replay and exact derived aggregate equality. Replay
never executes retained binaries. Structural schema envelopes do not replace
source, fixture, timing, allocation and complete-population validation.

## Engine profile experiments

`--experiment engine` uses the existing exact-revision builders, owned process
supervision and archive replay. It has two independent populations. The external
warm Echo comparison uses the unchanged public client against the old and new
default daemon: 32 offered calls in smoke, or 6,160 calls across seven full
pairs (560 warmup and 5,600 measured). The engine field is omitted in both
external node configurations. This is the matched follow-up to the warm costs
retained in the #104 and #105 reports; historical medians are not subtracted
from this comparison.

The separate matrix starts five fresh node owners per block:

| Row | Source | Allocator | Compiler optimization |
| --- | --- | --- | --- |
| O | Control containing merged #105 | Existing omitted default | Existing speed default |
| D0 | Candidate | On demand | Speed |
| P0 | Candidate | Pooling | Speed |
| D1 | Candidate | On demand | Speed and size |
| P1 | Candidate | Pooling | Speed and size |

Starting with `O D0 P0 D1 P1`, block `b` rotates left by `(b-1) mod 5` and
reverses the whole sequence for even blocks. Smoke uses the first block; full
uses seven blocks and 35 owners. Candidate D0 minus control O tests explicit
default preservation. P0, D1 and P1 each compare with the same actual candidate
D0 in that block; they are not three independently measured baseline owners.
Paired deltas and direction counts accompany the medians of process quantiles.
Seven blocks and small order strata support descriptive comparisons, not a
universal latency guarantee.

Each owner retains 52 Invokes/125 wire commands in smoke, or 794 Invokes/1,609
commands in full. Full matrix totals are 27,790 Invokes and 56,315 commands.
Ordinary phases are sequential Echo, fixed compute, 4 MiB memory initialization
and four-wide Echo, each with explicit warmup and measured populations. Eight
release publications and eight deployment applications precede the first
declared Echo warmup. There are no hidden preparation Invokes. The first Echo
call is fresh-engine work; later first uses of other components are separately
observed compilations within that owner.

The eight tenant publications derive from five retained, unchanged component
inputs. A bounded binary transform renames only their outer exported instance
names to `engine-a:` or `engine-b:`. Nested components, guest code, imports and
all other sections remain byte-exact; the existing tenant-B custom marker is
appended afterward. Capsule worlds, exports and owned contract/interface
identities use the same namespace, with canonical metadata digests recomputed.
Replay independently checks the exact binary delta and metadata association.
The first matrix smoke attempt stopped at its first publication, before any
Invoke, because tenant-only metadata did not match the original export
namespace. That failed attempt remains retained; the corrected common fixture
recipe requires new clean build receipts and a fresh smoke output directory.

Each matrix request keeps a five-second monotonic transport window, while its
native wall grant is explicit per case. Before dispatch it brackets a fresh
live Unix-clock read with monotonic `started_nanos` and `finished_nanos`, retained
alongside `unix_nanos` in `deadline_clock_sample`. Replay requires scheduled
time <= sample start <= sample finish <= dispatch. The absolute Unix deadline is
`floor((unix_nanos + max(0, deadline_nanos - finished_nanos)) / 1_000_000)`.
The raw row retains the floor remainder (less than one millisecond) and the
sample bracket duration plus that remainder as total projection loss. This
uses the actual offer's wall clock instead of extrapolating the campaign's
initial wall/monotonic anchor; it does not change the node's five-second limit,
gRPC remaining-time header, or native grant. Guest deadline snapshots must match
the actual admitted ledger, which can expire earlier than transport. WIT absent
options use `{"none":null}`. A second failed matrix smoke exposed the old ceiling
and absent-option oracle mistakes and remains excluded from qualified results.
Full matrix04 later retained three owners and 2,382 offered Invokes / 4,827
commands: control D0 and candidate D0 passed, while P0 retained 448 successes
followed by 346 `InvalidArgument` transport failures reporting an absolute
deadline above the configured maximum. Its clean shutdown and failed raw graph
remain retained; the partial run is excluded from full results. The fresh
per-offer clock projection replaces the stale campaign-anchor projection in
new evidence, without changing the population. Production replay requires the
new sample. An explicit keyword-only legacy-clock opt-in is used only by tests
for unchanged dirty snapshot11 fixtures; production suite parsing never enables
it or silently falls back when a fresh sample is absent.
Transport failures retain their actual status code and at most 2,048 UTF-8 bytes
of the message, with its original byte count and explicit truncation flag.
The fuel and memory fault cases additionally retain one bounded, tenant-scoped
local-manager status capture after their RPC responses. Replay binds its native
fault kind, cell identity and consumption to the same activation, release,
revision and subsequent public terminal status. Public resource-error details
remain redacted; their absence does not erase the separate native witness.

Each owner also retains all 24 functional Invokes, 24 terminal status queries
and five accepted Cancel commands. These calls check tenant context and trace
isolation, real clocks and log-byte accounting, mutable-global reset, fuel,
memory and deadline faults, and memory reset following a trap and cancellation.
The memory fixture checks every byte for zero before dirtying its fixed region.
Four known Running tasks must remain Pending while a fifth request is queued;
after one accepted cancellation the fifth succeeds while the remaining three
holders are still live. This proves scheduler capacity and reclamation. It
does not identify a particular physical Wasmtime pool slot. Separate native
single-slot correctness tests cover that boundary.

Every response, retained status, guest log and functional source observation
is bound to its actual activation, tenant, release, revision and route generation.
The diagnostic records at most 24 identities and 1,024 events and is enabled
only during functional work. Both sources include precise deadline accounting
and the bounded transport cleanup driver. Qualification requires the actual
native owners and reservations to drain, zero quarantined cells, all compiler,
epoch, runtime and cleanup-driver joins, and zero final unique compiled-runtime
charges. Retained bounded telemetry history is not an active native owner.

All rows retain four cells, a 64-entry queue, an eight-entry prepared cache,
four preparation jobs and two compiler workers. The 512 MiB journal allowance
is a retention-accounting bound, not allocated resident memory. Pooling uses
four slots, a 64 MiB maximum linear memory, zero guards/growth reservation,
zero warm unused slots, decommit batch size one and zero keep-resident thresholds.
The on-demand row preserves the pinned 64-bit Wasmtime layout: 4 GiB reservation,
32 MiB guard and 2 GiB growth reservation. The 5 ms epoch interval, fuel yielding,
stack limits, copy-on-write policy and context exposure remain fixed. A pooling
contrast therefore includes its declared allocator and memory-layout policy.

Per-RPC timestamps stop at response receipt before validation and status calls.
Batch throughput includes the explicitly retained status, validation and write
work. Backend setup, guest call, post-return accounting and reclamation keep
their existing instrumented boundaries. Preparation stages retain actual worker
CPU observations. Matrix process CPU includes the node, in-process client,
controls and observation; external RPC keeps server and client CPU separate.
Neither coarse process ticks nor batch throughput become per-call CPU values.

Bounded measurement-local `/proc/self/status` and `smaps_rollup` captures retain
VmSize, VmPeak, RSS, VmHWM, PSS and private/shared clean/dirty byte fields.
Each capture has an actual process/start identity and monotonic bracket. Missing,
denied, malformed or unsupported fields retain null plus a fixed reason, never
zero. Status, smaps, sampled process RSS and unique compiled-image charges are
different measurements. Virtual reservation is not committed RSS, and a maximum
over checkpoints is not an unsampled process peak. No Heaptrack population is
part of this experiment.

Build-only and each external collection have independent 7,200 s bounds. Each
matrix owner has 300 s and each matrix collection 10,800 s; functional work is
additionally bounded to 30 s per owner. Matrix raw JSON is limited to 32 MiB,
individual rows to 256 KiB, 2,048 sample rows and 64 memory captures. A matrix
root retains the existing 1 GiB/4,096-file limits; each new owner reserves 40 MiB
within the remaining root. Archive publication keeps 5,000 entries, 256 MiB
files, 99 MB monolithic or 198 MB split compressed transport. Failed populations
retain their evidence and cannot qualify as a complete publication.

From a clean identified harness, build once with `--experiment engine
--build-only --profile full`, full `--control-ref`, `--candidate-ref` and
`--harness-ref`, a fresh external `--output`, and a fresh
`--backend-build-output`. The builder retains five fixed component inputs and
two exact-source backend libtests. Before any measurement, copy both build-only
roots to separate, previously absent smoke/full directories. Run the external
CLI with `--builds <external-root>/revision-builds.json`, and the backend CLI
with `--builds <matrix-root>/backend-builds.json`, using `--experiment engine`,
the selected profile and an owned `--target-root`. Smoke must pass before full.
Never overwrite an existing measured root. Validate each full suite with its
existing revision/backend validation CLI and `--aggregate`, then package and
replay the two evidence roots independently. Structural schemas supplement
mandatory exact-source, complete-population and archive semantic replay.

## Catalog memory experiments

The #107 catalog experiment builds two exact-source `latentd` libtest collectors
and one maintained Echo component. Their collector/helper source and build
configuration are identical; the production catalog implementation differs.
No external RPC client, guest invocation, guest Store or compilation preparation
belongs to this population. Both variants retain the default on-demand/speed
engine, two runtime workers, one control worker and the same catalog limits.

Distinct-service and shared-service shapes publish unique releases using the
retained Echo bytes and `latent.scale.identity.v1` custom-section recipe.
Default selection preserves revision ordering, route spelling, weighted hash
framing and canonical deployment attributes. Normal timing measures the public
resolver call through its returned owned result; validation and result Drop
follow the clock. Every expected success and miss remains counted and replayed.

| Population | Smoke | Full |
| --- | --- | --- |
| Growth checkpoints | 2, 4, 16 | 100, 1,000, 10,000, 100,000 |
| Matched pairs per shape | 3 | 1 |
| Initial/reopen processes | 24 | 8 |
| Timed normal resolves | 6,912 | 192,000 |
| Normal API operations, including pins and policies | 7,332 | 592,080 |
| Separate tiny allocation processes | 16 | 16 |
| Measured resolves in allocation frames | 1,024 | 4,096 |
| Total API operations | 8,900 | 596,720 |

Each repetition runs distinct control first and shared candidate first.
An initial owner publishes its releases in bounded chunks, samples artifact-only
idle before constructing deployment requests, and applies each growth delta
once. Primary post-publication idle precedes all resolver inputs, result buffers
and correctness-oracle tables. Later samples follow their release. The final
weight update retains an old pin, verifies old and new policy/route attributes,
and measures both the overlapping generations and the old pin's release.

After the initial process exits, the parent hashes its durable catalog and binds
the original process, data-directory device/inode and exclusive owner marker to
the reopen input. The new process opens that unchanged directory with the same
executable. It samples reopened idle before four resolves, one pin and two policy
reads. The parent removes its owned root after the pair finishes. Generated
release files are excluded from the evidence archive; retained recipes, hashes,
operation digests and cleanup receipts describe the measured data.

A source-owned thread observes RSS, high-water RSS and process CPU ticks with a
requested 100 ms interval. Every observation retains its actual clock bracket
and process/start identity. Report actual cadence and the number of samples
wholly inside each apply window; absent samples cannot establish a peak.
Checkpoint status/smaps observations, allocator retention, conservative capacity
charges and process resident memory remain separate quantities.

Allocation children each build only sixteen releases. Their selected case has
one semantic preflight, sixteen warmup calls and 64/256 smoke/full calls in one
noninlined public-resolve-and-Drop frame. Four cases cover default and named
success, route miss and export miss. Heaptrack and actual binary symbols bind
allocation origins; unavailable attribution stays unavailable. The 100k growth
and reopen population is never allocation-profiled.

The first release smoke completed all 24 normal children and its first tiny
allocation child, then failed while exporting a 171,422,982-byte folded profile
against the original 64 MiB limit. That failed attempt remains retained. Catalog
suite plans now explicitly declare a 256 MiB expanded limit for each folded
stream, applied to lossless gzip compression and both whole-process and selected
replay. Historical 64 MiB defaults and ownership/codec 128 MiB selections remain
unchanged, as do the 256 MiB file, 1 GiB evidence-root, row and stack bounds.

Build from a clean identified harness using
`tools/build_optimization_backend_revision.py --experiment catalog --profile full`
with full `--control-ref`, `--candidate-ref`, `--harness-ref`, a fresh `--output`
and an owned external `--target-root`. Copy the untouched build-only directory
to fresh smoke/full directories before measurement. Run
`tools/run_optimization_backend_revision.py --experiment catalog --profile smoke
--builds <smoke-root>/backend-builds.json --target-root <owned-data-parent>`.
Full collection uses the corresponding full directory and `--profile full`
only after the complete smoke suite passes. Do not overwrite a measured root.
Validate the suite with `tools/validate_optimization_backend_revision.py`, then
package and semantically replay the complete archive with kind `catalog`.

Full initial processes have 3,600 s bounds and reopen processes 1,800 s;
the normal stage has 21,600 s. Smoke normal processes have 90 s bounds.
Allocation children have 180 s and their stage 7,200 s. Evidence retains the
standard 1 GiB root, 4,096 files, 32 MiB raw documents, 256 KiB rows and 2,048
sample records. Verify at least 16 GiB free physical backing storage before
the full run; a container filesystem's reported free space does not establish
its host backing capacity. Report the matched 25% RSS reduction and distinct
reference-shape 1,750,000,000-byte ceiling independently. One full pair per shape
supports a descriptive comparison, without a narrow confidence interval.

The [retained catalog comparison](../../benchmarks/optimization/catalog-memory/2026-09-10-container-linux-96716c8/README.md)
contains the completed 24-collector, 596,720-operation campaign. Its distinct
100k primary RSS targets were met, while shared 100k resolver latency and update
time regressed and reopened memory remained higher than primary idle memory.
The report preserves every scale and case, the separate tiny allocation scope,
failed attempts, exact source identities and the bounded publication recipe.

## Catalog mutation and commit experiments

The #108 `catalog-mutations` experiment uses exact clean control/candidate
`latentd` libtest builds and one reproducible Echo fixture. Collector, helpers,
operation-local work observer, configuration and release build settings are
source-identical across arms. Actual build and run receipts must bind the exact
clean commits containing the declared temporary-export protocol. Earlier
receipts retain their original identities. The
[retained 2026-09-11 comparison](../../benchmarks/optimization/catalog-mutations/2026-09-11-container-linux-15f3fba/README.md)
completed 32 collectors / 45,096 commands. All 24 mutation wall/CPU comparisons
were lower, while shared 10k reopen took 41.52% longer and distinct 10k reopened
idle RSS rose 18.75%. These are one-pair observations with the limitations below.
There are no guest Invokes, Stores or preparation
jobs, and no hidden warmups, retries or extra uncounted public catalog reads.

| Population | Smoke | Full |
| --- | --- | --- |
| Independently seeded normal sizes | 4 | 100, 1,000, 10,000 |
| Normal initial/reopen collectors | 8 | 24 |
| Normal public API operations | 186 | 44,910 |
| Separate allocation size / collectors | 4 / 8 | 4 / 8 |
| Allocation public API operations | 186 | 186 |
| Total collectors / API operations | 16 / 372 | 32 / 45,096 |
| Measured mutations / reopen observations | 32 / 8 | 64 / 16 |

Each normal size has distinct-service and shared-service shapes and one matched
control/candidate pair. Sizes ascend; shapes run distinct then shared, with
control first when the zero-based size/shape index sum is even and candidate
first otherwise. Each arm's initial and reopen children are adjacent. Allocation
uses its own N4 roots and the same shape order after the normal stage; larger
normal sizes and 100k catalogs are never allocation-profiled.

An initial owner publishes N releases, seeds one `apply_many`, and retains an old
pin at catalog generation 1. It performs unchanged versioned apply, weight 1-to-2
update, delete, then create-only reapply with expected generation zero. Successful
commits advance catalog generations through 2, 3, 4 and 5; unchanged apply still
advances the object version. Counted gets and old/current pinned resolve/policy
proofs follow every mutation, including a new current pin each time. Deleted
get returns `Ok(None)`; expected route misses remain real API errors. Initial
commands total N+36 for distinct and N+37 for shared. Reopen performs six calls:
get, pin, two resolves and two policy reads, checking final original content and
object generation 5. Pins and returned proof values are explicitly released.

The parent creates each fresh root exclusively, retains its owner marker and
device/inode identity, and hashes the persisted catalog after initial process
exit. A new process opens that same unchanged root with the same arm executable;
no seed-directory copying or restoration occurs. The parent verifies both
process exits, native cleanup and runtime joins, records one bounded final tree
walk, then removes its root. Initial and reopened memory observations remain
separate, including overlap before old-pin Drop and observations after release.

Normal mutation clocks span construction of the actual public future through
its returned Result, before validation, projection and Result Drop. Reopen clocks
span actual artifact/deployment repository opening before Node construction.
Process CPU brackets retain actual sampling times and tick frequency. Common
operation receipts retain compilation, derivation/reuse, fresh artifact
verification, encoding and staged-write work. Payload reuse does not by itself
prove skipped derivation. Commits still write a complete catalog representation;
report actual encodes and requested/written/synced bytes rather than inferring
constant write cost. Buffer lengths are summed work and capacities are individual
buffer maxima, not simultaneous scratch peaks; file fsync bytes alone do not
prove directory durability.

Normal owners use the common source sampler at a requested 100 ms cadence;
only read brackets wholly inside an operation contribute sampled maxima.
Zero samples mean unavailable, and VmHWM/VmPeak remain lifetime high-water
observations. Allocation owners disable that sampler. Their four noninlined
mutation frames cover actual async polls and owned Result Drop, with observed
poll/drop counts; the separately profiled reopen retains its returned catalog
through Node shutdown. Exact binary nm proofs and Heaptrack interpreted/folded
agreement bind matched selected origins, including later frees. The retained
comparison's four reopen profiles missed a raw symbol alias: their original
available/zero summaries remain byte-identical, but selected reopen attribution
is reported unavailable. This does not affect the sixteen selected mutation
frames or the whole-process allocation totals. Do not divide by
poll count or N, sum frame peaks, infer zero whole-process residuals from selected
residuals, or claim exact temporary scratch peaks. Unresolved attribution remains
unavailable. One pair per size/shape supports descriptive differences, not
per-mutation latency quantiles, confidence intervals or extrapolation from N4.

The plan explicitly permits 512 MiB expanded folded text and declares
`maximum_temporary_folded_bytes` as 512 MiB. Exactly one active owned expanded
folded file is temporary scratch, exempt from retained-byte accounting while
its partial gzip and every other file remain charged. Total coexistence is
bounded at 1.5 GiB; retained evidence remains bounded at 1 GiB. Both streams are
processed sequentially. The older catalog experiment stays at 256 MiB expanded
text, without this scratch allowance; earlier defaults remain unchanged.
Each export shares one 120 s deadline with gzip writing and roundtrip verification.
The original is removed only after complete byte/hash verification, followed by
the ordinary root-bound check. Failed originals and partial output remain
diagnostic evidence, not an enlarged qualifying archive. Ordinary retained files
remain bounded at 256 MiB, the evidence root at 1 GiB,
and inventory at 4,096 files. Interpreted profiles retain 4 million records;
folded streams retain 64 KiB lines, 100,000 rows and 512 frames. Raw documents,
rows and sample records retain the 32 MiB / 256 KiB / 2,048 bounds. Full normal
initial/reopen owners have 3,600/1,800 s limits and a 21,600 s stage; smoke normal
owners have 90 s limits. Allocation owners have 180 s and their stage 7,200 s.

Build from the exact clean harness, using full immutable commit arguments and
fresh output/external build roots. Preserve the complete referenced build closure,
including process sidecars and executable modes, in separate fresh smoke/full
roots before collection. The following commands run from that harness; full
collection requires a complete passing smoke and uses `--profile full` with its
own copied build receipt. Never reuse a measured root.

```text
python tools/build_optimization_backend_revision.py --experiment catalog-mutations --profile full --control-ref <control-sha> --candidate-ref <candidate-sha> --harness-ref <harness-sha> --output <build-root> --target-root <external-build-parent>
python tools/run_optimization_backend_revision.py --experiment catalog-mutations --profile smoke --builds <smoke-root>/backend-builds.json --target-root <owned-data-parent>
python tools/run_optimization_backend_revision.py --experiment catalog-mutations --profile full --builds <full-root>/backend-builds.json --target-root <owned-data-parent>
python tools/validate_optimization_backend_revision.py <full-root>/suite.json --aggregate <full-root>/aggregate.json
python tools/package_phase1_evidence.py --source <full-root> --output <fresh-package> --compression-level 9 --split-archive
python tools/validate_phase1_archive.py <fresh-package>
```

Collection and packaging perform mandatory semantic replay; canonical aggregate
equality and the exact complete population remain required. Package kind
`catalog-mutation` retains the standard 1 GiB expanded archive and 198 MB split
gzip bound, with 2-4 parts of at most 50 MB. Compression fit is not assumed before
the actual receipt. Independently copy/hash and replay the closed package, retain
failed attempts separately, and report archive and final-head CI outcomes only
after those checks complete.

## Scheduler queue experiments

The [retained #109 comparison](../../benchmarks/optimization/scheduler-queues/2026-09-11-container-linux-77c0715/README.md)
contains the qualified full population, every observed pair, and the closed
archive replayed on Linux and Windows. Cancellation scans and shifts fell;
selected allocations were unchanged. Timing and memory limits remain explicit.

The scheduler comparison uses the real admission controller, fair scheduler and
four fixed execution cells. Returned assignments are explicitly released after a
requested 10 ms hold. This is a controlled scheduler service model; no guest is
invoked and its throughput is not application execution capacity. Record actual
hold durations, original one-second admission deadlines, caller scheduling lag,
enqueue-to-return latency, every offered outcome, and final pool/quota ownership.
The selected tenant's priority/deadline/aging comparator remains a linear scan.

Each arm runs four load cases: one-tenant closed loop, one-tenant and 32-tenant
saturation at 1,000 offers/second, and a 32-tenant reference at 100 offers/second.
Each load child has eight warmups. Full uses 128 closed-loop offers and two-second
open-loop schedules; smoke uses 16 closed-loop offers and 200 ms schedules.
One closed-loop request or at most 64 open-loop requests may remain pending.
The scheduler queue is bounded at 32. Client backpressure, admission rejection,
scheduler rejection and completed assignments are separate populations.

Cancellation storms first hold four cells and register 64 original queued
futures. With one or eight tenants, cancel tenant-local ordinals whose remainder
modulo eight is 0, 3, 4 or 7. All 32 original canceled futures must settle before
the four holders and 32 survivors are released. Test-only queue-work counters
cover that cancellation-and-settlement window in normal storms; they are disabled
for load and allocation owners. Counts describe actual comparisons, lookups,
unlinks and logical slots shifted, not CPU instructions or mutex wait time.

Both presets have 14 children: eight load, four normal storm and two allocation
storm owners. Full contains 9,128 logical offers (8,720 load, 272 normal storm,
136 allocation); smoke contains 1,344 (936, 272, 136 respectively). These are
scheduler offers, not Invoke RPCs. Each case has one matched pair, so results are
descriptive observations without independent replication or production SLO claims.

The allocation frame polls the actual cancellation-and-settlement future,
including the original queued futures. Fixture construction, JSON projection and
validation stay outside it. Prove the selected frame in the actual interpreted
trace as well as the exact binary's symbol table; an absent match is unavailable
attribution, never evidence of zero allocation. Preserve whole-process totals and
selected-origin frees separately. Raw children are bounded at 32 MiB, aggregate
JSON at 8 MiB, expanded folded profiles at 64 MiB and retained evidence at 1 GiB.
There is no temporary folded-file allowance. The suite has a 30-minute deadline;
normal/allocation children have 60/180-second limits and profile reports 120 seconds.

The scheduler build, run and validation entrypoints use separate versioned
`scheduler-builds`, `scheduler-suite` and `scheduler-aggregate` documents. A
published full result requires replayed complete paired population, actual
scheduler overload in both saturated cases and arms, a successful low-rate
reference, and supported selected allocation coverage. Archive replay preserves
the standard 1 GiB expansion and 5,000-member bounds. Retain failures and unmet
targets as limitations rather than adjusting an arm's workload after collection.

Run the following from the clean measured harness. Full commit arguments bind
the two versions and the common collector; the full versions must differ.
Preserve the complete referenced build closure, including process sidecars and
executable modes, in fresh smoke/full roots before collecting. Run and inspect
smoke before full. Neither runner retries failed owners or supplies missing offers.

```text
python tools/build_optimization_scheduler.py --profile full --control-ref <control-sha> --candidate-ref <candidate-sha> --harness-ref <harness-sha> --output <build-root> --target-root <external-build-parent>
python tools/run_optimization_scheduler.py --profile smoke --builds <smoke-root>/scheduler-builds.json
python tools/run_optimization_scheduler.py --profile full --builds <full-root>/scheduler-builds.json
python tools/validate_optimization_scheduler.py <full-root>/suite.json --aggregate <full-root>/aggregate.json
python tools/package_phase1_evidence.py --source <full-root> --output <fresh-package> --compression-level 9 --split-archive
python tools/validate_phase1_archive.py <fresh-package>
```

Structural schemas live under `tools/optimization_scheduler/schemas`; semantic
replay additionally checks the original rows, artifacts, owners and summaries.
Keep the first actual selected-frame profile as preflight evidence before freezing
the common source. Preserve a failed preflight separately from the final paired
population. The report must distinguish collection completion from acceptance
qualification and report final CI against the exact PR head proposed for merging.

## Docker application comparison

The [Docker runbook](docker-comparison.md) defines #111 collection, independent
replay and publication. Full uses seven pairs / 9,926 offers; smoke uses one pair /
300 offers. Each density compares one LSF node serving 1/8/32 services with the
corresponding number of native service containers under matched aggregate CPU,
memory and PID limits. First-per-service, warmup and measured echo/compute phases
remain separate. The [retained Docker results](../../benchmarks/optimization/docker-comparison/2026-09-11-container-linux-a56a6dc/README.md)
report the actual completed comparison and both platform replays.

Retain actual container and namespace process ownership, ready/served/final
resource windows, persistent client costs, source/build identities and cleanup.
The seed-only CLI uses the controller's loopback network namespace; measured
groups use the owned internal bridge. Report summed native children and wrappers
separately, charge each leaf cgroup once, preserve unavailable metrics, and retain
the intentional lifecycle pauses. Docker Desktop/WSL2 observations describe its
shared Linux VM; they do not establish bare-metal or Kubernetes performance.

Private [Docker evidence schemas](../../tools/optimization_docker/schemas/README.md)
supplement semantic replay. The archive adapter requires both complete full and
smoke populations with one shared retained build, keeping the standard 1 GiB
expanded and 198 MB split-gzip bounds. Follow the runbook's fresh-root commands
and retain actual validation receipts before publishing any measured claim.
