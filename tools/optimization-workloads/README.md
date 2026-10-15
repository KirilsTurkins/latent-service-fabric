# latent-optimization-workloads

Identical deterministic workload logic for the native comparison reference and Wasm benchmark component. The package exports echo, bounded wrapping computation and record transformation plus the canonical LSF WIT-value framing used to invoke them.

Accepted-input semantics are shared; execution contracts are not. This helper has no I/O, clock, logs, retained state, fabric scheduler or fuel/memory enforcement.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Pure echo/compute/transform functions, limits and workload errors. |
| [src/framing.rs](src/framing.rs) | Bounded canonical argument/result arrays and invocation dispatch. |

## Execution and ownership

1. Validate the workload name and exact bounded argument frame.
2. Apply shared payload/text/collection/round limits before performing work.
3. Execute the same deterministic function in both comparison arms and encode canonical result fields.
4. Record invalid-input behavior outside accepted-input timing comparisons: native errors and Wasm traps are distinct mechanisms.

## Integration boundaries

Echo uses ["hello"] in both directions and permits empty text. Transform preserves the label, reverses bytes and applies the source-defined wrapping arithmetic using each original index. u8/u32 are JSON integers rather than decimal strings. Limits are 1 MiB frames/text, 4,096 collection items and 1,000,000 rounds; the implementation rejects excess rather than clamping. These bounds do not make the native reference a sandbox.

## Dependencies and build

There are no unconditional workspace dependencies. Target-specific and test/build edges, if present, are declared in the manifest.

Consumers with normal workspace dependency edges include [latent-toolchain-smoke](../toolchain-smoke/README.md), [latent-optimization-bench](../optimization-bench/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-optimization-workloads.lib.latent-optimization-workloads
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`exact_canonical_frames_match_the_pure_workloads`](src/tests.rs)
- [`compute_has_stable_wrapping_vectors_and_a_zero_round_identity`](src/tests.rs)
- [`invalid_inputs_are_rejected_without_echoing_payloads`](src/tests.rs)
- [`collection_and_frame_limits_reject_before_execution`](src/tests.rs)

## Related documentation

- [WIT value payloads](../../docs/protocol/wit-values.md)
- [Native comparison reference](../optimization-bench/src/bin/optimization_native/README.md)
- [component.rs](../toolchain-smoke/examples/optimization_capsule/component.rs)
- [Benchmark program](../../benchmarks/README.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)
