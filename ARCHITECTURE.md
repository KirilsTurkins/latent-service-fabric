# Architecture index

The authoritative architecture is divided by concern so that runtime implementation can evolve without erasing the foundational invariants.

Phase 1 and its prioritized performance extension are complete. The delivered
product is the [standalone Linux stateless node](docs/reference/standalone-node.md),
with the scope and evidence recorded in the [functional completion](docs/phase-1-completion.md)
and [extension report](docs/phase-1-extension-completion.md). The pages below also
define later-phase design contracts; their implementation boundaries distinguish
those plans from available features. Phase 2 begins with packaging and supply chain.

- [Overview](docs/architecture/overview.md)
- [Control plane](docs/architecture/control-plane.md)
- [Data plane](docs/architecture/data-plane.md)
- [Execution cells](docs/architecture/execution-cells.md)
- [Contracts and bindings](docs/architecture/contracts-and-bindings.md)
- [Ingress and triggers](docs/architecture/ingress-and-triggers.md)
- [Identity and capabilities](docs/architecture/identity-and-capabilities.md)
- [Blob model](docs/architecture/blob-model.md)
- [State and effects](docs/architecture/state-and-effects.md)
- [Cluster topology](docs/architecture/cluster-topology.md)
- [Security model](docs/architecture/security.md)
- [Versioning and deployment](docs/architecture/versioning-and-deployment.md)
- [API surface](docs/api-surface.md)
- [Activation lifecycle](docs/protocol/activation-lifecycle.md)
- [Commit protocol](docs/protocol/commit-protocol.md)
- [Platform errors](docs/protocol/platform-errors.md)
- [Testing invariants](docs/testing/invariants.md)
- [Roadmap](docs/roadmap.md)
- [Architecture decision records](adr/README.md)
