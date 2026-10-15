# latent-workflows

Durable workflow continuation and suspension vocabulary. `Continuation` records a definition digest, logical program counter, serialized locals, suspension condition, state version and attempt. Timer, event, effect, child-workflow and manual waits are represented as data.

This package is an interface scaffold, not an operational workflow engine. `ContinuationStore` and `WorkflowRuntime` signatures do not implement atomic checkpoint/wait registration, exclusive resume, crash recovery, compiler capture or complete guest Store reclamation.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | SuspensionPoint, WorkflowStatus, Continuation, WorkflowTransition and persistence/runtime traits. |

## Execution and ownership

1. A future qualified frontend would capture bounded logical state at an approved persistence boundary.
2. A durable host would atomically record the continuation and original wait/effect obligations under an exclusive generation fence.
3. The original execution owner would actually retire before its Store/cell could be reused.
4. A fresh admitted segment would recheck current authority and exact definition/format before resuming from recorded state.

## Integration boundaries

The sequence above is the proposed integration obligation, not implemented behavior. Store-local activation `park`/`wake` tokens are not durable continuations. Replay-based orchestration, compiler-generated capture and ordinary asynchronous waits require different contracts; none may silently renew budgets or replay uncertain external effects.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-state](../latent-state/README.md), [latent-effects](../latent-effects/README.md).

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-workflows.lib.latent-workflows
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Continuation-eviction research](../../docs/runtime/continuation-eviction-research.md)
- [Continuation eviction](../../research/continuation-eviction/README.md)
- [RFC-0006: Durable workflow segments and continuation handoff](../../rfcs/0006-durable-workflow-segments-and-continuation-handoff.md)
- [State and effect architecture](../../docs/architecture/state-and-effects.md)
- [Bounded asynchronous host I/O](../../docs/runtime/async-host-io.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
