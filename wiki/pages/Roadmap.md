# Roadmap

> **Document role:** Reader-friendly phase map. Issues, milestones, accepted ADRs, and `docs/roadmap.md` determine actual implementation scope and ordering.

## Phase 0 — Executable spike

Target:

- repository contracts;
- one Rust echo capsule;
- one fixed cell pool;
- Wasmtime component loading;
- timeout and trap containment;
- baseline measurements.

Success must include an end-to-end activation and the first proof that dormant registrations do not allocate service-specific execution resources.

## Phase 1 — Single-node stateless fabric

Target:

- standalone node;
- local release catalog and route table;
- admission and scheduling;
- activation envelopes and budgets;
- context, log, clock, and related baseline capabilities;
- generic invocation API;
- CLI flow;
- telemetry.

This phase establishes the core execution path before clustering.

## Phase 2 — Packaging and supply chain

Target:

- OCI push and pull;
- signatures;
- provenance and SBOM;
- trusted AOT cache;
- atomic routing;
- canary rollout and rollback.

## Phase 3 — Capabilities

Target:

- capability broker and policy grants;
- outbound HTTP;
- blobs;
- secrets;
- events;
- bounded provider pooling;
- auditing;
- descendant budgets.

## Phase 4 — State and effects

Target:

- transactional keyed state;
- optimistic concurrency;
- durable outbox;
- effect dispatcher;
- idempotency;
- entity-key routing.

## Phase 5 — Cluster

Target:

- separated control plane;
- route watches;
- direct node invocation;
- mTLS workload identity;
- artifact prefetch;
- state affinity;
- multi-zone placement.

## Phase 6 — Durable workflows

Target:

- explicit workflow state machines;
- durable timers;
- persisted continuations;
- awaited effects;
- replay;
- compensation.

## Phase 7 — Research promotion candidates

Candidates include:

- user-space state paging;
- continuation eviction;
- call-graph fusion;
- immutable shared blobs;
- adaptive materialization;
- native software fault isolation;
- hardware capability backends.

Promotion requires evidence and an accepted decision; these tracks are not baseline dependencies.

## Cross-phase gates

Each phase should preserve:

- fixed resource counts with dormant-service growth;
- bounded queues, caches, pools, and handles;
- explicit capability authorization;
- pinned route and policy identity;
- domain/platform error separation;
- state/effect ambiguity handling;
- local/remote semantic equivalence;
- reproducible validation and measurable evidence.

## Status interpretation

The repository's current compile-smoke and validation baseline is part of Phase 0 preparation. It must not be described as a completed production runtime.

## Canonical sources

- [Engineering roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/roadmap.md)
- [Repository issues](https://github.com/KirilsTurkins/latent-service-fabric/issues)
- [Accepted ADRs](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/adr)
- [Research tracks](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/research)
