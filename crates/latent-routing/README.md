# latent-routing

Immutable local routing and revision-policy contracts. It separates a caller's logical invocation target from the exact revision, release, publication and catalog generation selected by a trusted resolver.

`ActivationCatalogSource::pin` is the important integration seam: resolution and admission-policy lookup must use one pinned catalog generation. The concrete embedded catalog is implemented by `latent-control-store`, not here.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | InvocationTarget, route/binding snapshots, selected revisions and resolver/compiler/publication ports. |
| [src/revision_policy.rs](src/revision_policy.rs) | Trusted revision resource, placement and execution-policy lookup on that same pinned view. |

## Execution and ownership

1. The node pins a catalog view before resolving an invocation target.
2. The resolver selects an exact tenant/service/contract/function/revision/publication association.
3. Admission reads execution and resource constraints from the same view, checking the complete selected tuple.
4. Later live publication and policy checks remain separate from retaining an immutable route snapshot.

## Integration boundaries

Caller-supplied `ResolvedRevision::attributes` cannot supply trusted resource ceilings or placement. A route generation is neither a publication grant nor a replacement for currentness checks. Route compilation opens no guest Store and fetches no component bytes through this interface.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-manifest](../latent-manifest/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-admission](../latent-admission/README.md), [latent-activation](../latent-activation/README.md), [latent-wasmtime](../latent-wasmtime/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-nats](../latent-nats/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-routing.lib.latent-routing
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Control-plane architecture](../../docs/architecture/control-plane.md)
- [Data-plane architecture](../../docs/architecture/data-plane.md)
- [Versioning and deployment](../../docs/architecture/versioning-and-deployment.md)
- [Local publication catalog](../../docs/development/local-release-catalog.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
