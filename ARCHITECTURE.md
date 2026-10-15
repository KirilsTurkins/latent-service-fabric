# Architecture index

The authoritative architecture is divided by concern so that runtime implementation can evolve without erasing the foundational invariants.

The current product is a standalone Linux runtime with publication-aware package
admission, stateless capsule execution, bounded capability providers, six native
client SDKs, six guest authoring SDKs, shared HTTP ingress, static websites and
the supported Angular SSR profile. The [developer workflow](docs/start/application-development.md)
uses packaged compilers, explicit Linux/WSL/SSH workspaces and a separate native
Windows portable test subset. It manages development tools and nodes; it does
not allocate a persistent language process for each deployment.
Start with the [overview](docs/architecture/overview.md) for the
implemented components and the [node reference](docs/reference/standalone-node.md)
for configuration. Provider availability depends on the configured standalone
or trusted Rust embedding profile.

The [container profile](docs/operations/container-runtime.md) runs the same
standalone node as a non-root process. Optional node-level adapters provide
[private readiness probes](docs/operations/readiness-probes.md),
[TLS termination](docs/operations/local-https-edge.md) and
[bounded gzip delivery](docs/operations/static-compression.md).
[Private CI operations](docs/operations/headless-publication-ci.md) and
[route-set reconciliation](docs/operations/static-route-sets.md) retain explicit
operation identities and recovery. These helpers do not add an idle process per
capsule or establish support for unqualified cloud hosts and storage mounts.

Development adds explicitly configured protected state, host-owned transactions,
durable effect outboxes and original-result recovery. The
[state/effect architecture](docs/architecture/state-and-effects.md) and
[installed transaction runtime](docs/development/installed-transaction-rpc.md)
describe those owners and remaining acceptance gates. These profiles are outside
the published alpha.5 toolkit; clustering and durable workflows remain planned.
Maintainer acceptance and historical
measurements are collected in [engineering records](docs/development/engineering-records.md).

## Execution, delivery and authority

Start with the overview, then follow the owner of the behavior being changed.
These pages describe Development; the [release changes guide](docs/start/development-changes.md)
separates it from the published toolkit. Accepted ADRs record decisions, while
the linked implementation and qualification pages establish availability.

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
- [Security model](docs/architecture/security.md)
- [Versioning and deployment](docs/architecture/versioning-and-deployment.md)

## Transactional state and recovery

These opt-in profiles share one protected engine and fixed storage workers.
Commands, queries, result lookup, deferred dispatch and operator recovery have
separate current authority and physical ownership. Engine tests do not establish
the complete native, application or packaged acceptance gates.

- [State, transactions and durable effects](docs/architecture/state-and-effects.md)
- [Application schema and retained-format compatibility](docs/architecture/application-schema-compatibility.md)
- [Namespace history, schema and recovery epochs](docs/architecture/namespace-history-epochs.md)
- [Response retention and reserved recovery capacity](docs/architecture/transaction-retention.md)
- [Logical snapshot format and bounds](docs/architecture/logical-recovery-snapshot.md)
- [Paused recovery guard](docs/architecture/offline-recovery-guard.md)
- [Protected physical recovery and explicit resume](docs/architecture/protected-offline-recovery.md)
- [Reviewed older-history restore](docs/architecture/reviewed-older-history-restore.md)
- [Fixed aggregate migration](docs/architecture/fixed-aggregate-offline-migration.md)

For installed actions and the remaining native campaigns, use
[recovery qualification](docs/testing/installed-transaction-recovery.md).
Older-history restore preserves business incarnation and advances a separate
recovery epoch; it never renews historical grants. The retained v1 offline facade
and current protected v2 workflow have distinct formats and approval boundaries.

## Protocols, decisions and evidence

- [API surface](docs/api-surface.md)
- [Activation lifecycle](docs/protocol/activation-lifecycle.md)
- [Host-owned commit protocol](docs/protocol/commit-protocol.md)
- [Platform errors](docs/protocol/platform-errors.md)
- [Testing invariants](docs/testing/invariants.md)
- [Engineering records and roadmap](docs/development/engineering-records.md)
- [Architecture decision records](adr/README.md)
- [RFCs and draft research contracts](rfcs/README.md)
- [Research proposal review guide](docs/runtime/research-proposals.md)

## Planned cluster architecture

The standalone node supplies local authority fences, not replicated state,
remote invocation, distributed leases or durable workflow execution.

- [Cluster topology](docs/architecture/cluster-topology.md)
- [Distributed freshness implementation and conformance handoff](docs/architecture/cluster-freshness-handoff.md)
