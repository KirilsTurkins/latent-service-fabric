# latent-test-process

Neutral owned child-process and resource-observation helpers for tests. Upstream storage/runtime foundations can use this package without introducing dependencies on the node, capabilities or providers. No process, pipe or probe exists until explicitly constructed.

Owned process lifetime, captured output and resource identity are separate observations: a timeout or guessed PID is insufficient evidence that the intended child has retired.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Neutral process/resource exports with no workspace dependency. |
| [src/process.rs](src/process.rs) | ProcessHarness, limits, captured execution and owned process API. |
| [src/process/](src/process/) | Bounded output, timeout, termination and actual child/pipe retirement implementation. |
| [src/resources.rs](src/resources.rs) | Portable snapshots and richer Linux /proc probes. |
| [src/resources/current.rs](src/resources/current.rs) | Identity-bound current-process observations. |

## Execution and ownership

1. Build an explicit deterministic command with finite lifetime and stdout/stderr bounds.
2. Spawn the owned child and retain both output pipe owners, rejecting invalid limits before spawn.
3. Capture bounded output or terminate on the selected failure/timeout path, then reap the actual child and retire pipes.
4. Bind resource observations to the original process identity and report unsupported measurements as absent rather than inventing values.

## Integration boundaries

Use this dependency directly in low-level test crates. `latent-testkit` reexports these same types for compatibility, but importing its runtime feature upstream can create a dependency cycle. A process snapshot is neither a whole-host isolation proof nor permission to run scale/soak measurements in ordinary tests.

## Dependencies and build

There are no unconditional workspace dependencies. Target-specific and test/build edges, if present, are declared in the manifest.

Consumers with normal workspace dependency edges include [latent-testkit](../latent-testkit/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-test-process.lib.latent-test-process
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`builds_a_repeatable_command`](src/process.rs)
- [`invalid_limits_fail_before_attempting_to_spawn_a_program`](src/process/owned/tests.rs)
- [`aborting_a_reader_drops_the_pipe_without_waiting_for_inherited_writers`](src/process/owned/tests.rs)
- [`child_records_and_both_pipes_are_complete_after_wait`](src/process/owned/tests.rs)

## Related documentation

- [Owned selected test processes](../../docs/development/owned-test-processes.md)
- [Executable build foundation](../../docs/development/build-foundation.md)
- [Deterministic timing and cancellation tests](../../docs/development/deterministic-tests.md)
- [Local test entry point](../../docs/development/local-tests.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
