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
