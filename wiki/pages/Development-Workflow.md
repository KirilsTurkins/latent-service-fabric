<!-- LSF-WIKI-MANAGED -->
# Development workflow

Current product work targets development through focused branches and reviewed pull requests. Published tags/release branches identify shipped snapshots. The Wiki's `docs/wiki` branch owns documentation only; never merge its older product tree into development or release.

Start with [CONTRIBUTING](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/CONTRIBUTING.md). Check assignment and existing pull requests before taking a ticket. The [good-first-issue queue](https://github.com/KirilsTurkins/latent-service-fabric/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22) contains small evergreen tasks; they are not implicit dependencies of the main phase.

A useful change identifies the exact behavior, input bounds, owner and failure semantics, then validates the affected contract. Separate public identity from caller metadata, historical evidence from current authority, and a reserved resource from completed cleanup. Keep default dormant-service resources unchanged unless an approved design explicitly changes them.

Use `make help` and [VALIDATION](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/VALIDATION.md) to select required checks. Repository/schema/SDK tests, focused runtime tests, real workflow checks and heavy measurement campaigns serve different purposes. Do not run full 100k or historical authorization gates as routine documentation validation.

Phase 2 delivery gate [#158](https://github.com/KirilsTurkins/latent-service-fabric/issues/158) is pending. Phase 3's [41 planned tickets](https://github.com/KirilsTurkins/latent-service-fabric/issues/201) are decomposed capabilities with dependencies and resource/security acceptance. Planning and issue creation are not implementation delivery.

Update canonical repository docs alongside behavior and preserve historical measurement sources. The Wiki may summarize those docs, but it must not become the only home of a security rule, compatibility promise or operational recovery procedure.

Authorities: [build foundation](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/development/build-foundation.md), [toolchain](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/development/toolchain.md), [design governance](Design-Governance).
