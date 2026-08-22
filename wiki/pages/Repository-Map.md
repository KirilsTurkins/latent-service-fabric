# Repository Map

> **Document role:** Navigation aid. Directory contents and root documentation are authoritative.

## Top-level layout

| Path | Purpose |
|---|---|
| `apps/` | Placeholder binary entry points for `latentd`, `latent-control`, and `latent` |
| `crates/` | Rust architectural interfaces and data models |
| `wit/` | WIT packages for platform and service contracts |
| `api/proto/` | Protobuf control-plane, node, trigger, route, audit, and invocation APIs |
| `schemas/` | JSON Schemas for declarative resources |
| `sdk/` | Cross-language interface-only client and guest surfaces |
| `examples/` | Contract and deployment examples |
| `adr/` | Accepted architecture decisions |
| `rfcs/` | Future design proposals |
| `research/` | Experimental tracks outside the production core |
| `docs/` | Architecture, protocol, development, operations, security, and testing documentation |
| `tests/` | Conformance, compatibility, security, integration, chaos, and leak specifications |
| `benchmarks/` | Idle scaling, activation, calls, reclamation, state, and research benchmark definitions |
| `tools/` | Pinned validation, generation, and compile-smoke tooling |

## Intended applications

### `latentd`

Data-plane node runtime. Standalone mode is expected to embed control-plane modules.

### `latent-control`

Clustered control-plane application.

### `latent`

Build, package, deployment, inspection, invocation, and benchmark CLI.

The current binaries are zero-behavior placeholders. Their presence documents intended workspace shape rather than completed runtime functionality.

## Architecture navigation

Use [ARCHITECTURE.md](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/ARCHITECTURE.md) as the canonical index. Major groups include:

- overview, control plane, and data plane;
- execution cells;
- contracts and bindings;
- ingress and triggers;
- identity and capabilities;
- blob, state, and effect models;
- cluster topology and security;
- versioning and deployment;
- activation, commit, and platform error protocols;
- testing invariants and roadmap.

## Contract navigation

Use the [API surface map](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/api-surface.md) to find:

- guest-facing WIT packages;
- Protobuf services;
- declarative schemas;
- Rust subsystem seams;
- language SDK surfaces.

## Tests and benchmarks

The `tests/` tree groups behavior specifications by conformance, compatibility, security, integration, chaos, and leak concerns.

The `benchmarks/` tree groups idle scaling, activation latency, local and remote calls, memory reclamation, state throughput, and fusion studies.

## Generated outputs

Handwritten contracts remain authoritative. Generated WIT bindings, descriptor sets, SDK compiler artifacts, and smoke outputs belong under Cargo `OUT_DIR` or `target/contracts/`, according to the toolchain and validation policies.

## Canonical entry points

- [README](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/README.md)
- [Architecture index](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/ARCHITECTURE.md)
- [API surface](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/api-surface.md)
- [Validation baseline](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/VALIDATION.md)
- [Contributing](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/CONTRIBUTING.md)
