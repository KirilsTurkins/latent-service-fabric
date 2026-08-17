# LSF architecture overview

## Definition

Latent Service Fabric is a component-native execution fabric in which deployed services are dormant immutable artifacts. Requests become temporary activations. Activations execute inside a fixed pool of reusable sandboxed cells and release all activation-owned resources when they finish or suspend durably.

## Resource invariant

```text
resident resources = fixed node runtime + active activations + bounded global caches
```

A deployed but inactive service owns no process, operating-system thread, listener, heap, runtime instance, database connection pool, HTTP client pool, timer loop, or telemetry exporter.

Artifact storage, contract indexes, route indexes, policy metadata, and bounded cache entries are permitted to grow with registered service count. Execution allocation is not.

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

Standalone mode embeds the control plane into one `latentd` process and uses local storage. Production mode separates the clustered control plane from data-plane nodes.

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

The count is configured by node policy, not by deployed service count.

## Technology direction

- WebAssembly Component Model for portable polyglot capsule boundaries.
- WIT for capsule exports, imports, and host capabilities.
- Wasmtime as the initial execution engine behind `ExecutionBackend`.
- OCI artifacts for content-addressed distribution.
- Protobuf for control-plane and generic management RPCs.
- A transport abstraction suitable for WIT-native remote invocation.
- Explicit state transactions and durable effect intents.

These are recorded in ADRs and remain replaceable behind the Rust trait boundaries where explicitly stated.
