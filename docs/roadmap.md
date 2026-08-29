# Engineering roadmap

## Phase 0: executable spike — completion gate blocked

Repository contracts, one Rust echo capsule, one fixed cell pool, Wasmtime
component loading, timeout/trap containment, baseline measurements, native
Linux calibration, hot-path profiling, and a long-running resource soak are
implemented. The recorded seven-process native-Linux calibration and
three-process resource soak are matched and pass with complete
descriptor-lifecycle evidence. See
[the completion gate](phase-0-completion.md).

That evidence does not by itself authorize Phase 0 or Phase 1. A clean-checkout
`make phase0-gate` run must produce an `authorized` receipt for the current
execution identity and fresh baseline. Until then, Phase 1 issue #2 remains
dependent on the gate; no roadmap item may treat issue closure or a single-host
observational result as authorization.

The dependency is an authorization and integration boundary, not a ban on
design, scaffolding, or isolated branch work for later phases. That work must
not claim that Phase 1 is authorized or ready to merge before the gate issues
its full receipt.

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
