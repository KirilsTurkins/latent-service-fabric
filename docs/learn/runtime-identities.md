# Runtime identities and recovery terms

These terms connect capsule delivery, invocation and operator recovery. The
control identities below were already part of the alpha.3 surface. Provider
and Angular capabilities in development have their own versioned contracts;
this glossary does not certify the Phase 3 gate.

| Term | Meaning |
| --- | --- |
| Activation | One admitted call with fresh guest state, a selected revision and finite budget. |
| Activation ID | Caller/server correlation and retained-status identity; not general effect idempotency. |
| Admission | Context-dependent: execution-budget admission or checked package publication; neither should be confused with a historical label. |
| Builder authority | Policy authorization for the provenance signer, independent of publisher roles. |
| Canary window | Bounded exact-generation observations with sticky loss and owned terminal samples. |
| Catalog state version | Global managed-deployment CAS identity, including coherent object absence. |
| Component digest | Identity of portable executable component bytes. |
| Control digest | Binding of the exact canary control context; unrelated transactions do not create evidence. |
| Deployment generation | Version of one deployment object. |
| Eligibility | Sealed current permission from the exact catalog/lifecycle and applicable trust authority. |
| Execution cell | Shared configured execution slot. |
| Native compatibility key | Derived source, runtime, compiler and sandbox identity for protected local native reuse. |
| Native receipt | Untrusted stored metadata until authenticated by the configured protected local key. |
| Operation receipt | Exact retained control result bound to actor, tenant, request and operation ID; a release-operation receipt can record rejection as well as commit. |
| Package digest | Exact OCI package manifest identity, separate from its component. |
| Policy/clock floor | Durable monotonic recovery boundary that prevents accepting older authority state. |
| Prepared pin | Ownership of prepared code/resources; not proof that invocation start was accepted. |
| Provenance | Bounded build statement separating observed execution from supplied/asserted identity. |
| Publisher authority | Policy authorization to sign the exact package/component association. |
| Raw cache | Bounded replaceable byte storage with no execution authority. |
| Rollback target | Immutable recorded pre-Start target; restoration still requires current eligibility. |
| Rollout revision | CAS version of one durable rollout state machine. |
| Route generation | Identity of an atomically published immutable routing snapshot. |
| SBOM | Bounded software inventory with honest source/license/completeness scope. |
| Sealed canary proof | Owned exact-window evidence accepted only by the configured hub/store authority. |
| Unknown | Retained state cannot establish a result; absence/eviction is not proof of no commit. |
| Uncertain | Durable confirmation is unresolved; inspect/recover the exact operation. |


## Apply the distinctions

A successful signature check records a historical fact. Invocation still checks
current publisher and builder policy, lifecycle eligibility and the exact
selected revision. A prepared cache pin retains resources without granting
permission to execute. See [security](../architecture/security.md).

After a mutation timeout, query the original operation identity and compare its
retained request and result. A transport timeout does not prove that a durable
commit or external effect did not happen. Follow
[delivery and recovery](deliver-and-recover-a-capsule.md) and the
[operator reference](../reference/operator-cli.md).

Cancellation acknowledgment and completed cleanup are different observations.
The owner remains charged until its work and retained pins actually retire.
Dormant services share execution resources while their catalog metadata and
artifacts still consume space. The [resource model](../runtime/resource-budgets.md)
describes those separate owners; measurements keep their original workload scope.

## Attribution

The term definitions were selectively migrated from the
[original Wiki glossary](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/Glossary.md).
The explanatory distinctions also preserve the useful material from the
[original FAQ](https://github.com/KirilsTurkins/latent-service-fabric/blob/d1035a50d2fd99b076c74dd958ca4437d909f2ec/wiki/pages/FAQ.md).
The [migration inventory](../development/wiki-migration.md) records source and
published identities, legacy destinations and the retained historical evidence.
