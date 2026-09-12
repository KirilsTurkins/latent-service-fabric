<!-- LSF-WIKI-MANAGED -->
# Glossary

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
| Operation receipt | Exact retained committed result bound to actor, tenant, request and operation ID. |
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

See [Core concepts](Core-Concepts), [Deployment and routing](Deployment-and-Routing) and [Security and isolation](Security-and-Isolation) for the relationships between these terms.
