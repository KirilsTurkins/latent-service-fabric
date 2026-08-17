# Latent Service Fabric

Latent Service Fabric (LSF) is an interface-first research and engineering project for executing independently deployable service capsules without assigning persistent processes, sockets, threads, heaps, or connection pools to idle services.

A deployed service is represented by immutable code, contracts, policy, state metadata, and routing metadata. Resources are allocated only when an invocation becomes an activation. Activations execute in a fixed pool of reusable sandboxed cells.

> This repository is an architecture and API scaffold. It intentionally contains no runtime, storage, networking, compiler, scheduler, or provider implementation yet.

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
apps/                 Binary entry-point placeholders
crates/               Rust architectural interfaces and data models
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
```

## Intended binaries

- `latentd`: data-plane node runtime; standalone mode will embed control-plane modules.
- `latent-control`: clustered control-plane application.
- `latent`: build, package, deployment, inspection, invocation, and benchmark CLI.

The current binaries are zero-behavior placeholders so that the intended workspace shape is explicit without implying an implementation.

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

See [`docs/architecture/overview.md`](docs/architecture/overview.md), [`docs/api-surface.md`](docs/api-surface.md), and [`docs/testing/invariants.md`](docs/testing/invariants.md).

## Build status

The Rust workspace is designed to compile using only the Rust standard library. CI is configured to run formatting, compilation, Clippy, and repository consistency checks. The checks completed in the generation environment and the unavailable toolchains are recorded in [`VALIDATION.md`](VALIDATION.md).

## License

Apache License 2.0. See [`LICENSE`](LICENSE).
