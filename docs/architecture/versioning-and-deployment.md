# Versioning and deployment

## Immutable release

A release digest covers component bytes, immutable capsule manifest, WIT lock graph, provenance references, and package metadata. The release never mutates.

## Mutable deployment

A deployment points to a release and supplies capability grants, resource ceilings, placement, availability targets, and route weight. Updating deployment policy creates a new revision generation.

## Route switch

Deployments become active through atomic route-snapshot publication. Existing activations remain pinned to their selected release and policy generation. New activations use the new snapshot.

## Rollout

A future reconciler should support:

1. artifact verification,
2. compatibility checks,
3. cache prefetch targets,
4. canary route weight,
5. health and error observation,
6. progressive weight movement,
7. draining of old route selection,
8. rollback by route pointer.

No step requires a continuously running service instance.

## Coexistence

Multiple implementation and contract versions may coexist. A provider is selected only when the consumer's contract requirement and binding policy are satisfied.

## Derived artifacts

AOT images, snapshots, and fused components are cache derivatives. Their keys include every input release, policy digest, runtime/compiler configuration, target, and CPU feature set. They are invalidated rather than migrated when any input changes.
