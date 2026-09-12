# Versioning and deployment

## Immutable release

In Phase 1, `ReleaseDigest` is SHA-256 of component bytes. The local catalog's
versioned completion record separately binds the descriptor, contracts and
canonical capsule manifest to those bytes. Metadata cannot change under an
existing release identity. This detects accidental storage corruption under the
locally trusted filesystem boundary. See the
[local release catalog](../development/local-release-catalog.md).

Phase 2 introduces a separate `PackageDigest` over exact package-manifest bytes
and a [bounded OCI library adapter](../reference/oci-registry.md) for immutable
package distribution. These additions preserve the existing local release
identity. Separate [publisher](../reference/publisher-trust.md) and
[builder-provenance](../reference/build-provenance.md) verifiers authenticate
exact package evidence against explicit current trust policies.
[Authenticated package admission](../reference/package-admission.md) combines
those proofs with semantic, SBOM and tenant checks. An OCI transfer or standalone
verification proof does not admit a release or make it routable.

[Release compatibility](../reference/release-compatibility.md) checks actual-node
requirements and compares exact old/candidate package contracts. Its report is
an input to controlled rollout; it never grants execution authority or changes
the immutable versioned contract identifiers selected by callers.

[Release lifecycle](../reference/release-lifecycle.md) separately persists
admitted, revoked and retired state, with rejected attempts retained as bounded
operation outcomes. Authenticated mutations use exact lifecycle generations.
Revocation preserves immutable content and invalidates old held capabilities;
deploy, rollback or ordinary republication cannot restore permission. Evidence
renewal requires fresh bounded control compilation, including startup recovery,
before an old route can acquire current grants.

## Mutable deployment

A deployment points to a release and supplies capability grants, resource ceilings
and route weight. The schema also carries placement and availability declarations;
Phase 1 validates supported local requirements but does not reconcile cached
copies or place work across nodes. Three distinct identities describe updates:

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

Deployments become active through atomic route-snapshot publication. Existing activations remain pinned to their selected release and policy generation. A call accepted at the final execution fence may finish; a merely routed, queued or ready call still checks current lifecycle before starting. New activations use the new snapshot and current eligibility.

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

Phase 1 supports coexisting local revisions and explicit contract/function
selection. Consumer/provider binding resolution and contract migration remain
later work; see [contracts and bindings](contracts-and-bindings.md).

## Derived artifacts

AOT images, snapshots, and fused components are cache derivatives. Their keys include every input release, policy digest, runtime/compiler configuration, target, and CPU feature set. They are invalidated rather than migrated when any input changes.

The implemented prepared cache holds locally compiled Wasmtime code under
validated compatibility keys. Snapshotting, fused composition and distributed
AOT artifact acceptance remain planned; prepared entries retain no guest store.

Phase 2 also provides an [isolated trusted-local compiler producer](../runtime/trusted-aot.md)
with authenticated, bounded native-output ownership. Persistent storage and
runtime loading of that output remain issue #151; the current prepared cache
continues using its existing local compilation path.
