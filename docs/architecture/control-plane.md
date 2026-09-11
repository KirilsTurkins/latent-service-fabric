# Control-plane architecture

The control plane manages desired state and compiled metadata. It does not execute capsule code and is excluded from the ordinary invocation hot path.

Phase 1 embeds its implemented release/deployment catalogs, route compiler and
management services in the [standalone node](../reference/standalone-node.md).
The separate `latent-control` application remains a scaffold. PostgreSQL, OCI,
signature/provenance admission, binding compilation and distributed reconciliation
are later-phase designs. The [management API reference](../reference/management-services.md)
lists the supported RPC methods and explicit unsupported operations.

## Modules

### Release catalog

The delivered local catalog indexes immutable component digests, bounded
descriptors and manifest summaries, with verified durable publication and scoped
pagination. Publisher signatures, attestations, SBOM verification and OCI
distribution are planned additions; see [the catalog trust boundary](../development/local-release-catalog.md#trust-boundary).

### Contract registry

The future registry will index exported and imported WIT packages, interfaces,
worlds, functions, type graphs and dependency digests, and produce compatibility
reports and binding plans. Phase 1 validates supplied typed contract metadata
and actual component signatures during preparation.

### Deployment reconciler

Phase 1 validates local desired state and produces deterministic revisions from
a release and execution policy, with atomic weighted route publication and
per-object generation preconditions. A continuous distributed reconciler,
placement and cache-availability reconciliation remain planned.

### Binding compiler

The planned binding compiler connects imported contracts to host capabilities
or provider services and records permitted physical modes. Phase 1 binds only
its supported context, log and clock host imports; it has no service binding graph.

### Policy engine

Phase 1 enforces configured principal/tenant/trust/cell authorization, supported
capability grants and bounded resource admission. Publisher trust, general egress,
state/secrets providers, fusion and native fallback remain planned policy domains.

### Route compiler

Builds an immutable `RouteSnapshot` containing local service routes, weighted
revisions and policy digests. Every snapshot has a monotonically increasing
generation and content digest. Compiled provider bindings are later work.

The standalone deployment compiler verifies every referenced release on every compilation. After fresh verification it can reuse immutable record derivations and remap unchanged packed tenant/service scopes, using an optional bounded metadata memo. It still visits the full desired state and streams a complete canonical durable record into one bounded buffer; commit consumes those exact bytes after generation checks. These choices preserve object versions, weighted routing and crash recovery. See [deployment routing and update cost](../deployment-routing.md#limits-and-update-cost).

### Node inventory

The delivered node exposes bounded local identity, health, drain state, runtime,
cell, queue, cache and load observations. Cluster inventory, region/zone placement,
remote route-generation lag and state affinity are later work.

### Audit subsystem

Phase 1 has bounded structured node/activation telemetry and local management
receipts. The broader durable audit subsystem for signatures, secret access and
cluster administrative decisions remains planned.

## Consistency model

Management writes use optimistic generation checks. Route compilation produces a new immutable generation. Nodes atomically replace their local snapshot. An activation pins the selected revision, release digest, policy digest, and route generation for its complete lifetime.

## Storage boundary

The initial cluster implementation is expected to use PostgreSQL for control state and an OCI registry for artifacts. The interfaces deliberately avoid coupling to either implementation.

## Failure behavior

A temporary control-plane outage must not stop nodes from invoking routes already present in a valid local snapshot. Operations requiring new deployments, route changes, policy changes, or unknown artifacts may be delayed until control-plane access returns.
