<!-- LSF-WIKI-MANAGED -->
<!-- LSF-PHASE0-GATE: blocked -->
# Latent Service Fabric

Latent Service Fabric (LSF) is an interface-first systems project for running
independently deployable service capsules without reserving a process, thread,
socket, heap, or connection pool for every idle service.

> **Current status:** Phase 0 has a working local executable spike. Its
> completion gate is still pending an **authorized** clean-checkout receipt.
> Phase 1 is not authorized merely because an issue is closed, a benchmark
> aggregate passes, or a smoke check succeeds.

The Wiki explains the project. The [`development` branch](https://github.com/KirilsTurkins/latent-service-fabric/tree/development)
is authoritative for code, contracts, evidence, and delivery status.

## The core resource rule

```text
resident resources = fixed node runtime + active activations + bounded shared caches
```

A deployment can have immutable code, metadata, policy, and routing identity
while dormant. Execution resources are allocated only when an invocation
becomes an activation.

## What Phase 0 actually implements

- A Rust echo guest built as a real WebAssembly Component through generated WIT bindings.
- A local `latentd phase0-spike` composition using real Wasmtime Component Model host bindings.
- A fixed-capacity generic cell pool with affine leases and a bounded FIFO queue.
- Fresh invocation-owned Wasmtime stores, host state, limits, cancellation, and bounded logs.
- Containment and recovery exercises for success, declared domain error, trap,
  deadline, cancellation, and memory pressure.
- Machine-readable baseline, calibration, profiling, and resource-soak evidence
  that the completion gate independently validates from raw artifacts.

## What it does not implement or prove

Phase 0 is not a production node or public API. It has no management listener,
route table, deployment catalog, persistent state/effect implementation,
generic multi-service dispatch, network transport, cluster operation,
production security posture, production SLO, or dormant-service-density proof.

![Phase 0 activation flow](assets/phase0-activation-flow.svg)

## Start here

- [Phase 0 status](Phase-0-Status) — current evidence boundary and the only
  route to Phase 1 authorization.
- [Getting started](Getting-Started) — validate the repository and run the
  local spike.
- [Architecture](Architecture) — distinguish the implemented spike from the
  target fabric.
- [Activation lifecycle](Activation-Lifecycle) and [Execution cells](Execution-Cells)
  — ownership, containment, and reclamation rules.
- [Contracts and APIs](Contracts-and-APIs) — WIT, Protobuf, schemas, Rust
  seams, and SDK roles.
- [Testing and benchmarks](Testing-and-Benchmarks) — verification commands and
  the native-Linux evidence boundary.
- [Roadmap](Roadmap) — Phase 0 through research promotion candidates.

## Canonical sources

| Topic | Repository authority |
|---|---|
| Project definition and current boundary | [README](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/README.md) |
| Phase 0 receipt and evidence ledger | [docs/phase-0-completion.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-0-completion.md) |
| Architecture | [ARCHITECTURE.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/ARCHITECTURE.md) and [docs/architecture](https://github.com/KirilsTurkins/latent-service-fabric/tree/development/docs/architecture) |
| Validation | [VALIDATION.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/VALIDATION.md) |
| Engineering phases | [docs/roadmap.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/roadmap.md) |
| Open work | [GitHub issues](https://github.com/KirilsTurkins/latent-service-fabric/issues) |

The key distinction is simple: repository source defines LSF, this Wiki makes
it easier to navigate, and an authorized receipt—not narrative—establishes the
Phase 0 handoff.
