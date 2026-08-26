# Engineering roadmap

## Phase 0: executable spike — complete

**Gate:** issue #25. **Evidence:** [`phase-0-completion.md`](phase-0-completion.md) and [`../benchmarks/phase0/`](../benchmarks/phase0/).

Completed feasibility work includes the pinned Component Model toolchain, one real Rust echo capsule, generated guest/host WIT bindings, one fixed generic cell pool, real Wasmtime component loading/invocation, activation-local trap/timeout/cancellation/memory containment, executable recovery tests, bounded queue saturation, cleanup/resource probes, and checked-in full-profile baselines.

Phase 0 completion is deliberately narrow. It does not claim production security, stable APIs, generic multi-service dispatch, deployment management, production scheduling/telemetry/SLOs, cluster operation, or the 100,000 dormant-service invariant. Phase 1 consumes the spike and must productionize/generalize it rather than repeat it.

## Phase 1: single-node stateless fabric

Standalone node, local release catalog, route table, scheduler/admission composition, activation envelopes, resource budgets, context/log/clock capabilities, generic invocation API, CLI flow, productionized build foundation, and telemetry. Phase 1 starts from the retained/hardened/generalized decisions in the Phase 0 completion report.

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
