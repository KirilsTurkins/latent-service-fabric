# Engineering roadmap

## Phase 0: executable spike

Repository contracts, one Rust echo capsule, one fixed cell pool, Wasmtime component loading, timeout/trap containment, and baseline measurements.

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
