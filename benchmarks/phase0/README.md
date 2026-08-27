# Phase 0 baseline and calibration evidence

raw-results.json and BASELINE.md are the original full-profile observation.
They remain useful as historical evidence, but their WSL2 environment means
they are not the Phase 1 variance reference.

The authoritative native-Linux reference is retained under
benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source. Its
CALIBRATION.md and aggregate.json describe seven independent full-profile
processes, link every individual raw run, and retain published/execution
Git-tree provenance. The earlier
native-linux-2026-08-27 archive is retained unchanged as superseded audit
evidence because its recorded source commit was not reachable.

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
