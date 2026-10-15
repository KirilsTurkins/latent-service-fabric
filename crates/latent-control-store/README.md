# latent-control-store

Embedded deployment/control catalog with immutable route publication. `DirectoryDeploymentRepository` persists desired deployment/binding/HTTP-trigger/rollout state and compiles tenant-scoped execution indexes. A pinned resolver serves a coherent generation while newer catalog mutations publish another view.

It is a local standalone catalog, not a replicated cluster control plane. The catalog alone commits route/progress transitions; rollout workers and RPC adapters wrap that owner rather than replacing it.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Store ports and concrete directory catalog/resolver exports. |
| [src/deployments/mod.rs](src/deployments/mod.rs) | DirectoryDeploymentRepository construction, mutation and pinned route ownership. |
| [src/deployments/compiler/](src/deployments/compiler/) | Bounded immutable execution, policy, binding and inspection indexes. |
| [src/deployments/persistence/](src/deployments/persistence/) | Canonical persisted envelopes, checksums and recovery. |
| [src/deployment_operations.rs](src/deployment_operations.rs) | Managed apply/delete identities and historical receipts. |
| [src/http_routes.rs](src/http_routes.rs) | Exact HTTP trigger targets and bounded control preconditions. |
| [src/rollouts.rs](src/rollouts.rs) | Durable rollout/canary/rollback semantics. |
| [src/scoped_routes.rs](src/scoped_routes.rs) | Bounded complete tenant projections and scoped integrity. |

## Execution and ownership

1. Open a bounded repository with current artifact lifecycle, broker and trusted runtime/policy inputs.
2. Validate desired-state documents and exact package/publication/binding associations.
3. Compile and persist a coherent next catalog view, then publish immutable indexes under the catalog fence.
4. Invocations pin a view for route and admission-policy resolution, but still use live release/provider/policy acceptance.
5. Management reads and operation replay preserve tenant scope, exact preconditions and historical identity without reviving old authority.

## Integration boundaries

Data-only binding plans are not fused code. Permanently inactive desired rows must not acquire execution capability. HTTP, static web and transaction selections use the same catalog publication owner with different target semantics. `catalog-observation` is optional bounded instrumentation; observations are not allocator/RSS qualification or authorization evidence.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-ingress](../latent-ingress/README.md), [latent-manifest](../latent-manifest/README.md), [latent-routing](../latent-routing/README.md), [latent-node](../latent-node/README.md), [latent-state](../latent-state/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-policy](../latent-policy/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-audit](../latent-audit/README.md), [latent-contracts](../latent-contracts/README.md), [latent-packaging](../latent-packaging/README.md), [latent-telemetry](../latent-telemetry/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent](../../apps/latent/README.md), [latent-wire](../latent-wire/README.md), [latent-rollout](../latent-rollout/README.md), [latent-optimization-bench](../../tools/optimization-bench/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `default` | No additional feature dependency. |
| `catalog-observation` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-control-store.lib.latent-control-store
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`denied_immediate_http_requires_scoped_state_and_cannot_replace_ordinary_bindings`](src/deployments/bindings/compile.rs)
- [`installed_graph_distinguishes_tenants_and_rejects_cross_tenant_cycles`](src/deployments/bindings/compile/invocation.rs)
- [`graph_checks_auto_local_edges_and_rejects_cycle_depth_and_bounded_work`](src/deployments/bindings/compile/tests.rs)
- [`context_only_web_projection_cannot_acquire_provider_grants`](src/deployments/bindings/compile/web.rs)

## Related documentation

- [Control-plane architecture](../../docs/architecture/control-plane.md)
- [Versioning and deployment](../../docs/architecture/versioning-and-deployment.md)
- [Local publication catalog](../../docs/development/local-release-catalog.md)
- [Immutable target inspection](../../docs/reference/target-inspection.md)
- [Scoped HTTP trigger routes](../../docs/reference/http-triggers.md)
- [Standalone management services](../../docs/reference/management-services.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
