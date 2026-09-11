<!-- LSF-WIKI-MANAGED -->
# Repository map

| Path | Purpose |
| --- | --- |
| `apps/latentd` | Standalone Linux node and retained Phase 0 paths. |
| `apps/latent` | Working developer/operator RPC CLI. |
| `apps/latent-control` | Later separate control-plane surface, not a Phase 1 deployed service. |
| `crates/` | Implemented subsystems and explicit future trait seams. |
| `wit/`, `api/proto/`, `schemas/` | Authoritative component/RPC/declarative contracts. |
| `sdk/` | Six interface-only language surfaces. |
| `examples/` | Maintained Rust echo and declarative/contract examples. |
| `docs/` | Runtime/operations/protocol guides, completion reports and roadmap. |
| `tests/`, `tools/` | Validation, bounded conformance and explicit full measurements. |
| `benchmarks/` | Compact reports/evidence with bounded retention. |
| `adr/`, `rfcs/`, `research/` | Decisions, proposals and unpromoted experiments. |
| `wiki/` on `docs/wiki` | Separate Wiki source, visual generator, validator and publication. |

Use release for published product source and development for integration. Wiki branch code is an older snapshot, not a runnable release reference.

Authorities: [README](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/README.md), [architecture index](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/ARCHITECTURE.md), [tools](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/tools/README.md).
