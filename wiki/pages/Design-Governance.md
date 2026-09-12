<!-- LSF-WIKI-MANAGED -->
# Design governance

The dormant-service invariant, explicit ownership and bounded resource model guide current implementation. A new feature must explain what it owns, when it can deny work, how cancellation/recovery behave and which identities authorize action.

Canonical ADRs, RFCs, code contracts and validation evidence live in the product repository. The Wiki is explanatory. Product changes target development; documentation publication from the separate Wiki branch does not promote a product release.

Phase 2 delivered concrete package, trust, cache, audit and rollout implementations. Their boundaries remain narrow: cache storage is not execution authority, a canary report is not a sealed proof, historical admission is not current eligibility, and an audit Unknown outcome is not a rolled-back catalog mutation.

Phase 3 has [41 planned tickets](https://github.com/KirilsTurkins/latent-service-fabric/issues/201) for brokers, providers, web hosting, SDK delivery and gates. The design must preserve versioned host contracts, explicit policy, bounded async ownership, descendant budgets, pool limits and browser/security boundaries. [#44](https://github.com/KirilsTurkins/latent-service-fabric/issues/44) retains its web/Angular acceptance while concrete child tickets implement it.

Reviews should connect a concrete trigger to observable behavior and meaningful failure tests. Exact actor/tenant/generation bindings, response preflight before critical side effects, retained owner accounting, private filesystem recovery and finite rejection paths are part of correctness.

Measurements retain their original configuration, population and execution identity. Regressions are not removed because later features shipped. A source check, passing CI, issue closure, delivery gate and remote publication receipt establish different facts. The [Phase 2 completion report](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-2-completion.md) records the decision and retains failed attempts alongside its finite passing evidence.

Authorities: [ADR index](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/adr/README.md), [RFC index](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/rfcs/README.md), [architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/ARCHITECTURE.md), [roadmap](Roadmap).
