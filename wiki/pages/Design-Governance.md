<!-- LSF-WIKI-MANAGED -->
# Design governance

Canonical decisions live in ADRs; proposals needing design work live in RFCs. Invariants include component-native WIT boundaries, no per-service idle execution allocation, reusable generic cells, explicit capability authority, immutable metadata and local routing independent of ordinary control-plane calls.

An accepted design can intentionally precede implementation. OCI, general capability, state/effect, cluster and workflow declarations do not imply shipped features. [Phase 1 status](Phase-1-Status) identifies the delivered boundary.

Keep implementation identity, contract compatibility and measured source identity separate. Evidence is not rewritten after source changes or disappointing results. Failed runs, regressions, unavailable fields and scoped targets remain visible.

The Wiki explains canonical material and contains no unique security rule or compatibility guarantee. Wiki publication and branches remain separate from product branches.

Authorities: [ADRs](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/adr/README.md), [RFCs](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/rfcs/README.md), [contributing](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/CONTRIBUTING.md).
