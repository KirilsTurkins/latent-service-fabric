# Deployment and Routing

> **Document role:** Explanatory deployment model. Declarative schemas, route snapshots, and architecture files are authoritative.

## Identity chain

```text
Service
  → immutable Release
  → Deployment policy
  → compiled Revision
  → RouteSnapshot selection
  → pinned Activation
```

### Release

The immutable release digest covers component bytes, the immutable capsule manifest, WIT lock graph, provenance references, and package metadata.

### Deployment

A deployment points to a release and supplies mutable policy:

- capability grants;
- resource ceilings;
- placement constraints;
- availability and cache targets;
- route weight.

Changing deployment policy creates a new revision generation rather than mutating the release.

### Route snapshot

The control plane compiles routes, revisions, bindings, and policy digests into an immutable snapshot with a monotonic generation and content digest. Nodes replace the local snapshot atomically.

An activation pins its selected release, revision, policy digest, and route generation for its full lifetime.

## Route switches

A route update affects new activations. Existing activations continue under their pinned generation, including after a canary weight shift or rollback.

This avoids changing code or policy halfway through an invocation.

## Rollout direction

The future reconciler is intended to support:

1. artifact verification;
2. contract compatibility checks;
3. cache prefetch targets;
4. canary route weight;
5. health and error observation;
6. progressive weight movement;
7. draining old route selection;
8. rollback by route pointer.

No rollout step requires a continuously running service instance.

## Coexisting versions

Multiple implementation and contract versions may coexist. A provider is eligible only when the consumer's contract requirement and binding policy are satisfied.

Breaking contracts require a new major contract version and an explicit migration or parallel-routing plan.

## Triggers and ingress

HTTP, direct RPC, event, queue, timer, and blob triggers terminate in shared adapters. A trigger maps input into an activation request; it does not create a service-owned listener or consumer loop.

## Control-plane availability

A temporary control-plane outage should not stop nodes from invoking routes already present in a valid local snapshot. New deployments, route changes, policy changes, and unknown artifacts may wait until control access returns.

## Derived artifacts

AOT images, snapshots, and fused components are cache derivatives, not releases. Their cache keys include all input releases, policy digests, compiler/runtime configuration, target, and CPU features. A changed input invalidates the derivative.

## Operational capacity

Plan capacity by active concurrency, cell classes, worker counts, bounded cache limits, provider pool limits, trust-class partitions, and artifact/state locality—not by registered service count.

Required operational views include route-generation lag, queue delay, cell availability, cache hit rates, activation outcomes, state conflicts, effect retries, and process/thread/socket counts relative to registered releases.

## Canonical sources

- [Versioning and deployment](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/versioning-and-deployment.md)
- [Control-plane architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/control-plane.md)
- [Ingress and triggers](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/ingress-and-triggers.md)
- [Operational topology](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/operations/topology.md)
- [Deployment schema](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/schemas/deployment.schema.json)
- [Route snapshot schema](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/schemas/route-snapshot.schema.json)
