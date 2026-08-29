<!-- LSF-WIKI-MANAGED -->
# Repository map

The repository is intentionally organized around contract authorities,
replaceable Rust seams, executable evidence, and future architecture.

| Path | Current purpose |
|---|---|
| `apps/` | Binary entry points; `latentd` contains the finite Phase 0 spike mode. |
| `crates/` | Rust data models, architectural interfaces, fixed pool, activation runner, and Wasmtime pieces. |
| `wit/` | Guest-visible platform capability and component contracts. |
| `api/proto/` | Control-plane and generic invocation Protobuf contracts. |
| `schemas/` | Declarative resource schemas. |
| `sdk/` | Cross-language interface surfaces. |
| `examples/` | Echo fixture and other contract/declarative examples. |
| `benchmarks/phase0/` | Baseline, calibration, profile, and soak evidence. |
| `docs/` | Architecture, development, protocol, operational, testing, and Phase 0 evidence documentation. |
| `tools/` | Validation, component build, spike, evidence aggregation, and gate tooling. |
| `adr/` | Accepted architecture decisions. |
| `rfcs/` | Proposals that require design review. |
| `research/` | Experimental tracks not promoted into the baseline. |
| `tests/` | Conformance, compatibility, security, integration, chaos, and leak-test specifications. |

## Useful entry points

- [README](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/README.md)
- [Architecture index](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/ARCHITECTURE.md)
- [Validation baseline](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/VALIDATION.md)
- [Phase 0 completion gate](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/phase-0-completion.md)
- [API surface map](https://github.com/KirilsTurkins/latent-service-fabric/blob/development/docs/api-surface.md)

Generated files are intentionally isolated below `target/` or Cargo `OUT_DIR`.
They should not be edited or committed as authoritative source.
