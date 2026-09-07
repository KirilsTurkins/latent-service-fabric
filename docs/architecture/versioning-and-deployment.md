# Versioning and deployment

## Immutable release

In Phase 1, `ReleaseDigest` is SHA-256 of component bytes. The local catalog's
versioned completion record separately binds the descriptor, contracts and
canonical capsule manifest to those bytes. Metadata cannot change under an
existing release identity. This detects accidental storage corruption under the
locally trusted filesystem boundary; package signatures, provenance and OCI
distribution remain later-phase work. See the
[local release catalog](../development/local-release-catalog.md).

## Mutable deployment

A deployment points to a release and supplies capability grants, resource ceilings,
placement, availability targets, and route weight. Three distinct identities
describe updates:

| Identity | Meaning |
| --- | --- |
| Deployment generation | The object's last successful mutation version, used for caller preconditions. Unrelated object writes leave it unchanged. |
| Route generation | The catalog's monotonically increasing publication sequence. A batch advances it once. |
| `RevisionId` | A deterministic digest of the deployment's execution policy and release, excluding route weight. |

Deployment generations are allocated from the catalog publication sequence.
Accepted applies, including unchanged writes, assign the new stamp to affected
objects; deletion and recreation cannot reuse an old stamp. Snapshot-only
publication retains object versions. Reweighting advances the deployment and
route generations while preserving `RevisionId`. See
[deployment and routing semantics](../deployment-routing.md).

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
