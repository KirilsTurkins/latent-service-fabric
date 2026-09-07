# Test suites

This directory holds cross-phase behavioral specifications. Executable Rust
unit and integration tests live with their owning crates and applications;
repository/tooling regressions live in `tools/tests`. The maintained echo
component and `latentd` Phase 0 harness provide execution/containment fixtures.

Normal workspace tests cover the implemented manifest codec, resource budgets
and cancellation, fixed cell pool, local release catalog, and deployment/routing
foundations. Future-phase specifications here do not imply an implemented
conformance suite or a completed Phase 1 node workflow.

See [VALIDATION.md](../VALIDATION.md) for focused commands and the distinction
between ordinary regressions and explicit heavy scaling, profiling, and soak
tests. Phase 1's integrated conformance and completion harness remains tracked
by [#16](https://github.com/KirilsTurkins/latent-service-fabric/issues/16).
