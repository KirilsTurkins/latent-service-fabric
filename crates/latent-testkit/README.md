# latent-testkit

Explicit deterministic and conformance helpers for tests, with an optional node/runtime harness. It reexports core test support and the exact neutral `latent-test-process` types rather than implementing a second process owner.

The default `runtime` feature brings activation/executor/node/telemetry contracts. Low-level consumers should select `default-features = false`, or depend directly on the neutral owner they need, to preserve the workspace dependency direction.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Feature-gated exports, deterministic clocks/IDs/coordination and neutral process reexports. |
| [src/async_runtime.rs](src/async_runtime.rs) | Explicit current-thread AsyncTestRuntime; no global runtime initialization. |
| [src/conformance.rs](src/conformance.rs) | Finite source-matched conformance work and receipts independent of a particular node driver. |
| [src/harness.rs](src/harness.rs) | Adapters over caller-owned runtime services, behind the runtime feature. |
| [src/runtime_contract.rs](src/runtime_contract.rs) | Runtime-dependent invariant/probe contracts. |
| [tests/test_support_compatibility.rs](tests/test_support_compatibility.rs) | Reexport/type compatibility with the neutral foundations. |

## Execution and ownership

1. Choose the smallest feature/dependency surface needed by the test owner.
2. Construct clocks, runtime, workspace or process helpers explicitly inside the test.
3. Drive bounded deterministic scenarios against the caller-supplied implementation, sharing the same total work ceiling.
4. Retire actual helpers/children and preserve source/command identity in conformance evidence.

## Integration boundaries

Conformance adapters do not create a second activation ledger or certify the complete performance/resource gate. `tools/check_testkit_dependencies.py` checks the neutral dependency boundary, including non-default edges. Registered test preparation and discovery still go through the repository test front door; a helper library is not its replacement.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-test-process](../latent-test-process/README.md), [latent-activation](../latent-activation/README.md) (optional), [latent-executor](../latent-executor/README.md) (optional), [latent-node](../latent-node/README.md) (optional), [latent-telemetry](../latent-telemetry/README.md) (optional).

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `default` | `runtime` |
| `runtime` | `dep:latent-activation`, `dep:latent-executor`, `dep:latent-node`, `dep:latent-telemetry` |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-testkit.lib.latent-testkit
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`executes_on_an_explicit_current_thread_runtime`](src/async_runtime.rs)
- [`rejected_invocation_attempts_share_the_same_hard_work_ceiling`](src/conformance/tests.rs)
- [`command_ceiling_also_bounds_non_invocation_work`](src/conformance/tests.rs)
- [`expanded_drivers_share_the_same_total_work_ceiling`](src/conformance/tests.rs)

Integration targets: [tests/test_support_compatibility.rs](tests/test_support_compatibility.rs).

## Related documentation

- [Deterministic timing and cancellation tests](../../docs/development/deterministic-tests.md)
- [Owned selected test processes](../../docs/development/owned-test-processes.md)
- [Local test entry point](../../docs/development/local-tests.md)
- [Executable build foundation](../../docs/development/build-foundation.md)
- [Validation](../../VALIDATION.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
