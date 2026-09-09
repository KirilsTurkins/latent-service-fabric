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
total. Ordinary archives retain their 99 MB cap. Both forms keep the 1 GiB
expanded and 5,000-file limits and require full evidence replay; the validator
checks ordered part identities and the reconstructed archive before extraction.

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
