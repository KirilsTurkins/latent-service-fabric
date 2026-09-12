<!-- LSF-WIKI-MANAGED -->
# Repository map

Use development for current Phase 2 source until a release is published. The Wiki branch is a separate documentation lineage with an older non-Wiki snapshot.

| Location | Current purpose |
| --- | --- |
| `apps/latentd` | Standalone Linux node, configured owners, loopback services and bounded shutdown. |
| `apps/latent` | Local package/OCI commands and authenticated operator client. |
| `crates/latent-packaging`, `latent-oci` | Portable package validation, inventory/evidence associations and registry transfer. |
| `crates/latent-signing`, `latent-policy` | Publisher/builder verification and current supply-chain authority. |
| `crates/latent-artifacts` | Exact release storage, lifecycle capabilities, managed publication and raw cache. |
| `crates/latent-control-store`, `latent-rollout` | Durable deployment/rollout state, atomic publication and bounded coordinator. |
| `crates/latent-audit`, `latent-telemetry` | Durable control audit and bounded activation/canary observations. |
| `crates/latent-wasmtime` | Generic execution, isolated compilation and protected native reuse. |
| Other `crates/` | Domain models, contracts, budgets, scheduling, wire adapters and runtime composition. |
| `api/`, `schemas/`, `sdk/` | WIT/Protobuf, closed JSON profiles and six SDK interface fixtures. |
| `docs/`, `adr/`, `rfcs/` | Canonical explanation, decisions and planned architecture. |
| `tools/` | Bounded build/validation runners and the maintained real operator workflow. |
| `benchmarks/` | Historical evidence, reports and exact restoration metadata. |

The current node embeds local control ownership. Separate distributed control, placement and general cluster operation remain later phases; repository scaffolding is not proof of those capabilities.

The Wiki's `wiki/pages/` contains exactly 26 managed pages and four generated visual assets. Publication preserves unmanaged Wiki files and records exact source/remote identities separately. Never treat an old Wiki code tree as the current build.

Authorities: [repository root](https://github.com/KirilsTurkins/latent-service-fabric/tree/development), [architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/ARCHITECTURE.md), [operator runner](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/tools/run_phase2_operator_workflow.py), [development workflow](Development-Workflow).
