# Phase 0 completion gate

**Gate status: PENDING — Phase 1 is not authorized for the current branch.**

The retained August 29 receipt records a prior clean native-Linux checkout that ran `make phase0-gate` at commit
`54d02679aff757d4bf25d16e088b32d45682cb7f` (tree
`b77e4efa1cd46628efcbfebed6e3b0c05feade28`) and exited 0. Its retained
[gate summary](../benchmarks/phase0/receipts/native-linux-2026-08-29-54d02679/gate-summary.json)
records its historical `status: "pass"`, `authorization_status: "authorized"`,
`phase1_authorized: true`, and an empty `blockers` array. It cannot authorize
the current branch because both the verifier and the measured execution tree
have changed. Fresh native-Linux calibration, profiling, soak, and a separate
clean-checkout full-gate receipt are required.

The historical measured calibration, profiling, and soak inputs all came from commit
`a724a5e35234175f1001d1983e4411296ffa6b78` (tree
`c06ace2ae0f503495fa5bf87710ae5fc74c7ef50`). Their canonical
execution-relevant identity was
`sha256:d9ec14a46695eb2afedc07b70b114686163f82a0cfc216f65c521c541ad44191`,
which that receipt verified against its clean checkout. GitHub issue state is
not evidence. Only a new receipt with raw verification, identity comparison,
and a fresh baseline can establish current authorization.

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
4. writes `gate-summary.json`, which rebuilds the calibration, profile, and
   soak aggregates from their retained raw inputs; verifies archive manifests,
   hashes, paths, and file sets; then compares the regenerated results with
   the checked-in aggregates before evaluating the fresh baseline.

`make phase0-gate` returns non-zero whenever a final receipt is not
`authorized`; it still writes the receipt so the specific blocker is
reviewable. The retained full run is historical. The current branch must
satisfy the same fail-closed checks with newly collected applicable evidence.

CI uses `make phase0-gate-smoke`. It runs the same contract, executable, and
baseline path with smaller deterministic sample counts and records the receipt,
but does not claim Phase 1 authorization. Its output explicitly distinguishes
`Phase 0 smoke validation: PASS` from `Phase 1 authorization: BLOCKED` so a
correctness smoke result cannot be mistaken for completion.

## Historical evidence ledger — not eligible for current authorization

| Input | Machine-readable evidence | Gate result |
|---|---|---|
| Fresh full baseline | [receipt baseline](../benchmarks/phase0/receipts/native-linux-2026-08-29-54d02679/baseline/BASELINE.md), compressed raw result, and checksums | historical pass: 20 required hard checks and all required terminal outcomes |
| Native-Linux calibration | [`aggregate.json`](../benchmarks/phase0/calibration/native-linux-2026-08-29-a724a5e3/aggregate.json) and checksummed raw archive | historical pass: seven full-profile runs with fixed hard invariants and advisory comparison bands |
| CPU/allocation profiling | [`aggregate.json`](../benchmarks/phase0/profiling/native-linux-2026-08-29-a724a5e3/aggregate.json) and checksummed sharded raw archive | historical pass: eight workloads, guardrails, and seven explicit optimization decisions |
| Resource soak | [`aggregate.json`](../benchmarks/phase0/soak/native-linux-2026-08-29-a724a5e3/aggregate.json), [`SOAK.md`](../benchmarks/phase0/soak/native-linux-2026-08-29-a724a5e3/SOAK.md), and checksummed raw archive | historical pass: three matched 100,000-activation processes, complete lifecycle evidence, and no calibrated material growth |
| Completion receipt | [`gate-summary.json`](../benchmarks/phase0/receipts/native-linux-2026-08-29-54d02679/gate-summary.json) and [receipt manifest](../benchmarks/phase0/receipts/native-linux-2026-08-29-54d02679/receipt.manifest.sha256) | historical result; not eligible to authorize this branch |

## Recorded environment, configuration, and observations

The JSON aggregates above are cached conclusions, not trust roots. The gate
validates the underlying raw runs, host observations, execution-status records,
fixture/configuration/toolchain identities, profile artifacts, manifests, and
hashes; it then regenerates each aggregate with the repository aggregation
logic. The receipt also retains the current commit/tree and a canonical hash of
the execution-relevant Git entries. Every evidence set must have that same
canonical identity; documentation-only differences remain visible through the
recorded commit/tree but cannot hide an execution-affecting change.

- The historical calibration, `perf`/Heaptrack archive, and soak were measured on
  one native-Linux host from the same execution-relevant tree at
  `a724a5e3…` / `c06ace2a…`. The retained commit/tree changes are auditable,
  while the canonical identity is the strict applicability comparison.
- The calibration retains seven full-profile runs. The profile covers cold
  preparation, prepared-cache reuse, first/warm execution, failure
  containment, cleanup, and both contention modes. Its decision ledger has
  seven retained/deferred/rejected decisions over eight candidates.
- The soak retains three independent native-Linux processes, each with 1,000
  excluded warm-ups, 100,000 measured fresh-store activations, real capacity
  and queue saturation batches, sampled post-warm-up resource series, and
  release/shutdown observations. Its strict aggregate reports matched
  calibration applicability, complete evidence, and passed descriptor
  lifecycle checks.
- The historical full baseline ran at `54d02679…` / `b77e4efa…` against those
  retained inputs and passed all 20 required checks. The receipt's raw result
  is compressed losslessly and checked alongside the complete receipt manifest.

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

## Gate completion and audit handoff

The full receipt and raw evidence are retained in the repository as immutable
historical artifacts, including archive manifests, checksums, reports,
aggregates, and the losslessly compressed baseline result. The current
execution-relevant source and verifier have changed. Fresh evidence and a new
authorized receipt are required before this branch can establish authorization.

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

An authorized Phase 0 gate establishes only a local feasibility and
measurement boundary. It does not establish production security, stable public
APIs, generic multi-service dispatch, persistent deployment management,
production scheduling or telemetry, performance SLOs, dormant-service density,
multi-node operation, Kubernetes replacement, realistic workloads, or
arbitrary-duration leak freedom. Phase 1 issue #2 remains dependent on this
gate and must consume this evidence/handoff rather than duplicate the spike.
