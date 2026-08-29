# Phase 0 completion gate

**Gate status: BLOCKED — Phase 1 is not yet authorized.**

Issue #39 is complete: the checked-in seven-process native-Linux calibration
and three-process 100,000-activation soak are both independently regenerated
from complete raw evidence and the soak aggregate is `pass`.

The completion gate fails closed until a clean-checkout receipt validates every
retained archive, raw measurement, source identity, and fresh-baseline
requirement. GitHub issue state is not itself evidence: the gate's raw
verification and execution-identity checks remain the authority for
authorization and future revalidation.

## Status at a glance

| Scope | Current status | What it means |
|---|---|---|
| Retained #39 calibration and resource soak | pass | The recorded native-Linux configuration has complete, verified plateau evidence. |
| Full Phase 0 completion gate | blocked | A current clean checkout has not produced an `authorized` full receipt. |
| CI smoke sequence | validation only | A smoke pass exercises deterministic coverage; it never authorizes Phase 1. |
| Production readiness and public API compatibility | not claimed | Neither is a Phase 0 outcome. |

Some reports inside the retained evidence archives use the historical tense
appropriate to their measurement runs. They are immutable evidence, not the
current status source; this document and the machine receipt are authoritative
for authorization.

## Run the full gate

Run the full gate from a clean Linux or WSL checkout. WSL is sufficient to
verify retained evidence and produce a receipt. It is **not** sufficient to
collect replacement calibration, profiling, or soak evidence: those wrappers
require a clean native-Linux host or VM and reject WSL and containers.

Before running the gate, confirm that Git sees no tracked or untracked user
changes:

```bash
git status --porcelain --untracked-files=all
```

The gate creates its own ignored output under `target/phase0-gate/`. Other
untracked output can block authorization, so use an isolated clean clone or
worktree when in doubt.

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
4. writes `gate-summary.json`, which rebuilds the calibration, profile, and
   soak aggregates from their retained raw inputs; verifies archive manifests,
   hashes, paths, and file sets; then compares the regenerated results with
   the checked-in aggregates before evaluating the fresh baseline.

`make phase0-gate` returns non-zero whenever the final receipt is not
`authorized`; it still writes the receipt so the specific blocker is
reviewable. The passing #39 calibration and soak do not remove the raw,
identity, and fresh-baseline checks for every retained evidence source.

## Interpret the result

| Command | Baseline | Exit zero means | Phase 1 authorization |
|---|---|---|---|
| `make phase0-gate` | full | The full receipt is `authorized`. | Required and granted only by this result. |
| `make phase0-gate-smoke` | deterministic smoke | The smoke validation completed. | Never granted; its receipt may remain `blocked`. |

The smoke output explicitly distinguishes `Phase 0 smoke validation: PASS`
from `Phase 1 authorization: BLOCKED`, so deterministic correctness coverage
cannot be mistaken for a completed full gate. When a full run blocks, inspect
the retained `gate-summary.json` and address its `blockers`; GitHub issue state
does not override them.

## Evidence ledger

| Input | Machine-readable evidence | Gate result |
|---|---|---|
| #24 executable baseline | [`raw-results.json`](../benchmarks/phase0/raw-results.json) and [`BASELINE.md`](../benchmarks/phase0/BASELINE.md) | pass: 19 hard checks and all required terminal outcomes |
| #38 native-Linux calibration | [`aggregate.json`](../benchmarks/phase0/calibration/native-linux-2026-08-28-6a64f063/aggregate.json) and retained seven runs | pass: seven selected-configuration full-profile runs, fixed hard invariants, advisory comparison bands |
| #40 CPU/allocation profiling | [`aggregate.json`](../benchmarks/phase0/profiling/native-linux-2026-08-27-de2337906/aggregate.json) and checksummed raw archive | pass: required workloads, guardrails, and explicit optimization decisions |
| #39 resource soak | [`aggregate.json`](../benchmarks/phase0/soak/native-linux-2026-08-28-6a64f063/aggregate.json), [`SOAK.md`](../benchmarks/phase0/soak/native-linux-2026-08-28-6a64f063/SOAK.md), and checksummed raw archive | pass: three matched 100,000-activation processes, complete lifecycle evidence, and no calibrated material growth |

## Recorded environment, configuration, and observations

The JSON aggregates above are cached conclusions, not trust roots. The gate
validates the underlying raw runs, host observations, execution-status records,
fixture/configuration/toolchain identities, profile artifacts, manifests, and
hashes; it then regenerates each aggregate with the repository aggregation
logic. The receipt also retains the current commit/tree and a canonical hash of
the execution-relevant Git entries. Every evidence set must have that same
canonical identity; documentation-only differences remain visible through the
recorded commit/tree but cannot hide an execution-affecting change.

- The #24 full profile is a historical WSL2/Linux x86_64 observation with a
  two-cell fixed pool, four-waiter bounded queue, two configured runtime
  workers, one bounded prepared component, and fresh invocation stores. Its
  343 activation samples pass all 19 hard checks; the raw document records its
  startup, cold/warm, containment/recovery, cleanup, saturation, RSS, VM, FD,
  thread, socket, and topology observations.
- The #38 selected-configuration native-Linux reference retains seven
  full-profile runs from durable source commit
  `6a64f0630cee9afa080d33f376aabadac724fa72` and tree
  `d27ff38ebbd891c5be949f54a0047522ed893d20`. It explicitly records the
  prepared cache, on-demand Wasmtime allocator, and initialized-memory COW
  settings. Its aggregate records per-metric min/median/max/MAD/CV, run-level
  outliers, and advisory comparison bands; these are regression-detection
  aids, never production SLOs or cross-machine claims.

- The #40 native-Linux `perf`/Heaptrack archive comes from source commit
  `de2337906a4942e47611124a1c2217949abb58dc` and tree
  `0a32896faa58da7f34662cbf3be97670d6d1de4c`. It covers cold preparation,
  prepared-cache reuse, first/warm execution, failure containment, cleanup,
  and both contention modes. The default remains the fixed 2-worker/2-cell,
  bounded-cache, on-demand allocator, COW-enabled configuration; the profile
  records explicit retain/defer/reject decisions for every candidate.
- The #39 archive comes from final-configuration commit
  `6a64f0630cee9afa080d33f376aabadac724fa72` and tree
  `d27ff38ebbd891c5be949f54a0047522ed893d20`. It retains three independent
  native-Linux processes, each with 1,000 excluded warm-ups, 100,000 measured
  fresh-store activations, 100 real batches of each saturation mode, sampled
  post-warm-up resource series, release/shutdown observations, and a
  checksummed raw archive. The strict aggregate is `pass`: calibration
  applicability and evidence completeness are matched/complete, descriptor
  lifecycle checks pass, and the retained late-window RSS/PSS/private/VM
  series has no material calibrated growth.

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
validated by [`tools/validate_phase0_gate.py`](../tools/validate_phase0_gate.py)
and [`tools/phase0_evidence.py`](../tools/phase0_evidence.py). The verifier
rejects malformed or synthetic archives, missing/additional/duplicate archive
paths, links, traversal attempts, changed raw artifacts, unverified profile
measurements, weakened guardrails, free-form optimization decisions, source
identity drift, and incomplete evidence presented as an authorization.

## When a full run blocks

#39's retained calibration and soak pass for their recorded configuration; the
closed issue does not waive the completion gate. Before Phase 1 is authorized,
run `make phase0-gate` from a clean checkout and address every receipt blocker
without weakening its raw-evidence, archive-integrity, source-identity, or
fresh-baseline checks.

1. If the run writes `gate-summary.json`, preserve it and read its `blockers`
   array. Do not edit an aggregate, archive, or receipt to clear a blocker: the
   verifier regenerates and compares those inputs.
2. If the run fails before a receipt exists, use the failing command or
   verifier diagnostic to correct the cause, then rerun from a clean checkout.
   A pre-receipt failure is not authorization or evidence that the receipt
   would pass.
3. If the blocker is execution-identity drift, regenerate the required native
   Linux evidence chain for the current executable configuration. A retained
   profile, calibration, or soak with a different execution-relevant identity
   cannot authorize the new tree.
4. Re-run the full gate from a clean checkout after the evidence and fresh
   baseline agree. Documentation-only changes are excluded from the execution
   identity but remain visible in the receipt.

An issue's closed state cannot substitute for this evidence.

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
