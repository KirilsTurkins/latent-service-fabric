# Versioning and deployment

Phase 2 feature delivery extends the completed Phase 1 local routing model.
[Gate #158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158)
remains pending. Identity, historical outcome and current permission remain
separate at every publication boundary.

## Immutable release

`ReleaseDigest` remains SHA-256 of component bytes. The local catalog's
versioned completion record separately binds the descriptor, contracts and
canonical capsule manifest to those bytes. Metadata cannot change under an
existing release identity. This detects accidental storage corruption under the
locally trusted filesystem boundary. See the
[local release catalog](../development/local-release-catalog.md).

Phase 2 adds a separate `PackageDigest` over exact package-manifest bytes
and [bounded OCI transfer](../reference/oci-registry.md) for immutable
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
| Operation ID | A caller-retained identifier for one exact scoped request and its finite retained receipt. It is neither a release identity nor a generation. |

Deployment generations are allocated from the catalog publication sequence.
Accepted applies, including unchanged writes, assign the new stamp to affected
objects; deletion and recreation cannot reuse an old stamp. Snapshot-only
publication retains object versions. Reweighting advances the deployment and
route generations while preserving `RevisionId`. See
[deployment and routing semantics](../deployment-routing.md).

## Route switch

Deployments become active through atomic route-snapshot publication. Existing activations remain pinned to their selected release and policy generation. A call accepted at the final execution fence may finish; a merely routed, queued or ready call still checks current lifecycle before starting. New activations use the new snapshot and current eligibility.

Desired deployments, routes, rollout progress and managed deployment receipts
share one catalog publication. Preparation owns the exact bounded candidate;
commit rechecks caller object preconditions, route generation and combined state
version under the actual writer lock and final authority fence. A concurrent
writer cannot commit an earlier candidate over a newer control-only change.

| Durable format | Contents and compatibility |
| --- | --- |
| 1 | Legacy deployment catalog remains readable. |
| 2 | Versioned deployment and snapshot metadata retain their existing decoding and checksum behavior. |
| 3 | Combined catalog adds rollout rows and finite committed rollout receipts. |
| 4 | Managed deployment receipts join the same catalog transaction. Earlier omitted fields keep their original encoding. |

All writers preserve histories introduced by later formats, including legacy
apply/delete, snapshot publication and state-only rollout operations. Recovery
checks complete retained associations rather than silently dropping history to
fit changed limits. Confirmed atomic replacement and a failure to confirm the
parent-directory sync are distinct results; the latter requires recovery before
claiming durable completion.

## Managed deployment identity and retention

[Managed Apply/Delete](../phase-2-operator-workflows.md#managed-deployment-receipts)
requires an operation ID, exact expected object generation and exact expected
catalog state version. Actor and tenant come from authentication. A coherent
operation snapshot supplies the object and state precondition, including when
the object is absent. Existing callers can retain the legacy operation path;
requesting managed semantics never silently falls back to it.

The receipt binds action, normalized request, both preconditions, selected
deployment/component/manifest and the resulting object, route and state versions.
Exact retained replay is checked first and returns that original receipt without
compiling or publishing. Changed actor, scope, body or preconditions under the
same retained ID conflict. An Apply replay may describe historical desired state
even after a later delete; it does not restore that state or current eligibility.

The receipt ring is finite. `Unknown` can mean absent or evicted, so it cannot
prove that a request never committed. If an old create receipt has been evicted,
its original state version still prevents rerunning it after a later deletion
returns the object generation to zero. Operators must not automatically replace
an operation ID or refresh its preconditions after an uncertain response.

Catalog disposition, durability and audit acknowledgement are separately
reported. Critical audit reserves its outcome before mutation; exact durable
receipts support startup reconciliation without executing the mutation again.
Canceled callers can still leave a committed catalog and an unknown audit
conclusion. Bounded response leases retain the actual result ownership through
the final response frame.

## Rollout

The [single-node rollout coordinator](../phase-2-rollouts.md) persists an explicit
base/candidate plan and operator-controlled weight stages. Start, advance and
resume check current release eligibility and compatibility, then publish the
complete route generation together with the rollout state and operation receipt.
Pause and abort persist control state without replacing the executable snapshot.
Every commit checks the combined transaction version; concurrent deployment
edits cannot be overwritten by an earlier prepared rollout.

Direct old/candidate comparison uses the exact retained package sources when
available, bounded to 32 MiB per source. Signed package association cannot fall
back to descriptor-only approval. Conservative local comparison and packaged
comparison both reject unknown/unsupported compatibility, including missing
named-type definitions or changed host-import shapes. An explicit breaking
allowance remains tied to the exact pair and never bypasses current eligibility.

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

Rollback targets come from the exact original base of new Start plans, including
its original weight and deployment policy. Completed or aborted plans may still
restore that target if their exact cohort and preconditions hold. The currently
served candidate is historical comparison input and need not regain execution
permission; the restored base must pass current lifecycle, trust and runtime
checks. Legacy plans without a retained target report target-unavailable for a
new rollback. No history derivation or implicit migration fabricates a target.

Canary thresholds, window identity and decision summaries persist with the
operation receipt. Runtime observations themselves remain bounded live data;
restart creates no successful window from old summaries and does not promote
automatically. A retained replay returns its original outcome before fresh
evidence or current generation checks.

## Coexistence

Multiple implementation and contract versions may coexist. A provider is selected only when the consumer's contract requirement and binding policy are satisfied.

The current runtime supports coexisting local revisions and explicit versioned
contract/function selection. Phase 3 adds exact host/provider bindings and
isolated local service calls; it does not migrate a consumer's contract ID
implicitly. See [contracts and bindings](contracts-and-bindings.md).

## Derived artifacts

AOT images are cache derivatives. Their authenticated identity binds the exact
source, metadata, compiler executable, actual engine/host compatibility and
runtime/security configuration. Current lifecycle and admission capabilities
remain separate use preconditions. Future snapshots and fused components must
similarly bind every relevant input rather than migrate across changed policy.

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
