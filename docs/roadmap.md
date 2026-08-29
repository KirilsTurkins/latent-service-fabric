# Engineering roadmap

## Phase 0: executable spike — completion gate authorized

Repository contracts, one Rust echo capsule, one fixed cell pool, Wasmtime
component loading, timeout/trap containment, baseline measurements, native
Linux calibration, hot-path profiling, and a long-running resource soak are
implemented. A separate clean native-Linux checkout completed `make phase0-gate`
with exit code 0; its [retained receipt](../benchmarks/phase0/receipts/native-linux-2026-08-29-54d02679/gate-summary.json)
is `authorized`, has `phase1_authorized: true`, and has no blockers. See
[the completion gate](phase-0-completion.md).

The underlying measurements remain single-host observational evidence. Neither
an issue closure nor such an observation alone authorizes Phase 1; the full
receipt did so only after validating the matched raw archives, identity,
profiling, and fresh-baseline checks. This authorization does not claim
production readiness or stable Phase 1 APIs.

## Phase 1: single-node stateless fabric

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
