# Validation baseline

Updated on **2026-08-26** for the completed Phase 0 executable feasibility gate.

## Entry points

After installing the exact prerequisites in [`docs/development/toolchain.md`](docs/development/toolchain.md):

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
```

Use the general repository validation for contract/toolchain/SDK source consistency:

```bash
make validate
```

Use the complete Phase 0 feasibility gate for the executable/runtime proof:

```bash
make phase0-gate
```

PR CI uses `make phase0-gate-smoke`, which executes the same scenarios with smaller deterministic benchmark sample counts. Both commands are non-mutating for authoritative sources; generated artifacts remain under `target/` or Cargo `OUT_DIR`.

## Phase 0 gate sequence

`tools/run_phase0_gate.sh` is the single clean-checkout sequence required by issue #25. It fails fast and performs, in order:

1. `cargo fmt --all --check`;
2. `cargo check --workspace --all-targets --all-features --locked`;
3. `cargo clippy --workspace --all-targets --all-features --locked`;
4. `cargo test --workspace --all-targets --all-features --locked`;
5. `tools/run_phase0_spike.sh`, which runs repository-contract validation, builds the echo and containment components, runs the ignored real-executable E2E suite, and finishes through `latentd phase0-spike invoke-once`;
6. `tools/run_phase0_baselines.sh`, which repeats mandatory real-executable probes and runs the retained resource/containment/saturation measurements; and
7. a gate receipt check that rejects a baseline unless all required issue-24 invariants are present and passing and all required terminal outcomes were observed.

Full-profile output is written to `target/phase0-gate/full/`; smoke output is written to `target/phase0-gate/smoke/`. Each contains `baseline/raw-results.json`, `baseline/BASELINE.md`, and `gate-summary.json`.

## What repository-contract validation covers

`tools/validate_contracts.sh` validates the authoritative repository and contract layer before runtime execution:

- pinned Rust/MSRV/Component Model/Buf/Python/dependency versions and the committed `Cargo.lock`;
- Rust workspace structure and source consistency;
- all platform/example WIT packages, including generated Wasmtime host bindings and `wit-bindgen` guest bindings;
- the real Rust echo guest, its domain-error behavior, Component Model interface, reproducible two-build digest, generated capsule manifest, and absence of ambient WASI imports;
- the containment and oversized-log component fixtures used by runtime tests;
- real `latent-wasmtime` echo/containment integration tests through generated bindings;
- all Protobuf files through Buf and a deterministic descriptor set;
- all six JSON Schemas plus checked-in examples; and
- repository validator/tool tests.

`make validate` additionally compiles/syntax-checks the Rust, Go, TypeScript, Java, .NET, and C SDK surfaces with the pinned tool identities documented by the repository.

## What the executable gate covers

The ignored `apps/latentd/tests/phase0_spike_e2e.rs` test is only enabled by the spike/gate command because it requires the external Component Model toolchain. It launches the real `latentd` binary and proves:

- successful echo output through generated WIT bindings and real Wasmtime Component Model invocation;
- declared `empty-message` domain error mapping;
- invalid component bytes fail as invalid component/configuration without leasing a cell;
- guest timeout, guest trap, and explicit cancellation return the expected terminal classifications;
- a trap followed by a healthy invocation in the same composition recovers correctly;
- every executable result reports released/not-leased capacity, no retained activation-owned runtime state, unchanged configured topology, zero listeners, and clean shutdown.

The baseline runner adds memory pressure, bounded queue saturation, repeated cause-specific post-failure recovery, cold/warm latency distributions, activation phase timing, fixed-pool throughput, cache bounds, RSS/file-descriptor observations, and explicit post-release checks.

## Checked-in reference evidence

Issue #24 committed the full-profile evidence at:

- [`benchmarks/phase0/raw-results.json`](benchmarks/phase0/raw-results.json)
- [`benchmarks/phase0/BASELINE.md`](benchmarks/phase0/BASELINE.md)

All 19 invariant checks in that run are `PASS`. The report records the environment/configuration required to compare runs. See [`docs/phase-0-baselines.md`](docs/phase-0-baselines.md) for measurement methodology and [`docs/phase-0-completion.md`](docs/phase-0-completion.md) for the gate interpretation and Phase 1 handoff.

## Resource/topology interpretation

The measured composition uses a node-fixed two-cell pool and two configured runtime workers. Process count remains one, listener/open-socket counts remain zero, and no per-service process/thread/socket/cell is introduced. A bounded Wasmtime epoch-interruption helper thread appears after component preparation, so raw OS thread count may increase by one while configured runtime workers remain fixed; the reference run returns to one process thread after runtime shutdown.

Every measured activation terminal path returns its lease or records the expected pre-lease rejection. After each sample there is no active waiter, cancellation registration, invocation, store, host state, component instance, temporary buffer, cancellation probe, retained log, quarantine, or unbounded cache growth. Final explicit release clears the prepared cache and all live backend resource counts return to zero.

RSS validation intentionally checks bounded range/net growth after warm-up rather than byte-identical return because allocators and Wasmtime may retain bounded arenas. Linux `/proc` is currently required for the strict process/resource reference probe.

## Scope

Passing the Phase 0 gate establishes the finite local feasibility claims recorded in [`docs/phase-0-completion.md`](docs/phase-0-completion.md). It does not establish production security, stable APIs, routing/admission, generic multi-service dispatch, persistent deployment management, durable state/effects, remote-call equivalence, cluster behavior, production telemetry/SLOs, long-duration leak freedom, cross-platform resource-probe parity, or the 100,000 dormant-service invariant.
