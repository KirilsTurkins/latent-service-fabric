# Phase 0 completion gate

**Gate status: BLOCKED — Phase 1 is not yet authorized.**

The Phase 0 executable spike has completed its implementation chain, but the
completion receipt intentionally fails closed until every retained evidence
archive is conclusive. The checked-in native-Linux resource soak is
structurally valid and passes its hard runtime checks, but its aggregate status
is `inconclusive`; it cannot establish the required calibrated post-warm-up
plateau.

The GitHub state of issue #39 is not itself evidence: its checked-in aggregate
and raw-evidence checksum remain the authority for this gate. Do not mark
Phase 0 complete, or start Phase 1 as though it were complete, merely because
an issue was closed while its retained evidence is incomplete.

## One clean-checkout command sequence

After installing the pinned prerequisites in
[`development/toolchain.md`](development/toolchain.md), run:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make phase0-gate
```

The command creates a new directory beneath `target/phase0-gate/`, then:

1. runs repository formatting, builds, Clippy, Rust tests, contract/component
   validation, SDK checks, and repository-tool tests;
2. runs the real `latentd phase0-spike` executable E2E and containment suite;
3. runs a fresh full executable baseline, including the real Wasmtime path,
   capacity/queue saturation, recovery, cleanup, and topology probes; and
4. writes `gate-summary.json`, which validates that fresh baseline together
   with the retained calibration, profile, and soak evidence.

`make phase0-gate` returns non-zero whenever the final receipt is not
`authorized`; it still writes the receipt so the specific blocker is
reviewable. Today that final step is expected to fail because the retained
soak has an incomplete calibration/descriptor-lifecycle comparison.

CI uses `make phase0-gate-smoke`. It runs the same contract, executable, and
baseline path with smaller deterministic sample counts and records the receipt,
but does not claim Phase 1 authorization. The smoke job prevents a code
regression from being mistaken for a missing long-running native-Linux run.

## Evidence ledger

| Input | Machine-readable evidence | Gate result |
|---|---|---|
| #24 executable baseline | [`raw-results.json`](../benchmarks/phase0/raw-results.json) and [`BASELINE.md`](../benchmarks/phase0/BASELINE.md) | pass: 19 hard checks and all required terminal outcomes |
| #38 native-Linux calibration | [`aggregate.json`](../benchmarks/phase0/calibration/native-linux-2026-08-27-reachable-source/aggregate.json) and retained seven runs | pass: seven matched full-profile runs, fixed hard invariants, advisory comparison bands |
| #40 CPU/allocation profiling | [`aggregate.json`](../benchmarks/phase0/profiling/native-linux-2026-08-27-de2337906/aggregate.json) and checksummed raw archive | pass: required workloads, guardrails, and explicit optimization decisions |
| #39 resource soak | [`aggregate.json`](../benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/aggregate.json), [`SOAK.md`](../benchmarks/phase0/soak/native-linux-2026-08-27-6250b978/SOAK.md), and checksummed raw archive | **blocked**: aggregate, calibration applicability, evidence completeness, and descriptor lifecycle are `inconclusive`/`incomplete` |

## Recorded environment, configuration, and observations

The JSON aggregates above are the machine-readable record of exact commands,
host observations, source/tree identities, fixture digests, configuration,
raw-file hashes, raw/aggregate results, and limitations. The concise report is
intentionally a map to that evidence rather than a replacement for it.

- The #24 full profile is a historical WSL2/Linux x86_64 observation with a
  two-cell fixed pool, four-waiter bounded queue, two configured runtime
  workers, one bounded prepared component, and fresh invocation stores. Its
  343 activation samples pass all 19 hard checks; the raw document records its
  startup, cold/warm, containment/recovery, cleanup, saturation, RSS, VM, FD,
  thread, socket, and topology observations.
- The #38 native-Linux reference retains seven full-profile runs from the
  durable source commit `49e24fdbee1a3cde1a09fdb3bf8dcf640cc956c3` and tree
  `88e8875b7be7e46b4702c15d5c8c2f26c1e4a037`. Its aggregate records per-metric
  min/median/max/MAD/CV, run-level outliers, and advisory comparison bands;
  these are regression-detection aids, never production SLOs or
  cross-machine claims.
- The #40 native-Linux `perf`/Heaptrack archive comes from source commit
  `de2337906a4942e47611124a1c2217949abb58dc` and tree
  `0a32896faa58da7f34662cbf3be97670d6d1de4c`. It covers cold preparation,
  prepared-cache reuse, first/warm execution, failure containment, cleanup,
  and both contention modes. The default remains the fixed 2-worker/2-cell,
  bounded-cache, on-demand allocator, COW-enabled configuration; the profile
  records explicit retain/defer/reject decisions for every candidate.
- The #39 archive comes from final-configuration commit
  `6250b9782ffc4174676d2d72bd023dbfc38c39d7` and tree
  `65ba341221ea89e107a3e0e3c4b0aed7e26efd9b`. It retains three independent
  processes, each with 1,000 excluded warm-ups, 100,000 measured activations,
  100 at-capacity batches, 100 bounded-queue batches, sampled post-warm-up
  resource series, release/shutdown observations, and a checksummed raw
  archive. Its exact interval method, rolling ranges, final-window deltas,
  late-window slopes, peaks, and unsupported probes are in `aggregate.json`
  and `SOAK.md`.

The current soak archive retains three native-Linux processes, each with 1,000
excluded warm-ups, 100,000 measured fresh-store activations, repeated success
and failure/recovery work, and 100 real batches of each saturation mode. Its
logical-resource, measured-topology, explicit-release, and runtime-shutdown
checks pass. It is nevertheless not a conclusive plateau result because:

- the #38 calibration did not serialize the selected prepared-cache, Wasmtime
  allocator, or initialized-memory COW configuration;
- the historical soak host observations lack VM and allocator provenance; and
- the raw soak records predate serialized pre-runtime and post-warm-up file
  descriptor baselines.

These are measurement/provenance gaps, not grounds to increase an allowance
or reinterpret an inconclusive archive as a pass.

## What the gate already proves

For the recorded local component and native-Linux environments, the evidence
proves that:

- generated WIT guest and host bindings build a real Rust echo Component Model
  guest and invoke it through Wasmtime;
- echo success and declared domain errors cross the real typed boundary;
- invalid component input is rejected by the executable/containment validation
  path before an activation can remain leased;
- trap, timeout, explicit cancellation, and memory-pressure failures remain
  activation-local and are followed by successful cause-specific recovery;
- every measured terminal path returns its cell or reports quarantine, with no
  active lease, waiter, store, cancellation registration, activation host
  state, temporary buffer, or unbounded history retained;
- configured runtime workers, process count, listeners/sockets, and cell
  capacity remain fixed throughout the measured spike lifecycle; and
- real at-capacity and bounded-queue workloads reach their configured bounds
  and return admitted work to a clean baseline.

The exact checks, scenarios, executable samples, and raw observations are
validated by [`tools/validate_phase0_gate.py`](../tools/validate_phase0_gate.py).
The validator rejects missing, duplicate, unexpected, or failed hard checks;
missing terminal scenarios; an altered raw-evidence archive; weakened
fresh-store/fixed-topology guardrails; and incomplete evidence presented as an
authorization.

## Required work to authorize Phase 1

1. Run a fresh seven-process native-Linux calibration from the final ordinary
   configuration, recording prepared-cache enablement, `on_demand` Wasmtime
   allocation, initialized-memory COW, allocator provenance, and VM
   provenance.
2. Run a fresh, matching three-process native-Linux soak with serialized
   pre-runtime and post-warm-up descriptor baselines, all required raw samples,
   and the calibrated late-window resource comparison.
3. Preserve the raw archive/checksums and regenerate its aggregate. The result
   must be `pass` for the aggregate, evidence completeness, calibration
   applicability, and descriptor lifecycle; a material-growth result requires
   a focused root-cause issue, not a raised allowance.
4. Update the checked-in evidence paths. At that point `make phase0-gate` must
   finish with an `authorized` receipt before the roadmap can mark Phase 0
   complete.

## Audit and Phase 1 handoff

| Classification | Phase 0 asset | Phase 1 action |
|---|---|---|
| Retain | WIT authority, generated bindings, reproducible echo fixture | Keep as the maintained integration fixture and contract-generation foundation. |
| Retain | `ExecutionBackend`, `CellPool`, affine `CellLease`, fixed-capacity accounting | Preserve the seams and invariants while adding production implementations. |
| Retain | Machine-readable baseline, calibration, profile, and soak schemas | Keep as regression evidence; do not replace like-for-like comparison rules with SLO claims. |
| Harden | Wasmtime limits, fresh-store cleanup, interruption, bounded logging | Turn spike constants into explicit policy/configuration and telemetry without weakening cleanup proof. |
| Harden | One-entry prepared-component cache | Generalize to a bounded cache keyed by artifact, trust, and engine compatibility. |
| Generalize | `Phase0ActivationRunner` and `phase0_composition` | Add routing, admission, release resolution, budgets, and generic invocation without retaining echo-specific dispatch. |
| Rewrite | `latentd phase0-spike` JSON/exit-code surface | Treat it as a harness, not a public compatibility promise; replace it with Phase 1 CLI/RPC surfaces. |
| Delete after replacement | Test-only trap/infinite-loop/memory-pressure controls and benchmark-only entry points | Remove them from product dispatch when equivalent Phase 1 containment tests exist. |

Phase 1 must retain fresh invocation-owned stores, host state, import tables,
instances, limiters, and activation contexts; fixed node topology; bounded
state; activation-local failure containment; and affirmative cleanup proof.
The profile decision record defers worker/cell policy and Wasmtime/cache/value
work to #8 and #9, lifecycle-envelope work to #11, and rejects store/instance
reuse plus untrusted AOT/cache/snapshot/native-execution shortcuts in Phase 0.

## Explicit limits

Even an authorized Phase 0 gate would establish only a local feasibility and
measurement boundary. It would not establish production security, stable public
APIs, generic multi-service dispatch, persistent deployment management,
production scheduling or telemetry, performance SLOs, dormant-service density,
multi-node operation, Kubernetes replacement, realistic workloads, or
arbitrary-duration leak freedom. Phase 1 issue #2 remains dependent on this
gate and must consume this evidence/handoff rather than duplicate the spike.
