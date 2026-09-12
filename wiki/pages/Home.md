<!-- LSF-WIKI-MANAGED -->
# Latent Service Fabric

LSF runs stateless WebAssembly components on a bounded, shared execution topology. Dormant services retain metadata and artifacts; they do not own a guest heap, process or listener.

**Phase 2 is complete; the [completion report](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-completion.md) records the gate decision, exact evidence and qualifications.** Packaging, signed admission, lifecycle controls, protected native reuse, durable audit, rollouts, canary promotion, rollback and operator workflows extend the completed Phase 1 baseline. Phase 3 has **41 planned tickets** under [epic #201](https://github.com/KirilsTurkins/latent-service-fabric/issues/201); those capabilities are not current runtime promises.

![Phase 2 package, control and invocation path](assets/architecture-at-a-glance.gif)

| Start here | What it explains |
| --- | --- |
| [Getting started](Getting-Started) | The Linux node, explicit local configuration and current source branch. |
| [Operator CLI](Operator-CLI) | Package/OCI workflows and authenticated release, deployment, rollout and audit operations. |
| [Security and isolation](Security-and-Isolation) | Publisher and builder authority, current eligibility, compiler isolation and cache trust. |
| [Deployment and routing](Deployment-and-Routing) | Atomic publication, operation receipts, canary policy, rollback and recovery. |
| [Architecture](Architecture) | Shared owners, fixed execution resources and separately bounded storage. |
| [Phase 1 status](Phase-1-Status) | The historical baseline and its original evidence. |
| [Roadmap](Roadmap) | Phase 2 completion and planned Phase 3 capabilities. |

Phase 1 functional completion on September 8 and the September 11 performance extension remain separate historical evidence populations. Their reports do not become Phase 2 measurements. The new resource experiment covers 32 releases, 16 deployments and two warmed portable runtime images; [testing guidance](Testing-and-Benchmarks) preserves that finite scope and the earlier unclassified failed attempt.

The current published release remains **alpha.2**. Phase completion and Wiki publication do not publish a new product release. Current canonical links use [development](https://github.com/KirilsTurkins/latent-service-fabric/tree/development) until that release is published. The repository owns requirements and implementation; the Wiki explains them. Start with the [operator workflow guide](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-operator-workflows.md) and [architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/ARCHITECTURE.md).

Reviewed September 13, 2026. Live Wiki publication is recorded separately from source validation.
