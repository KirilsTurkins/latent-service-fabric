# Latent Service Fabric

Latent Service Fabric (LSF) is an interface-first research and engineering project for executing independently deployable service capsules without assigning persistent processes, sockets, threads, heaps, or connection pools to idle services.

A deployed service is represented by immutable code, contracts, policy, state metadata, and routing metadata. Resources are allocated only when an invocation becomes an activation. Activations execute in a fixed pool of reusable sandboxed cells.

> Phase 0 is complete as a narrow feasibility gate. The repository contains a real local echo-component spike and measured containment/resource evidence, but most product surfaces remain architecture/API scaffold. Phase 0 is not Phase 1 API compatibility or production readiness.

## Core invariant

```text
resident resources = fixed node runtime + active activations + bounded shared caches
```

The number of operating-system processes, threads, sockets, and execution cells is node-defined and must not scale with the number of deployed services.

## Authoritative interface layers

- **WIT** defines capsule exports, platform capabilities, and component-to-component contracts.
- **Protobuf** defines control-plane, node-management, trigger-management, and generic invocation APIs.
- **JSON Schema** defines declarative capsule, deployment, binding, policy, trigger, and route documents.
- **Rust traits** define the internal architectural seams between runtime subsystems.
- **Language SDK surfaces** expose implementation-neutral client and guest contracts.

## Repository map

```text
apps/                 Binary entry points and the explicit latentd Phase 0 spike mode
crates/               Rust architectural interfaces, data models, and Phase 0 runtime pieces
wit/                  WIT packages for platform capabilities
api/proto/            Protobuf service definitions
schemas/              JSON Schemas for declarative resources
sdk/                  Cross-language interface-only SDK surfaces
examples/             Contract and deployment examples
adr/                   Accepted architecture decisions
rfcs/                  Future design proposals
research/              Experimental tracks kept outside the production core
docs/                  Architecture, protocol, operations, and security documentation
tests/                 Conformance, isolation, chaos, and leak-test specifications
benchmarks/            Benchmark definitions and checked-in Phase 0 evidence
tools/                 Pinned validation, generation, spike, benchmark, and gate tooling
```

## Intended binaries

- `latentd`: data-plane node runtime. Its only current executable behavior is the finite local `phase0-spike` harness used by the Phase 0 proof.
- `latent-control`: clustered control-plane application placeholder.
- `latent`: future build, package, deployment, inspection, invocation, and benchmark CLI placeholder.

The `latentd` spike has no management API, public invocation listener, persistent catalog, deployment surface, generic multi-service dispatch, or production operations contract.

## Phase 0 result

Phase 0 proved one real Rust echo component can be built with generated WIT bindings, loaded and invoked through Wasmtime Component Model bindings, run through a fixed generic cell pool, and reclaimed after success, declared domain error, trap, timeout, cancellation, memory pressure, and bounded queue saturation. The checked-in full baseline also records fixed configured workers/process/socket/cell topology and bounded resource growth for the measured run.

It did **not** prove routing, admission, deployment management, production trust/security, durable state/effects, remote invocation, cluster operation, production SLOs, or the 100,000 dormant-service invariant.

See [`docs/phase-0-completion.md`](docs/phase-0-completion.md) for the gate decision and Phase 1 handoff, [`docs/architecture/overview.md`](docs/architecture/overview.md) for the architecture boundary, and [`docs/testing/invariants.md`](docs/testing/invariants.md) for proven versus future invariants.

## Build and validation

The Phase 0 build baseline pins Rust, Component Model, Protobuf, schema, and SDK tools. After installing the prerequisites in [`docs/development/toolchain.md`](docs/development/toolchain.md), run the general repository validation with:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

Run the complete Phase 0 completion gate with:

```bash
make phase0-gate
```

That single command performs workspace Rust checks, contract/component validation, the real executable spike E2E and containment/recovery suite, then the full resource/baseline profile. Evidence is written under `target/phase0-gate/full/`; the checked-in reference evidence remains under [`benchmarks/phase0/`](benchmarks/phase0/). PR CI runs the same gate with smaller benchmark sample counts via `make phase0-gate-smoke`.

For only the executable demonstration, use:

```bash
make phase0-spike-demo
```

Generated bindings, parsed WIT output, Protobuf descriptors, capsule artifacts, and gate output are isolated under Cargo `OUT_DIR` or `target/`; handwritten contract sources are never overwritten. See [`VALIDATION.md`](VALIDATION.md) for the exact validation layers.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
