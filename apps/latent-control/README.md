# latent-control

Reserved clustered control-plane binary package. Its current `main` is empty: it has no commands, listener, database, worker, authentication flow or runtime behavior.

The implemented standalone control/catalog behavior is composed by `latentd` using `latent-control-store`, `latent-rollout`, `latent-policy` and `latent-wire`. This package must not be presented as a deployable control plane merely because it is a workspace binary.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/main.rs](src/main.rs) | Documented empty entry point for the future clustered control-plane application. |

## Execution and ownership

1. Cargo can build the placeholder binary without bootstrapping resources.
2. Running it returns from the empty main; no control-plane service is started.
3. A future implementation needs explicit cluster authority, persistence, freshness, transport and lifecycle decisions plus conformance before advertising availability.

## Integration boundaries

Keep new standalone management behavior with its current owner instead of duplicating it here. The planned cluster topology and freshness handoff are architectural requirements, not implementation supplied by this binary. There is no package test suite that could establish clustered behavior today.

## Dependencies and build

There are no unconditional workspace dependencies. Target-specific and test/build edges, if present, are declared in the manifest.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/main.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-control.bin.latent-control
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Control-plane architecture](../../docs/architecture/control-plane.md)
- [Cluster topology](../../docs/architecture/cluster-topology.md)
- [Route freshness: Phase 5 implementation handoff](../../docs/architecture/cluster-freshness-handoff.md)
- [Standalone node](../../docs/reference/standalone-node.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)
