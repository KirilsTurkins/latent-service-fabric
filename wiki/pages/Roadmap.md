<!-- LSF-WIKI-MANAGED -->
# Roadmap and delivery boundaries

Implementation, retained evidence, gate completion and release publication are distinct. The current feature map is:

| Phase | Status and boundary |
| --- | --- |
| Phase 0 | Historical feasibility handoff completed August 30, 2026, for its exact recorded execution identity. |
| Phase 1 | Single-node stateless runtime functionally complete September 8; performance extension complete September 11. |
| Phase 2 | Complete: packaging, verified admission, lifecycle, isolated AOT/native reuse, audit, rollouts, canary promotion, rollback and operator workflows. The completion report records finite evidence and qualifications. |
| Phase 3 | 41 planned tickets covering capability brokers/providers, HTTP/web hosting, SDK delivery and operator/security/resource gates. |
| Phase 4 | Transactional guest state and explicit effect handling. |
| Phase 5 | Cluster control, placement, node identity and distributed operation. |
| Phase 6 | Durable workflows and resumable orchestration. |
| Phase 7 | Subsequent optimization and expansion against delivered evidence. |

Phase 2 keeps portable package identity separate from local native-code trust. OCI distribution and signatures do not establish a distributed native attestation protocol. Its rollout commands are operator-triggered; canary policy gates explicit promotion, and rollback restores only an eligible recorded target through a new route generation.

The Phase 3 [capability epic #201](https://github.com/KirilsTurkins/latent-service-fabric/issues/201) includes versioned host ABI/policy, bounded async I/O and pools, local child calls with descendant budgets, outbound HTTP, blobs, secrets, events, randomness and metrics. Concrete SDK transports and parity fixtures have their own delivery tickets.

[Web hosting parent #44](https://github.com/KirilsTurkins/latent-service-fabric/issues/44) retains its Angular/browser/SSR acceptance and is decomposed into concrete children. HTTP contracts and ingress, immutable asset delivery, renderer isolation, browser security and hydration are planned integrations. Existing browser/SSR package profiles do not mean a hosting runtime already exists.

The plan includes operator tooling, security tests, resource accounting and documentation gates. A future capability must have an owner, finite capacity, cancellation and recovery rules before it becomes an executable contract.

Historical extension [epic #97](https://github.com/KirilsTurkins/latent-service-fabric/issues/97) and [gate #113](https://github.com/KirilsTurkins/latent-service-fabric/issues/113) remain closed; #110 was closed as not planned. Their measurements are retained unchanged. Follow [Phase 1 status](Phase-1-Status) and [performance evidence](Performance-and-Infrastructure) for those claims.

The current published release remains alpha.2; completion does not itself publish a successor. Current Phase 2 guidance stays on development until product release publication.

Authorities: [roadmap](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/roadmap.md), [Phase 2 completion](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-completion.md), [Phase 3 epic](https://github.com/KirilsTurkins/latent-service-fabric/issues/201).
