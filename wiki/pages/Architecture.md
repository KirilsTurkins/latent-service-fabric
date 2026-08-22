# Architecture

> **Document role:** Guided architecture map. The detailed architecture files and accepted ADRs are authoritative.

## System decomposition

![Animated LSF system decomposition](https://github.com/KirilsTurkins/latent-service-fabric/blob/docs/wiki/wiki/pages/assets/system-decomposition.gif?raw=1)

*Animated render generated from the [animated SVG source](https://github.com/KirilsTurkins/latent-service-fabric/blob/docs/wiki/wiki/pages/assets/system-decomposition.svg?raw=1) by the [Wiki diagram generator](https://github.com/KirilsTurkins/latent-service-fabric/blob/docs/wiki/wiki/visuals/generate_diagrams.py).*

## Control plane

The control plane manages desired state and compiled metadata. It does not execute capsule code and is excluded from the ordinary invocation hot path.

Principal modules:

- **Release catalog:** immutable digests, OCI references, signatures, provenance, SBOMs, WIT digests, trust status, and compatibility metadata.
- **Contract registry:** WIT packages, interfaces, worlds, functions, type graphs, dependencies, compatibility reports, and binding plans.
- **Deployment reconciler:** release plus grants, limits, placement, cache targets, and route weights.
- **Binding compiler:** connects imports to host capabilities or provider services and records permitted physical modes.
- **Policy engine:** evaluates publisher trust, capability grants, quotas, placement, egress, state, secrets, fusion, and native fallback.
- **Route compiler:** produces immutable route snapshots with a monotonic generation and content digest.
- **Node inventory:** tracks identity, architecture, CPU features, trust classes, capacity, pressure, locality, topology, and route lag.
- **Audit subsystem:** records administrative changes and security-sensitive decisions.

Nodes should continue invoking routes from a valid local snapshot during a temporary control-plane outage.

## Data plane

The ordinary invocation path is:

```text
shared ingress
  → local route resolution
  → admission
  → fair scheduling
  → artifact/AOT materialization
  → capability binding
  → execution cell
  → state/effect commit
  → result and telemetry
```

Admission occurs before a cell is allocated. Scheduling uses bounded queues, fairness, priority, deadlines, locality, state affinity, and trust-class constraints. Overload must not create service-specific processes or threads.

## Shared ingress and triggers

HTTP, direct RPC, event, queue, timer, and blob triggers terminate in shared adapters. Capsules do not own listeners or consumer loops. Shared ingress creates the activation envelope and delegates exact revision selection to the local route snapshot.

## Fixed physical topology

A node may use a configured set of execution-host processes partitioned by trust or workload class:

```text
latentd supervisor
├── trusted execution host
├── ordinary tenant execution host A
├── ordinary tenant execution host B
├── restricted/high-value execution host
└── optional native compatibility host
```

The count is node policy, not service count.

## Standalone and clustered forms

### Development or standalone

One `latentd` process may embed control modules, a local route snapshot, local artifact and state stores, and a fixed cell pool.

### Initial production

A small clustered control plane manages desired state and snapshots. Shared ingress targets multiple `latentd` nodes connected to state backends, effect providers, artifact storage, and telemetry.

## Technology direction

- WebAssembly Component Model for portable capsule boundaries;
- WIT for guest exports, imports, and capabilities;
- Wasmtime as the first execution engine behind an abstraction;
- OCI artifacts for content-addressed distribution;
- Protobuf for management and generic invocation;
- explicit state transactions and durable effect intents;
- a transport abstraction preserving WIT-level semantics across local and remote bindings.

## Canonical architecture sources

- [Architecture overview](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/overview.md)
- [Control plane](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/control-plane.md)
- [Data plane](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/data-plane.md)
- [Execution cells](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/execution-cells.md)
- [Cluster topology](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/cluster-topology.md)
- [Ingress and triggers](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/ingress-and-triggers.md)
- [Operational topology](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/operations/topology.md)

Continue with [[Activation-Lifecycle|Activation lifecycle]] and [[Deployment-and-Routing|Deployment and routing]].
