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
copies or place work across nodes. These distinct identities describe updates:

| Identity | Meaning |
| --- | --- |
| Deployment generation | The object's last successful mutation version, used for caller preconditions. Unrelated object writes leave it unchanged. |
| Route generation | The catalog's monotonically increasing publication sequence. A batch advances it once. |
| `RevisionId` | A deterministic digest of the deployment's execution policy and release, excluding route weight. |
| Rollout revision | The monotonically increasing version of one persisted rollout, used for rollout operation preconditions. |
| State version | The combined catalog transaction sequence, including rollout-only changes that preserve the route generation. |

Deployment generations are allocated from the catalog publication sequence.
Accepted applies, including unchanged writes, assign the new stamp to affected
objects; deletion and recreation cannot reuse an old stamp. Snapshot-only
publication retains object versions. Reweighting advances the deployment and
route generations while preserving `RevisionId`. See
[deployment and routing semantics](../deployment-routing.md).

## Route switch

Deployments become active through atomic route-snapshot publication. Existing activations remain pinned to their selected release and policy generation. A call accepted at the final execution fence may finish; a merely routed, queued or ready call still checks current lifecycle before starting. New activations use the new snapshot and current eligibility.

## Rollout

The [single-node rollout coordinator](../phase-2-rollouts.md) persists an explicit
base/candidate plan and operator-controlled weight stages. Start, advance and
resume check current release eligibility and compatibility, then publish the
complete route generation together with the rollout state and operation receipt.
Pause and abort persist control state without replacing the executable snapshot.
Every commit checks the combined transaction version; concurrent deployment
edits cannot be overwritten by an earlier prepared rollout.

One fixed worker and bounded shared storage serve all rollouts. Restart restores
committed progress without automatically advancing it. Active invocations keep
their route pins; newly selected work uses the current routes and still checks
release authority at the execution fence. No stage creates a continuously running
service instance. [Canary promotion](../phase-2-canary-promotion.md) requires an
explicit policy and a full, drained observation window bound to the exact catalog
owner, rollout revision and compiled cohort. The catalog rechecks the evidence
and current release eligibility before publishing the next stage.
[Explicit rollback](../phase-2-rollback.md) restores the plan-bound original base
through a new publication generation, after current target eligibility and
candidate-to-base compatibility checks. It records the historical target
separately, preserves invocation pins and conflicts with intervening cohort edits.

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
with authenticated, bounded native-output ownership. Opt-in persistent native
storage and loading bind the approved compiler, actual engine/host compatibility,
exact catalog source and protected host key. Reopened cache hits verify those
identities and current release authority before loading; resident prepared hits
retain their existing bounded ownership. The default mode continues local
portable compilation.
