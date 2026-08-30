# Phase 0 baseline and calibration evidence

raw-results.json and BASELINE.md are the original full-profile observation.
They remain useful as historical evidence, but their WSL2 environment means
they are not the Phase 1 variance reference.

The current native-Linux reference for the selected ordinary Phase 0
configuration is retained under
[`calibration/native-linux-2026-08-30-52ac4754`](calibration/native-linux-2026-08-30-52ac4754/CALIBRATION.md).
Its `CALIBRATION.md` and `aggregate.json` describe seven independent
full-profile processes, link every individual raw run, and retain
published/execution Git-tree provenance. It
explicitly records prepared-cache enablement, `on_demand` Wasmtime allocation,
and initialized-memory COW. Together with the matching August 30 profile and
soak packages, it is verified by the
[authorized full-gate receipt](receipts/native-linux-2026-08-30-b932a935/gate-summary.json).
The August 29 packages remain immutable historical evidence.

For repository transport, the current calibration and soak archives use the
checksummed, reassemblable `latent.phase0.raw-evidence.parts.v1` format; the
profile retains its compatible `latent.phase0.hot-path.raw-evidence.parts.v1`
format. Every fragment is at most 716,800 bytes, and the verifier checks part
order, size, digest, reconstructed archive digest, and extracted manifest
before regenerating an aggregate.

Generate a new reference only from a clean worktree on a stable native-Linux
host or VM:

~~~bash
tools/run_phase0_calibration.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  --published-source-ref <durable-branch-or-tag> \
  /var/tmp/phase0-evidence/calibration
~~~

The command refuses WSL and detected containers, requires a fresh output
directory, records source/environment provenance before and after every run,
and invokes tools/run_phase0_baselines.sh full seven times. Each invocation
still validates contracts and fixtures and still treats all containment,
topology, capacity, reclamation, and resource checks as pass/fail.

First publish a durable branch or tag, then give the wrapper its reachable
commit, tree, and ref IDs:

~~~bash
tools/run_phase0_calibration.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  --published-source-ref <durable-branch-or-tag> \
  /var/tmp/phase0-evidence/calibration
~~~

The wrapper requires the checked-out commit to be the published commit, rejects
a local worktree whose Git tree differs from that published tree, and records
the durable ref plus its resolved head in every run and aggregate.

When this calibration is intended for the selected issue-40 ordinary
configuration, the helper explicitly runs and records prepared-cache enabled,
`on-demand` Wasmtime allocation, and initialized-memory COW enabled. A
calibration that lacks those recorded fields cannot be assumed comparable.

The archive contains:

- runs/run-NN/raw-results.json and runs/run-NN/BASELINE.md for every full
  profile;
- per-run execution status and before/after host observations, including
  virtualization, allocator, CPU frequency/power policy where observable, and
  background-load notes, plus published/execution Git-tree provenance;
- aggregate.json with per-metric sample count, run count, minimum, median,
  maximum, MAD, CV, run-level outliers, and advisory comparison bands;
- CALIBRATION.md, the concise human-readable reference.

The evidence is observational. Its comparison bands are Phase 1
regression-detection aids, not production SLOs, capacity guarantees, or
cross-machine claims.

## Native-Linux hot-path profiles

Issue 40 adds a separate manual CPU/allocation profiling archive. It is not
shared CI and does not replace the correctness baseline or the seven-run
calibration. From a clean native-Linux worktree with the documented open-source
`perf` and `heaptrack` tools, publish the measured source tree and run:

~~~bash
tools/run_phase0_hot_path_profiles.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  --published-source-ref <durable-branch-or-tag> \
  --calibration-aggregate /var/tmp/phase0-evidence/calibration/aggregate.json \
  /var/tmp/phase0-evidence/profiling
~~~

The calibration argument is mandatory and must be a newly collected aggregate
with its sibling `runs/` directory. Before profiling, the runner regenerates
and compares the aggregate from those raw runs, requiring at least seven
matched native-Linux full profiles with passed invariants and the supplied
published commit/tree. It never substitutes the older checked-in calibration.
Collect both directories outside the source tree, then package only verified
evidence for retention.

The archive retains symbolized CPU reports, Heaptrack allocation/copy reports,
raw profile data, exact commands, every matching Phase 0 raw baseline, a
bounded worker/cell and Wasmtime allocator/COW experiment matrix, and a
machine-readable aggregate. Heaptrack allocation categories are bound to the
nearest non-plumbing owner frame scanned from each folded stack's allocation
leaf; absent direct samples are reported as not observed at profiler resolution
rather than as zero cost. It refuses failed or incomplete hard-invariant
evidence and uses the issue-38 noise bands only as an adoption gate; a faster
single or small candidate set is not a Phase 0 optimization decision. See
[the profiling handoff](../../docs/phase-0-hot-path-profiling.md) for the
guardrails, decisions, and Phase 1 ownership.

The current v5 native-Linux archive is
[`native-linux-2026-08-30-52ac4754`](profiling/native-linux-2026-08-30-52ac4754/README.md).
It covers all eight required workloads and candidates, retains a complete
full-invariant proof, and was independently reassembled and regenerated by the
authorized gate. Its `aggregate.json` and `PROFILE.md` are directly readable;
its complete raw
profile tree is losslessly retained as checksummed `raw-evidence.tar.zst`
fragments for practical Git storage. The archive identifies durable source commit
`52ac47542a05c0a1263f78a14c04a5c2e6b761f3` and tree
`cac3ececdbd0b5734691c30c0283fccff169a5f5`. The August 29 v3 archive remains
historical and is not substituted for this input.

## Native-Linux long-running resource soak

Issue #39 has a retained, explicit native-Linux resource-soak result. It is not
a PR smoke workload. A replacement or revalidation run must use the final
Phase 0 configuration from a clean worktree on a native Linux host or VM, with
the exact source commit or tag published first:

~~~bash
tools/run_phase0_resource_soak.sh \
  --published-source-commit <reachable-final-commit> \
  --published-source-tree <reachable-final-tree> \
  --published-source-ref <durable-branch-or-tag> \
  --final-configuration-commit <reachable-final-commit> \
  --calibration /var/tmp/phase0-evidence/calibration/aggregate.json \
  /var/tmp/phase0-evidence/soak
~~~

The wrapper refuses WSL, containers, missing native `/proc` probes, missing
toolchain or fixture inputs, a dirty worktree, a source-tree mismatch, an
existing archive directory, and test-only output. It starts at least three
independent processes. Each one uses the real Phase 0 composition with 1,000
excluded warm-up activations, 100,000 normal measured fresh-store activations,
and additional real at-capacity and bounded-queue batches every ten measured
batches.

Each archive retains `runs/run-NN/raw.json`, before/after host observations,
command status, the raw-file hash, `aggregate.json`, and `SOAK.md`. Raw batch
samples record RSS, VM, PSS/private mappings when exposed, process/child/thread
and socket/FD topology, pool/runner/backend/log/cache/timing-store state, and
post-release/shutdown evidence. New raw runs also retain pre-runtime and
post-warm-up process snapshots: final measured FDs must not exceed the
post-warm-up baseline and post-release/post-shutdown FDs must not exceed the
pre-runtime baseline. The
aggregate applies the #38 calibrated RSS noise band to RSS and (where
available) PSS/private material-growth triage only after CPU, memory, kernel,
virtualization, toolchain, allocator, fixture, and relevant configuration
identity—including prepared-cache enablement, Wasmtime allocator mode, and
initialized-memory COW—are recorded as matched. Otherwise it blocks the
calibrated comparison and authorization. It reports rolling ranges, final-window deltas, robust
late-window slopes and peaks. A material growth
result is not fixed by increasing the allowance: it remains failed until a
retaining subsystem or focused follow-up issue is recorded. Record that
diagnosis in the same archive with `--retaining-subsystem <name>` and/or
`--followup-issue <URL-or-number>`.

The current final-config raw evidence is
[`native-linux-2026-08-30-52ac4754`](soak/native-linux-2026-08-30-52ac4754/README.md). It retains all three machine-readable
raw process series losslessly in a checksummed zstd archive, alongside
the aggregate, concise report, host observations, command statuses, and
raw-file hashes, without duplicating earlier attempts. Its hard invariants,
full descriptor lifecycle, release/shutdown topology, and calibrated
late-window RSS/PSS/private/VM analysis pass against the matching seven-process
calibration. The package participates in the August 30 authorized receipt but
does not make an authorization decision by itself. The August 29 soak remains
historical evidence.
