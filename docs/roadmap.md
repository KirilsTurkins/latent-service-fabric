# Engineering roadmap

## Phase 0: executable spike — Phase 1 authorized

Repository contracts, one Rust echo capsule, one fixed cell pool, Wasmtime
component loading, timeout/trap containment, baseline measurements, native
Linux calibration, hot-path profiling, and a long-running resource soak are
implemented. Fresh native-Linux calibration, profiling, and soak packages from
commit `52ac4754…` were independently rebuilt from their raw evidence and bound
to a fresh full baseline at `b932a935…`. The retained August 30
[receipt](../benchmarks/phase0/receipts/native-linux-2026-08-30-b932a935/gate-summary.json)
records `pass`, `authorized`, and no blockers. See
[the completion gate](phase-0-completion.md).

The underlying measurements remain single-host observational evidence. Neither
an issue closure nor such an observation alone authorizes Phase 1. The full
receipt authorizes only because it validates the matched raw archives,
execution identity, profiling, resource soak, and fresh-baseline checks
together. Phase 1 builds on the retained runtime and invariants; Phase 0 does
not claim production readiness or Phase 1 API compatibility.

## Phase 1: single-node stateless fabric — in progress

The following foundations are implemented:

- [Executable build and generated bindings](development/build-foundation.md) (#2) and [cross-layer contracts](protocol/phase-1-contract-hardening.md) (#36).
- [Manifest codecs and schema-backed validation](protocol/manifest-codec.md) (#3).
- [Durable local release catalog](development/local-release-catalog.md) (#4).
- [Embedded deployment catalog and immutable local routing](deployment-routing.md) (#5).
- [Resource budgets, deadlines, and cancellation primitives](runtime/resource-budgets.md) (#6).
- [Bounded single-node admission and overload control](admission-control.md) (#7).
- [Fixed class pools and bounded tenant-fair scheduling](scheduling.md) (#8).

The remaining work is tracked by the
[Phase 1 epic](https://github.com/KirilsTurkins/latent-service-fabric/issues/1):

| Area | Remaining issues |
| --- | --- |
| Catalog and contract corrections | [Immutable metadata integrity #68](https://github.com/KirilsTurkins/latent-service-fabric/issues/68), [versioned deployment mutations/pages #67](https://github.com/KirilsTurkins/latent-service-fabric/issues/67), [SDK identity/cancellation parity #65](https://github.com/KirilsTurkins/latent-service-fabric/issues/65) |
| Invocation runtime | [Generic Wasmtime backend #9](https://github.com/KirilsTurkins/latent-service-fabric/issues/9), [context/log/clock #10](https://github.com/KirilsTurkins/latent-service-fabric/issues/10), [activation orchestration #11](https://github.com/KirilsTurkins/latent-service-fabric/issues/11) |
| Node services and operations | [Invocation/cancellation/status #12](https://github.com/KirilsTurkins/latent-service-fabric/issues/12), [telemetry/inventory #13](https://github.com/KirilsTurkins/latent-service-fabric/issues/13), [management adapters #37](https://github.com/KirilsTurkins/latent-service-fabric/issues/37), [standalone node #14](https://github.com/KirilsTurkins/latent-service-fabric/issues/14), [CLI #15](https://github.com/KirilsTurkins/latent-service-fabric/issues/15) |
| Completion evidence | [Conformance, isolation, reclamation, and zero-idle scaling gate #16](https://github.com/KirilsTurkins/latent-service-fabric/issues/16) |

Status is recorded as of September 7, 2026. An open implementation PR does not
make its feature available on the integration branch. Phase 0 remains the
runnable local echo demonstration; the complete standalone release-to-invocation
workflow and Phase 1 completion evidence are pending.

## Phase 2: packaging and supply chain

OCI push/pull, signatures, provenance, SBOM, trusted AOT cache, release rollout
orchestration, canary, and rollback. Atomic local deployment/snapshot publication
and deterministic weighted selection are already Phase 1 routing foundations.

## Phase 3: capabilities

Capability broker, policy grants, HTTP, blob, secrets, events, provider pooling, auditing, and descendant budgets.

## Phase 4: state and effects

Transactional keyed state, optimistic concurrency, durable outbox, effect dispatcher, idempotency, and entity-key routing.

## Phase 5: cluster

Separate control plane, route watches, direct node invocation, mTLS identity, artifact prefetch, state affinity, and multi-zone placement.

## Phase 6: durable workflows

Explicit workflow state machines, timers, continuations, awaited effects, replay, and compensation.

## Phase 7: research promotion candidates

User-space state paging, continuation eviction, call-graph fusion, immutable shared blobs, adaptive materialization, native software fault isolation, and hardware capability backends.
