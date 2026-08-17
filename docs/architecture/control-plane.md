# Control-plane architecture

The control plane manages desired state and compiled metadata. It does not execute capsule code and is excluded from the ordinary invocation hot path.

## Modules

### Release catalog

Indexes immutable capsule digests, OCI references, publisher identity, signatures, attestations, SBOMs, WIT contract digests, admission status, and compatibility metadata.

### Contract registry

Indexes exported and imported WIT packages, interfaces, worlds, functions, type graphs, and dependency digests. It provides compatibility reports and binding plans.

### Deployment reconciler

Combines a release with mutable grants, resource ceilings, placement constraints, cache-availability targets, and route weights to produce a revision.

### Binding compiler

Connects imported contracts to host capabilities or provider services. It records the permitted physical modes: host, inline, isolated local, remote, or automatic.

### Policy engine

Evaluates publisher trust, capability grants, placement, resource ceilings, tenant quotas, network egress, state namespaces, secret access, fusion eligibility, and native fallback eligibility.

### Route compiler

Builds a fully resolved immutable `RouteSnapshot` containing service routes, weighted revisions, bindings, and policy digests. Every snapshot has a monotonically increasing generation and content digest.

### Node inventory

Tracks node identity, architecture, CPU features, trust classes, cell capacity, queue pressure, cache locality, region/zone, state-affinity information, and route-generation lag.

### Audit subsystem

Records administrative mutations, policy decisions, signature results, capability grants, route switches, secret access, and security-sensitive denials.

## Consistency model

Management writes use optimistic generation checks. Route compilation produces a new immutable generation. Nodes atomically replace their local snapshot. An activation pins the selected revision, release digest, policy digest, and route generation for its complete lifetime.

## Storage boundary

The initial cluster implementation is expected to use PostgreSQL for control state and an OCI registry for artifacts. The interfaces deliberately avoid coupling to either implementation.

## Failure behavior

A temporary control-plane outage must not stop nodes from invoking routes already present in a valid local snapshot. Operations requiring new deployments, route changes, policy changes, or unknown artifacts may be delayed until control-plane access returns.
