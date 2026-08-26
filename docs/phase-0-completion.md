# Phase 0 completion gate

Phase 0 is complete when issue #25 is merged. The feasibility gate is **PASS** based on the checked-in full-profile evidence from issue #24 and the clean-checkout gate introduced here. This decision authorizes Phase 1 to productionize the proven foundation; it does not promote the Phase 0 spike into a production API.

## Gate command

After installing the pinned prerequisites from [`development/toolchain.md`](development/toolchain.md):

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make phase0-gate
```

`make phase0-gate` is the complete local gate. It runs workspace formatting, compilation, Clippy, and unit tests; validates repository contracts and generated Component Model fixtures; executes the real `latentd phase0-spike` integration and containment suite; then runs the full Phase 0 resource/baseline profile. Generated evidence is written to `target/phase0-gate/full/`.

Pull requests use the same sequence with the smaller deterministic benchmark sample count through `make phase0-gate-smoke`. The smoke profile changes sample counts only; it does not remove success, failure, cleanup, saturation, or topology scenarios.

The final machine-readable receipt is `target/phase0-gate/<profile>/gate-summary.json`. The gate fails unless every required issue-24 invariant remains present and passing and all required terminal outcomes are observed.

## Dependency closure

The Phase 0 implementation chain is complete:

| Issue | Delivered proof | Status |
|---|---|---|
| #18 | pinned Component Model/build toolchain | closed |
| #19 | real Rust echo component fixture | closed |
| #20 | fixed generic execution-cell pool | closed |
| #21 | generated WIT bindings and Wasmtime component invocation | closed |
| #22 | trap/timeout/cancellation/memory containment and reclamation | closed |
| #23 | executable `latentd` end-to-end spike and recovery harness | closed |
| #24 | activation, saturation, topology, cleanup, and resource baselines | closed |

Phase 1 issue #2 explicitly depends on #25 and requires this completion report as implementation input.

## Reference evidence

The authoritative checked-in full-profile evidence is:

- [`../benchmarks/phase0/raw-results.json`](../benchmarks/phase0/raw-results.json) — machine-readable `latent.phase0.baseline.v2` result.
- [`../benchmarks/phase0/BASELINE.md`](../benchmarks/phase0/BASELINE.md) — human-readable rendering of the same run.
- [`phase-0-baselines.md`](phase-0-baselines.md) — benchmark method and comparison rules.
- [`phase-0-spike.md`](phase-0-spike.md) — executable spike contract and limitations.

The reference run recorded Linux/x86_64 under WSL2, Rust 1.97.1, Wasmtime 47.0.3, release-mode benchmark code, a two-cell fixed pool, a four-waiter bounded queue, and two configured runtime workers. The raw document records the exact kernel, CPU, memory, target, fixture digest, configuration, samples, and repository commit used by the run.

All 19 reference invariant checks passed. Notable observations include:

- 12 independent real-executable success samples passed with clean shutdown and unchanged configured topology.
- Real-executable trap, timeout, and same-composition post-trap recovery probes passed.
- Success, declared domain error, trap, timeout, explicit cancellation, memory-pressure/resource exhaustion, bounded queue saturation, and cause-specific recovery were observed through the retained runtime path.
- The measured pool never exceeded two active leases; the bounded saturation probe reached exactly four queued waiters and rejected the next waiter as `resource_exhausted`.
- 343 activation samples returned to zero active lease/waiter/cancellation/invocation/store/host-state/component-instance/temporary-buffer/cancellation-probe/retained-log state, with no quarantine or cache growth.
- Process count remained one, configured Tokio workers remained two while the runtime was active, listeners and open sockets remained zero, and cell capacity remained two.
- The Linux process probe observed one bounded Wasmtime epoch-interruption helper thread after preparation, so raw OS thread count ranged from three to four while configured runtime workers stayed fixed. Shutdown returned to one process thread and zero runtime workers.
- File descriptors remained constant at five. Steady-state RSS ranged by 352,256 bytes, below the explicit 64 MiB allowance; this is a bounded-growth observation, not proof of byte-for-byte deallocation.
- Explicit prepared-component release returned the cache to zero entries/bytes, and final backend live-resource counts were all zero.

## What Phase 0 proved

Phase 0 proved a narrow local feasibility statement:

1. a real Rust Component Model guest can be built reproducibly from the pinned toolchain and generated WIT bindings;
2. the host can load and invoke that component through real Wasmtime Component Model bindings;
3. a fixed generic cell pool can lease/reclaim capacity without per-service idle execution allocation;
4. success and declared guest-domain errors cross the typed boundary correctly;
5. invalid input/component configuration fails before a cell is left leased;
6. guest trap, deadline timeout, explicit cancellation, and memory pressure remain activation-local in the tested composition and a following activation succeeds;
7. bounded queue admission and cleanup/resource invariants hold for the measured finite run; and
8. the executable spike can complete without opening an invocation listener or creating service-specific processes, worker pools, sockets, or cells.

These statements are feasibility evidence only. They are not public API, security, capacity, latency, or production-readiness guarantees.

## Spike audit and Phase 1 handoff

| Classification | Phase 0 asset | Phase 1 action |
|---|---|---|
| Retain | WIT as capsule contract authority, generated guest/host bindings, pinned/reproducible echo fixture | Keep as the maintained integration fixture and contract-generation foundation. |
| Retain | `ExecutionBackend`, `CellPool`, affine `CellLease` lifecycle, fixed-capacity accounting | Preserve the seams and invariants; production composition may add implementations without weakening them. |
| Retain | Machine-readable baseline schema/evidence and resource probes | Preserve as regression evidence so Phase 1 can quantify productionization cost/benefit. |
| Harden | Wasmtime engine limits, fresh-store-per-activation cleanup, timeout/cancellation interruption, bounded host logging | Turn spike constants into explicit production policy/configuration and telemetry while keeping fail-closed cleanup. |
| Harden | Prepared-component cache | Replace the one-entry spike configuration with a bounded production cache keyed by the final artifact/trust/engine compatibility model. |
| Generalize | `Phase0ActivationRunner` and `phase0_composition` | Move orchestration into Phase 1 composition with routing, admission, release resolution, budgets, and generic invocation while preserving activation-local ownership. |
| Generalize | Echo-specific typed invocation and domain-error decoding | Generate/dispatch maintained contract worlds without hard-coding the echo export or echo media types into shared runtime behavior. |
| Generalize | Local capsule path loading and hard-coded test identity/trace values | Replace with the local release catalog, real invocation identity/context, and artifact verification defined by Phase 1. |
| Rewrite | `latentd phase0-spike` JSON/exit-code surface | Treat it as a test harness, not a compatibility promise. Replace it with Phase 1 CLI/RPC surfaces; retain only while it provides useful regression coverage. |
| Delete after replacement | test-only containment guest control strings and benchmark-only composition entry points | Keep in test/benchmark scope until equivalent Phase 1 containment tests exist, then remove any path that can leak into product dispatch. |

### Known shortcuts and debt

- The executable accepts one local capsule and invokes the echo contract; there is no generic multi-service/function dispatch.
- The spike embeds local test identities, trace identifiers, fixture paths, cache sizes, and other deterministic values chosen for proof and measurement rather than product configuration.
- The containment fixture deliberately exposes test-only trap/infinite-loop/memory-pressure behaviors.
- `latentd phase0-spike` is explicitly `production_ready=false` and `phase1_api_compatible=false` in its machine output.
- There is no route snapshot, admission controller, deployment catalog, persistent management surface, capability broker, durable state/effect protocol, remote transport, or production telemetry path in the demonstrated composition.
- The reference resource probes depend on Linux `/proc`; comparable non-Linux measurement support remains open.
- The run is finite and local. It does not establish long-duration leak freedom, multi-tenant isolation, cluster behavior, or capacity/SLO guarantees.

### Phase 1 questions

Phase 1 must decide, and document, at least:

- the generic contract/function dispatch and generated-binding strategy;
- the production cache key/admission/trust model and whether AOT artifacts are introduced;
- the final trust-class/process-isolation topology without making it service-count dependent;
- how expensive resource/containment invariants become required CI rather than occasional benchmarks; and
- when the Phase 0 CLI and benchmark-only composition can be deleted without losing regression coverage.

## Explicitly not established

This gate does **not** establish production security, stable public APIs, generic multi-service dispatch, persistent deployment management, production scheduling, comprehensive telemetry, performance SLOs, cluster behavior, durable state/effect semantics, remote-call equivalence, or the 100,000 dormant-service invariant. Those remain Phase 1 or later work.
