# Testing and Benchmarks

> **Document role:** Verification map. Test specifications and benchmark definitions in the repository are authoritative.

## Why tests are central

LSF's primary architectural claim is measurable. Interface compilation cannot prove that dormant services consume no execution resources or that reused cells do not leak state.

The implementation must make resource, isolation, compatibility, and failure semantics observable and testable.

## Invariant suites

### Dormant-service scaling

Register 100, 1,000, 10,000, and 100,000 dormant releases. Process count, OS-thread count, socket count, and execution-cell count must remain constant. Metadata, route indexes, and disk storage may grow.

### Reclamation

After repeated calls, resident memory should return near the fixed-runtime plus bounded-cache baseline. File descriptors, handles, timers, provider leases, and temporary blobs must remain bounded.

### Isolation

Tests must establish that:

- a guest trap cannot corrupt another activation;
- one activation cannot access another handle table or memory;
- tenant state cannot cross namespaces;
- cell reuse cannot reveal previous input, output, or secrets;
- malformed payloads fail before unsafe host work;
- AOT artifacts with incompatible engine keys are rejected.

### Route pinning

In-flight activations finish on their pinned release after a route switch. New calls use only revisions in the new snapshot.

### Budget hierarchy

Child work cannot exceed the parent's remaining deadline, CPU, fan-out, outbound-call, state, blob, log, or effect budgets.

### Failure ambiguity

Tests cover response loss after state commit or provider dispatch. Automatic retries are allowed only when operation semantics and idempotency make them safe.

### Local and remote equivalence

Domain output, platform errors, identity, deadlines, budgets, tracing, state semantics, and accounting must match across inline, isolated-local, and remote binding modes.

## Repository test categories

| Category | Purpose |
|---|---|
| `conformance` | Backend and provider behavior against stable platform contracts |
| `compatibility` | Contract and version-evolution rules |
| `security` | Authorization, isolation, trust, and malformed-input controls |
| `integration` | Multi-subsystem behavior |
| `chaos` | Fault injection and recovery behavior |
| `leak` | Memory, handle, descriptor, secret, and cell-reuse leakage |

## Benchmark tracks

| Benchmark | Question |
|---|---|
| Idle scaling | Does registered service count change resident execution resources? |
| Activation latency | What are cold, cached, and prepared activation costs? |
| Local call | What does an inline or isolated-node call cost? |
| Remote call | What does transport and node placement add? |
| Memory reclamation | Are activation-owned pages and buffers returned? |
| State throughput | What are transaction and conflict costs? |
| Fusion | When does derived composition help, and does it preserve semantics? |

## Current baseline versus future runtime proof

`make validate` currently proves deterministic interface compilation and repository consistency. It does not yet prove:

- runtime isolation;
- execution latency;
- memory reclamation;
- local/remote semantic equivalence;
- zero idle allocation under service registration;
- state/effect recovery behavior.

Those proofs begin with the Phase 0 vertical slice and expand with each roadmap phase.

## Evidence expected in implementation pull requests

A relevant PR should state:

- the invariant being implemented;
- the measurement or test oracle;
- expected bounds;
- failure cases;
- resource-accounting impact;
- compatibility and security impact;
- reproducible test or benchmark commands.

## Canonical sources

- [Test invariants](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/testing/invariants.md)
- [Test specifications](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/tests)
- [Benchmark definitions](https://github.com/KirilsTurkins/latent-service-fabric/tree/release/benchmarks)
- [Validation baseline](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/VALIDATION.md)
- [Roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/roadmap.md)
