# Design Governance

> **Document role:** Explanation of how LSF decisions are recorded. ADR and RFC files in the main repository are authoritative.

## ADRs

Architecture Decision Records constrain implementations and compatibility. An accepted ADR may be superseded only by another ADR.

Use an ADR when a change affects:

- a core invariant;
- the execution or isolation model;
- dependency direction;
- a compatibility promise;
- contract authority;
- state or external-effect guarantees;
- control-plane/data-plane responsibilities;
- promotion of research into the production core.

## Current foundational decisions

The repository currently records 18 foundational ADRs:

1. use Rust for the runtime;
2. use the WebAssembly Component Model;
3. use WIT as capsule contract authority;
4. use Wasmtime as the first execution engine;
5. forbid per-service idle execution allocation;
6. use reusable generic execution cells;
7. distribute capsules as OCI artifacts;
8. compile AOT artifacts only in a trusted boundary;
9. use capability-based host access;
10. separate immutable capsule metadata from deployment policy;
11. keep the control plane out of the invocation hot path;
12. place remote invocation behind a WIT-native transport abstraction;
13. use explicit state transactions and effect intents;
14. do not promise universal exactly-once external effects;
15. build a single-node stateless fabric before clustering;
16. keep paging, continuation eviction, and fusion optional;
17. use fixed trust-class execution hosts for stronger containment;
18. treat Latent Service Fabric as a working name.

Read the actual ADR before relying on this summary.

## RFCs

RFCs are proposals for changes that need review before contracts or architectural commitments are changed. They may explore alternatives, migration, open questions, and implementation staging.

An RFC is not an accepted guarantee until the repository's decision process says so.

## Research boundary

Experimental paging, continuation eviction, call-graph fusion, native software fault isolation, hardware capability backends, and similar work belongs under `research/` until promoted.

A successful experiment does not automatically become a production requirement. Promotion should explain:

- the problem solved;
- measured benefit;
- semantic and security preservation;
- failure behavior;
- portability;
- operational cost;
- fallback behavior;
- effect on the fixed-resource invariant.

## Decision review checklist

A proposed decision should make explicit:

1. context and problem;
2. accepted decision;
3. alternatives considered;
4. consequences and tradeoffs;
5. compatibility and migration;
6. security implications;
7. resource-accounting implications;
8. test and benchmark obligations;
9. which documents and contracts change.

## Canonical sources

- [ADR directory](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/adr)
- [ADR index](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/adr/README.md)
- [RFC directory](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/rfcs)
- [CONTRIBUTING.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/CONTRIBUTING.md)
- [Research directory](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/research)
