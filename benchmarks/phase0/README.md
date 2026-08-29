# Phase 0 baseline and calibration evidence

raw-results.json and BASELINE.md are the original full-profile observation.
They remain useful as historical evidence, but their WSL2 environment means
they are not the Phase 1 variance reference.

The authoritative native-Linux reference for the selected ordinary Phase 0
configuration is retained under
benchmarks/phase0/calibration/native-linux-2026-08-28-6a64f063. Its CALIBRATION.md and
aggregate.json describe seven independent full-profile processes, link every
individual raw run, and retain published/execution Git-tree provenance. It
explicitly records prepared-cache enablement, `on_demand` Wasmtime allocation,
and initialized-memory COW. The duplicate unreachable calibration archive was
removed; the historical reachable reference remains only where the retained
issue-40 profile archive needs its original comparison input.

Generate a new reference only from a clean worktree on a stable native-Linux
host or VM:

~~~bash
tools/run_phase0_calibration.sh benchmarks/phase0/calibration/native-linux-YYYY-MM-DD
~~~

The command refuses WSL and detected containers, requires a fresh output
directory, records source/environment provenance before and after every run,
and invokes tools/run_phase0_baselines.sh full seven times. Each invocation
still validates contracts and fixtures and still treats all containment,
topology, capacity, reclamation, and resource checks as pass/fail.

For an evidence archive that will be published from a different local Git
commit object, first publish a durable branch or tag, then give the wrapper its
reachable commit and tree IDs:

~~~bash
tools/run_phase0_calibration.sh \
  --published-source-commit <reachable-commit-sha> \
  --published-source-tree <reachable-tree-sha> \
  benchmarks/phase0/calibration/native-linux-YYYY-MM-DD
~~~

The wrapper rejects a local worktree whose Git tree differs from that published
tree. Each run and aggregate retain the published commit/tree and local
execution commit/tree, so replacing a recorded commit is never an unsupported
text substitution.

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
  benchmarks/phase0/profiling/native-linux-YYYY-MM-DD
~~~

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

The accepted native-Linux archive is
[native-linux-2026-08-27-de2337906](profiling/native-linux-2026-08-27-de2337906/README.md).
Its `aggregate.json` and `PROFILE.md` are directly readable; its complete raw
profile tree is losslessly retained as checksummed `raw-evidence.tar.zst`
fragments for practical Git storage. The archive identifies durable source commit
`de2337906a4942e47611124a1c2217949abb58dc` and tree
`0a32896faa58da7f34662cbf3be97670d6d1de4c`.

## Native-Linux long-running resource soak

Issue 39 adds a separate, explicit native-Linux resource-soak command. It is
not a PR smoke workload. After issue 40 has selected and merged the final
pre-Phase-1 configuration, run it from a clean worktree on a native Linux host
or VM, first publishing the exact source commit or tag:

~~~bash
tools/run_phase0_resource_soak.sh \
  --published-source-commit <reachable-final-commit> \
  --published-source-tree <reachable-final-tree> \
  --final-configuration-commit <reachable-final-commit> \
  --calibration benchmarks/phase0/calibration/native-linux-2026-08-28-6a64f063/aggregate.json \
  benchmarks/phase0/soak/native-linux-YYYY-MM-DD
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
initialized-memory COW—are recorded as matched. Otherwise it emits an explicit
inconclusive result. It reports rolling ranges, final-window deltas, robust
late-window slopes and peaks. A material growth
result is not fixed by increasing the allowance: it remains failed until a
retaining subsystem or focused follow-up issue is recorded. Record that
diagnosis in the same archive with `--retaining-subsystem <name>` and/or
`--followup-issue <URL-or-number>`.

The retained final-config raw evidence is
[native-linux-2026-08-28-6a64f063](soak/native-linux-2026-08-28-6a64f063/README.md). It retains all three machine-readable
raw process series losslessly in a checksummed 52 KiB zstd archive, alongside
the aggregate, concise report, host observations, command statuses, and
raw-file hashes, without duplicating earlier attempts. Its hard invariants,
full descriptor lifecycle, release/shutdown topology, and calibrated
late-window RSS/PSS/private/VM analysis pass against the matching seven-process
calibration. Issue #39 is therefore complete for the recorded local
configuration; this remains observational evidence rather than a production or
arbitrary-duration claim.
