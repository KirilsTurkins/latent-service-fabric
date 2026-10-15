# latent-optimization-bench

Explicit measurement tooling: an external load client, native reference, container supervisor and artifact identity probe. Product dispatch remains in the runtime; shared application semantics remain in `latent-optimization-workloads`.

These executables produce source/configuration-bound observations, not an automatic performance guarantee. Ordinary workspace tests exercise bounded helper correctness and do not run scale or soak workloads.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/client/mod.rs](src/client/mod.rs) | External finite load-client planning, calls and measurement receipts. |
| [src/bin/optimization-client.rs](src/bin/optimization-client.rs) | Load-client executable entry. |
| [src/bin/optimization_native/mod.rs](src/bin/optimization_native/mod.rs) | Authenticated loopback native reference with deliberately fewer runtime guarantees. |
| [src/bin/optimization_container/mod.rs](src/bin/optimization_container/mod.rs) | PID1 child/transport owner for controlled infrastructure comparisons. |
| [src/bin/artifact_identity_probe/mod.rs](src/bin/artifact_identity_probe/mod.rs) | Exact artifact/cache identity comparison probe. |
| [src/bin/artifact_identity_probe/fixture/padding.rs](src/bin/artifact_identity_probe/fixture/padding.rs) | Validated component padding without changing executable sections. |

## Execution and ownership

1. Prepare an explicit finite plan and source/binary/fixture identities before measurement.
2. Validate accepted inputs through the shared workload helper, then run the selected transport/runtime arm.
3. Observe phase timing, resource/owner behavior and failures without treating unavailable counters as measured zeros.
4. Stop and reap actual child/transport owners, then retain receipts with the exact arm/configuration and scope.

## Integration boundaries

The native reference has no Wasm isolation, preemptive fuel/memory meter, fabric scheduler, catalog or activation journal. Its labels are reference identities, not component hashes; cancellation/status are unimplemented. An unrestricted/native lower-overhead comparison cannot establish a semantics-equivalent runtime speedup. Run costly campaigns only through their explicit plans and owners.

## Dependencies and build

Direct workspace dependencies: [latent-artifacts](../../crates/latent-artifacts/README.md), [latent-control-store](../../crates/latent-control-store/README.md), [latent-core](../../crates/latent-core/README.md), [latent-manifest](../../crates/latent-manifest/README.md), [latent-routing](../../crates/latent-routing/README.md), [latent-optimization-workloads](../optimization-workloads/README.md), [latent-rpc](../../crates/latent-rpc/README.md), [latent-wire](../../crates/latent-wire/README.md).

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-optimization-bench.lib.latent-optimization-bench
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`exact_padding_preserves_executable_sections_and_validates_at_leb_boundaries`](src/bin/artifact_identity_probe/fixture/padding.rs)
- [`rejects_truncation_invalid_component_and_too_small_custom_section`](src/bin/artifact_identity_probe/fixture/padding.rs)
- [`repository_measurements_cannot_hide_repeated_warm_reopens`](src/bin/artifact_identity_probe/tests.rs)
- [`immediate_directory_port_rejects_unexpected_suspension`](src/bin/artifact_identity_probe/tests.rs)

## Related documentation

- [Native comparison reference](src/bin/optimization_native/README.md)
- [Benchmark program](../../benchmarks/README.md)
- [CI performance and coverage](../../docs/development/ci-performance.md)
- [Owned selected test processes](../../docs/development/owned-test-processes.md)
- [Local test entry point](../../docs/development/local-tests.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)
