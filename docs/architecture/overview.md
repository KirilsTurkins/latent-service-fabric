# LSF architecture overview

## Definition

Latent Service Fabric is a component-native execution fabric in which deployed services are dormant immutable artifacts. Requests become temporary activations. Activations execute inside a fixed pool of reusable sandboxed cells and release activation-owned execution resources when they finish. Durable suspension remains a later-phase model.

Phase 1 and its prioritized performance extension are complete. The current
product is a locally trusted standalone Linux stateless node. Phase 2 now also
provides immutable package formats, a deterministic packager and a
[bounded OCI library adapter](../reference/oci-registry.md). Publisher trust,
remote-package catalog and management integration, clustered control, guest
state, workflows and general trigger/provider implementations remain planned.

![Phase 1 delivery boundary: durable local catalogs and RPC feed bounded preparation, fixed cells and fresh Wasmtime activations; measured comparisons retain limits, while packaging, distributed control and state remain later phases.](../assets/phase1-delivery-boundary.svg)

## Resource invariant

```text
resident state = fixed node runtime + bounded catalog metadata + active activations + bounded global caches
```

A deployed but inactive service owns no process, operating-system thread, listener, guest heap, runtime instance, database connection pool, HTTP client pool, timer loop, or telemetry exporter.

Artifact storage, contract indexes, route indexes, policy metadata, and bounded cache entries are permitted to grow with registered service count. Execution allocation is not.

The standalone node also owns one fixed async cleanup supervisor with slots
bounded by its admitted activation capacity. After a transport disconnect, it
continues polling the same activation owner under its original deadline, keeping
quota and cell ownership through bounded cleanup. It adds no per-service worker
or per-disconnect task. Cell reuse still requires affirmative cleanup proof;
uncertain cleanup remains quarantined.

## Phase 0 evidence boundary

Phase 0 implements one deliberately narrow local composition. Its evidence
shows that the project can build a real Rust echo Component Model guest with
generated WIT bindings; load and invoke it through real Wasmtime Component
Model host bindings; lease a fixed generic cell; create fresh
activation-owned stores and host state; contain the tested failure paths; and
affirmatively reclaim measured activation resources.

The configured runtime workers, process count, listeners/sockets, and cell
capacity remain fixed through the measured lifecycle. Wasmtime may create one
bounded epoch-interruption helper thread after preparation; that is fixed
node/runtime infrastructure, not a per-service thread.

The retained August 30 native-Linux resource soak has a matched calibration
identity and complete descriptor-lifecycle evidence. The full gate
independently regenerated it with the matching profile and calibration,
validated a fresh baseline, and authorized Phase 1 for the common canonical
execution identity. The measurements remain observational and single-host;
authorization does not imply production readiness or Phase 1 API
compatibility. Their boundaries and the handoff are recorded in
[`../phase-0-completion.md`](../phase-0-completion.md).

![Activation resource lifecycle: prepared components and fixed cells are bounded node-owned resources; every invocation creates fresh activation state and ends by releasing or quarantining its cell.](../assets/phase0-resource-lifecycle.svg)

Phase 0 did not prove dormant registration at 100,000 services, route or
admission behavior, persistent management/deployment, production
trust/security, generic dispatch, durable state/effects, remote transport,
cluster behavior, or production telemetry/SLOs.

## Service model

The current [standalone Linux node](../reference/standalone-node.md) composes
durable release and deployment catalogs, immutable routing, admission, fair
scheduling, [generic Wasmtime execution](../runtime/wasmtime.md), activation
capabilities and lifecycle management, telemetry, and invocation and management
RPCs. The [operator CLI](../reference/operator-cli.md) drives the local
release-to-invocation workflow through generated clients. The
[Phase 1 completion review](../phase-1-completion.md) records the delivered
stateless surface, acceptance evidence and completion decision.
[Bounded conformance](../testing/phase-1-conformance.md) covers selected scenarios.
The [full measurements](../../benchmarks/phase1/measurements/2026-09-08-container-linux-d72c99b6/REPORT.md)
show fixed node topology through 100,000 releases/deployments and bounded
reclamation across three mixed soaks; catalog metadata RSS grows and is reported
separately. The [controlled comparison](../../benchmarks/phase1/paired/2026-09-08-container-linux-e7e06f7/REPORT.md)
records actual productionization overhead and its measurement boundaries.

The [completed extension](../phase-1-extension-completion.md) records warm/cold
preparation, budget, cache, ownership, codec, catalog and scheduler changes, plus
actual Docker and Kubernetes comparisons. Native handlers retain lower warm
latency in those infrastructure campaigns; LSF reduces memory and startup cost
for their dense cohorts. Results include mixed regressions and do not establish
a universal millisecond SLO or production cluster capacity.

```text
Service = stable logical name
Release = immutable capsule digest
Revision = release + deployment configuration
Route = rule selecting a revision
Activation = revision × function × input × identity × budget × deadline
Phase 1 result = output or typed failure + accounting
Later transactional result = output + state commit + effect intents + accounting
```

There is intentionally no `Service = PID + port + heap + threads` relationship.

## Planes

### Developer plane

Builds WIT contracts and language components, creates capsules, produces SBOM/provenance, signs artifacts, and publishes them as OCI artifacts.

### Control plane

Stores desired state, validates releases, compiles bindings and routes, evaluates policy, records node inventories, and distributes immutable route snapshots. It does not participate in ordinary invocation routing after a snapshot reaches a node.

### Data plane

Receives triggers and direct calls, resolves exact revisions from a local snapshot, performs admission, schedules activations, materializes code, binds capabilities, executes guest code, commits state, persists effect intents, and returns results.

These plane descriptions include later-phase capabilities. Phase 1 implements
the local stateless routing and execution path, management RPCs, and CLI. Phase 2
adds bounded library packaging and OCI transfers; publisher verification and
their catalog/management integration remain planned. Clustered control, durable
state/effects and general trigger adapters are later work. Phase 0 implements
only the local component preparation, execution, containment and reclamation slice.

## Physical topology

```text
Developer tooling ──► OCI registry
                         │
Management client ──► latent-control ──► PostgreSQL
                         │ route snapshots
                         ▼
Ingress ─────────────► latentd nodes ◄────► latentd nodes
                         │
                         ├── state backend
                         ├── effect providers
                         └── telemetry collector
```

The diagram shows the intended clustered topology. Current standalone mode
embeds local desired-state catalogs and the supported management services in
one Linux `latentd` process, using durable local storage. A separate clustered
control plane and PostgreSQL storage remain later work. The delivered OCI adapter
is a separate library boundary; it does not yet connect remote packages to the
node's catalog or management services. Neither topology was a Phase 0 product surface.

## Fixed process model

A production node may have a fixed set of execution-host processes partitioned by trust class or workload class:

```text
latentd supervisor
├── trusted execution host
├── ordinary tenant execution host A
├── ordinary tenant execution host B
├── restricted/high-value execution host
└── optional native compatibility host
```

The count is configured by node policy, not by deployed service count. Phase 0 and the delivered Phase 1 standalone node each use one process and fixed in-process cells; stronger trust-class process isolation remains later work.

## Technology direction

- WebAssembly Component Model for portable polyglot capsule boundaries.
- WIT for capsule exports, imports, and host capabilities.
- Wasmtime as the initial execution engine behind `ExecutionBackend`.
- OCI artifacts for content-addressed distribution.
- Protobuf for control-plane and generic management RPCs.
- A transport abstraction suitable for WIT-native remote invocation.
- Explicit state transactions and durable effect intents.

These are recorded in ADRs and remain replaceable behind the Rust trait boundaries where explicitly stated. Phase 1 applies the retain/harden/generalize/rewrite/delete handoff in [`../phase-0-completion.md`](../phase-0-completion.md); the [completion review](../phase-1-completion.md) identifies the retained isolated regression paths and current product surface.
