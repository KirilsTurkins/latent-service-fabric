# LSF architecture overview

## Definition

Latent Service Fabric is a component-native execution fabric in which deployed services are dormant immutable artifacts. Requests become temporary activations. Activations execute inside a fixed pool of reusable sandboxed cells and release all activation-owned resources when they finish or suspend durably.

## Resource invariant

```text
resident resources = fixed node runtime + active activations + bounded global caches
```

A deployed but inactive service owns no process, operating-system thread, listener, heap, runtime instance, database connection pool, HTTP client pool, timer loop, or telemetry exporter.

Artifact storage, contract indexes, route indexes, policy metadata, and bounded cache entries are permitted to grow with registered service count. Execution allocation is not.

## Phase 0 evidence boundary

Phase 0 closed its feasibility gate with one deliberately narrow local composition. The checked-in evidence proves that composition can:

- build one real Rust echo Component Model guest with generated WIT bindings;
- load/invoke it through real Wasmtime Component Model host bindings;
- lease from a fixed generic cell pool and create a fresh activation-owned Wasmtime store/host state;
- propagate success and declared echo-domain errors;
- contain invalid component input, guest trap, deadline timeout, explicit cancellation, memory pressure, and bounded queue rejection without poisoning the following activation;
- clear activation-owned stores, host state, component instances, cancellation registrations/probes, temporary buffers, and retained logs on every measured terminal path; and
- keep configured runtime workers, process count, listeners/sockets, and cell capacity independent of the invoked service in the measured lifecycle.

The measured runtime may create one bounded Wasmtime epoch-interruption helper thread after preparation; that is node/runtime infrastructure rather than a per-service thread. The full evidence and measurement limits are in [`../phase-0-completion.md`](../phase-0-completion.md) and [`../../benchmarks/phase0/BASELINE.md`](../../benchmarks/phase0/BASELINE.md).

Phase 0 did **not** implement the complete planes/topology described below. In particular it did not prove dormant registration at 100,000 services, route/admission behavior, persistent management/deployment, production trust/security, generic dispatch, durable state/effects, remote transport, cluster behavior, or production telemetry/SLOs.

## Service model

```text
Service = stable logical name
Release = immutable capsule digest
Revision = release + deployment configuration
Route = rule selecting a revision
Activation = revision × function × input × identity × budget × deadline
Result = output + state commit + effect intents + accounting
```

There is intentionally no `Service = PID + port + heap + threads` relationship.

## Planes

### Developer plane

Builds WIT contracts and language components, creates capsules, produces SBOM/provenance, signs artifacts, and publishes them as OCI artifacts.

### Control plane

Stores desired state, validates releases, compiles bindings and routes, evaluates policy, records node inventories, and distributes immutable route snapshots. It does not participate in ordinary invocation routing after a snapshot reaches a node.

### Data plane

Receives triggers and direct calls, resolves exact revisions from a local snapshot, performs admission, schedules activations, materializes code, binds capabilities, executes guest code, commits state, persists effect intents, and returns results.

These plane descriptions are target architecture unless a linked implementation document says otherwise; Phase 0 implemented only the local component-preparation/execution/reclamation slice.

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

Standalone mode is intended to embed the required control-plane behavior into one `latentd` process and use local storage. Production mode is intended to separate the clustered control plane from data-plane nodes. Neither topology is a Phase 0 product surface.

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

The count is configured by node policy, not by deployed service count. Phase 0 used one process and a fixed in-process cell pool; stronger trust-class process isolation remains later work.

## Technology direction

- WebAssembly Component Model for portable polyglot capsule boundaries.
- WIT for capsule exports, imports, and host capabilities.
- Wasmtime as the initial execution engine behind `ExecutionBackend`.
- OCI artifacts for content-addressed distribution.
- Protobuf for control-plane and generic management RPCs.
- A transport abstraction suitable for WIT-native remote invocation.
- Explicit state transactions and durable effect intents.

These are recorded in ADRs and remain replaceable behind the Rust trait boundaries where explicitly stated. Phase 1 must apply the retain/harden/generalize/rewrite/delete handoff recorded in [`../phase-0-completion.md`](../phase-0-completion.md).
