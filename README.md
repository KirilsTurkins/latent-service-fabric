# Latent Service Fabric

Latent Service Fabric (LSF) is an interface-first research and engineering project for executing independently deployable service capsules without assigning persistent processes, sockets, threads, heaps, or connection pools to idle services.

A deployed service is represented by immutable code, contracts, policy, state metadata, and routing metadata. Resources are allocated only when an invocation becomes an activation. Activations execute in a fixed pool of reusable sandboxed cells.

> Most of this repository remains an architecture and API scaffold. Phase 0 additionally contains a narrow, explicitly non-production executable spike for one local echo capsule; it does not imply Phase 1 API compatibility or production readiness.

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
benchmarks/            Benchmark definitions for validating LSF claims
tools/                 Pinned validation, generation, and compile-smoke tooling
```

## Intended binaries

- `latentd`: data-plane node runtime. Its only current behavior is `phase0-spike invoke-once`, a finite local composition harness.
- `latent-control`: clustered control-plane application placeholder.
- `latent`: future build, package, deployment, inspection, invocation, and benchmark CLI placeholder.

The `latentd` spike has no management API, public invocation listener, persistent catalog, deployment surface, or production operations contract.

## First implementation milestone

The first vertical slice will:

1. load one signed or locally trusted capsule,
2. resolve one route,
3. admit one invocation,
4. lease one generic execution cell,
5. invoke one WIT export,
6. return one result,
7. drop all activation-owned state, and
8. prove that registering dormant services does not change process, thread, socket, or cell counts.

The Phase 0 spike currently proves the local component preparation, cell lease, contained echo invocation, cleanup, and machine-readable result portions of that slice. Routing, admission, trust, and standalone APIs remain later work.

See [`docs/architecture/overview.md`](docs/architecture/overview.md), [`docs/api-surface.md`](docs/api-surface.md), and [`docs/testing/invariants.md`](docs/testing/invariants.md).

## Build and validation

The Phase 0 build baseline pins Rust, Component Model, Protobuf, schema, and SDK tools. After installing the prerequisites documented in [`docs/development/toolchain.md`](docs/development/toolchain.md), validate a clean checkout with:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
make validate
```

Run the complete local Phase 0 executable demonstration with:

```bash
make phase0-spike-demo
```

The command validates contracts, builds the real guest and runtime, exercises success and containment failures only through the `latentd` executable path, and finishes with one successful echo result. See [`docs/phase-0-spike.md`](docs/phase-0-spike.md) for the CLI, JSON schema, exit codes, cleanup proof, and limitations.

Generated bindings, parsed WIT output, Protobuf descriptors, and SDK compiler artifacts are isolated under Cargo `OUT_DIR` or `target/contracts/`; handwritten contract sources are never overwritten. See [`VALIDATION.md`](VALIDATION.md) for the checks performed.

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
