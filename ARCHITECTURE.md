# Architecture index

The authoritative architecture is divided by concern so that runtime implementation can evolve without erasing the foundational invariants.

The current product is a standalone Linux runtime with publication-aware package
admission, stateless capsule execution, bounded capability providers, six native
client SDKs, shared HTTP ingress, static websites and the supported Angular SSR
profile. Start with the [overview](docs/architecture/overview.md) for the
implemented components and the [node reference](docs/reference/standalone-node.md)
for configuration. Provider availability depends on the configured standalone
or trusted Rust embedding profile.

State transactions, durable effect outboxes, clustering and durable workflows
are planned designs. Their architecture pages state that boundary explicitly;
they are not installation instructions. Maintainer acceptance and historical
measurements are collected in [engineering records](docs/development/engineering-records.md).

- [Overview](docs/architecture/overview.md)
- [Control plane](docs/architecture/control-plane.md)
- [Data plane](docs/architecture/data-plane.md)
- [Execution cells](docs/architecture/execution-cells.md)
- [Contracts and bindings](docs/architecture/contracts-and-bindings.md)
- [Ingress and triggers](docs/architecture/ingress-and-triggers.md)
- [Static website delivery](docs/component-development/static-sites.md)
- [Angular server rendering](docs/component-development/angular-build.md)
- [Identity and capabilities](docs/architecture/identity-and-capabilities.md)
- [Blob model](docs/architecture/blob-model.md)
- [State and effects: implemented operations and planned transactions](docs/architecture/state-and-effects.md)
- [Planned cluster topology](docs/architecture/cluster-topology.md)
- [Security model](docs/architecture/security.md)
- [Versioning and deployment](docs/architecture/versioning-and-deployment.md)
- [API surface](docs/api-surface.md)
- [Activation lifecycle](docs/protocol/activation-lifecycle.md)
- [Planned commit protocol](docs/protocol/commit-protocol.md)
- [Platform errors](docs/protocol/platform-errors.md)
- [Testing invariants](docs/testing/invariants.md)
- [Engineering records and roadmap](docs/development/engineering-records.md)
- [Architecture decision records](adr/README.md)
