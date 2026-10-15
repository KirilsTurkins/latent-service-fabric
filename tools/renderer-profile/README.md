# latent-renderer-profile

Finite operator-controlled Wasmtime qualification host for the closed Angular renderer fixture. It compiles the supplied fixture once, creates fresh bounded Stores for individual probes, checks hydration/fresh state and adversarial interruption/cleanup, then writes a hydration fixture and compact JSON report.

It is separate from `latentd`, publication admission and the authenticated native loader. The compilation caller must supply its own outer process/resource boundary.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/main.rs](src/main.rs) | Selected fixture loading, render/probe checks, hydration output and report. |
| [src/ownership.rs](src/ownership.rs) | Store/resource limits, epoch ticker and actual live-Store ownership observations. |

## Execution and ownership

1. An explicit operator runner selects the fixture and bounds the host process.
2. Compile once and instantiate with an empty linker, proving that this fixture has no ambient host imports.
3. Run fresh Stores for render and adversarial fuel/epoch/memory cases; inspect actual Store release after each.
4. Emit finite fixture/report artifacts, leaving real-node application ingress and signed admission qualification to their own campaigns.

## Integration boundaries

Probe success establishes this closed fixture boundary only. It does not qualify arbitrary JavaScript, build commands, persistent guest reuse, native deserialization or real HTTP delivery. The runtime renderer adapter is a different package and uses the generic production backend.

## Dependencies and build

Direct workspace dependencies: [latent-core](../../crates/latent-core/README.md).

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/main.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-renderer-profile.bin.latent-renderer-profile
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Bounded Angular renderer qualification](../../examples/renderer-profile/README.md)
- [Angular renderer execution profile](../../docs/runtime/angular-renderer-profile.md)
- [Angular in generic execution cells](../../docs/runtime/angular-renderer-runtime.md)
- [Angular build implementation and validation](../../docs/development/angular-build-evidence.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)
