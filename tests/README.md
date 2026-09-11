# Test suites

This directory holds cross-phase behavioral specifications. Executable Rust
unit and integration tests live with their owning crates and applications;
repository/tooling regressions live in `tools/tests`. Maintained echo, generic
and capabilities components exercise the completed Phase 1 standalone node;
the retained `latentd` Phase 0 harness has separate containment coverage.

Normal workspace tests cover manifests, durable catalogs and routing, admission,
fair scheduling, budgets and cancellation, generic Wasmtime execution, lifecycle
ownership, management/invocation adapters, the CLI, telemetry and SDK contracts.
The [bounded conformance profile](../docs/testing/phase-1-conformance.md) exercises
the real node and CLI. The specifications in the subdirectories also describe
later-phase state, effects, providers, compatibility and cluster requirements;
those requirements are not all implemented by the stateless Phase 1 suite.

See [VALIDATION.md](../VALIDATION.md) for focused commands and the distinction
between ordinary regressions and explicit heavy scaling, profiling, and soak
tests. The [functional completion report](../docs/phase-1-completion.md) records
the completed Phase 1 gate. The
[extension report](../docs/phase-1-extension-completion.md) consolidates subsequent
optimizations and actual Docker/Kubernetes comparisons, including regressions
and environment limits. Historical archive restoration follows the
[retention policy](../docs/testing/benchmark-retention.md).
