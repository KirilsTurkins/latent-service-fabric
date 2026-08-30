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

## Phase 1: single-node stateless fabric — authorized to begin

Standalone node, local release catalog, route table, scheduler, activation envelopes, resource budgets, context/log/clock capabilities, generic invocation API, CLI flow, and telemetry.

## Phase 2: packaging and supply chain

OCI push/pull, signatures, provenance, SBOM, trusted AOT cache, atomic routing, canary, and rollback.

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
