# latentd

Standalone node composition root and product command entry point. It validates explicit versioned configuration, constructs fixed shared runtime/control/provider resources and exposes the selected RPC/HTTP listeners. Dormant deployments add metadata/code, not an application-owned process, heap, thread or listener.

Development also contains opt-in protected transaction storage, deferred dispatch and native recovery composition. Those paths have explicit installation/readiness and acceptance requirements and are outside the published alpha.5 toolkit; their presence is not blanket completion of Phase 4.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/main.rs](src/main.rs) | Binary entry into product command dispatch. |
| [src/command.rs](src/command.rs) | check-config, serve and bounded transaction/effect inspection commands. |
| [src/config.rs](src/config.rs) | Strict bounded versioned config validation before opening node resources. |
| [src/standalone.rs](src/standalone.rs) | Shared standalone composition and ownership exports. |
| [src/standalone/start/](src/standalone/start/) | Startup order, listener publication and offline composition. |
| [src/standalone/providers/](src/standalone/providers/) | Explicit provider installation and scalar host capability registration. |
| [src/standalone/state/mod.rs](src/standalone/state/mod.rs) | Canonical protected state startup, validation and transaction owners. |
| [src/standalone/effects.rs](src/standalone/effects.rs) | Deferred dispatcher on the same protected database and original clock/capacity owners. |
| [src/standalone/http.rs](src/standalone/http.rs) | One shared bounded application listener; sibling static-asset and renderer selection. |
| [src/standalone/transport.rs](src/standalone/transport.rs) | Transport admission and cleanup independent of activation quota. |

## Execution and ownership

1. Read explicit protected configuration and validate actual platform, compiler/profile, resource and credential prerequisites.
2. Construct shared clock/audit/storage/policy/catalog/provider/backend/scheduler owners in dependency order; fail readiness if a selected installation is incomplete.
3. Publish bounded listeners only after required owners are ready. Each request enters the normal authenticated adapter and activation or transaction lifecycle.
4. During shutdown stop new admission, drain accepted transports/activations/providers/control/dispatch/storage and retain unresolved owners instead of claiming early reclamation.

The standalone inventory precharges 38 topology row slots: the fixed node,
activation and architectural service groups plus the bounded catalog, HTTP,
policy, rollout and canary groups. These group lengths also type-check the
source arrays. The snapshot byte cap remains 256 KiB; a shorter selection still
reports an incomplete topology rather than dropping rows as a complete result.
The generic inventory default remains 32 slots.

## Integration boundaries

`check-config` is preflight rather than serve; inspection does not silently bootstrap a node. Product execution/security qualification is Linux x86-64. `development-test-node` and `development-outbound-streams` are explicit fixture/qualification features. Measurement collectors are separately invoked tooling, never ordinary workload startup. Standalone composition does not implement clustered control or remote invocation.

Startup failure reports retain up to 32 observations with fixed stage and owner
codes. Treat `protectedStoreStartup` as the state-kernel boundary; use nested
initializer, mode-marker, clock-binding and readiness stages to locate the
refusal. Typed initializer errors remain visible alongside the original returned
platform error, with the same startup deadline and physical cleanup.

## Dependencies and build

Direct workspace dependencies: [latent-activation](../../crates/latent-activation/README.md), [latent-admission](../../crates/latent-admission/README.md), [latent-artifacts](../../crates/latent-artifacts/README.md), [latent-audit](../../crates/latent-audit/README.md), [latent-blobs](../../crates/latent-blobs/README.md), [latent-control-store](../../crates/latent-control-store/README.md), [latent-core](../../crates/latent-core/README.md), [latent-capabilities](../../crates/latent-capabilities/README.md), [latent-commit](../../crates/latent-commit/README.md), [latent-executor](../../crates/latent-executor/README.md), [latent-effects](../../crates/latent-effects/README.md), [latent-ingress](../../crates/latent-ingress/README.md), [latent-http](../../crates/latent-http/README.md), [latent-manifest](../../crates/latent-manifest/README.md), [latent-nats](../../crates/latent-nats/README.md), [latent-node](../../crates/latent-node/README.md), [latent-protected-files](../../crates/latent-protected-files/README.md), [latent-policy](../../crates/latent-policy/README.md), [latent-routing](../../crates/latent-routing/README.md), [latent-rollout](../../crates/latent-rollout/README.md), [latent-rpc](../../crates/latent-rpc/README.md), [latent-scheduler](../../crates/latent-scheduler/README.md), [latent-secrets](../../crates/latent-secrets/README.md), [latent-state](../../crates/latent-state/README.md), [latent-streams](../../crates/latent-streams/README.md), [latent-telemetry](../../crates/latent-telemetry/README.md), [latent-wasmtime](../../crates/latent-wasmtime/README.md), [latent-wire](../../crates/latent-wire/README.md).

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `development-test-node` | `latent-wasmtime/development-clock-fixture` |
| `development-outbound-streams` | `latent-streams/development-outbound` |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/main.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latentd.lib.latentd
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`check_config_requires_an_explicit_file_and_never_selects_serve`](src/command/tests.rs)
- [`serve_requires_configuration_and_help_advertises_only_product_surfaces`](src/command/tests.rs)
- [`status_encoding_is_one_bounded_json_line`](src/command/tests.rs)
- [`obsolete_catalog_migration_command_is_rejected`](src/command/tests.rs)

Integration targets: [tests/catalog_scale.rs](tests/catalog_scale.rs), [tests/phase3_angular_fixture.rs](tests/phase3_angular_fixture.rs), [tests/phase3_reference_fixture.rs](tests/phase3_reference_fixture.rs), [tests/phase3_static_fixture.rs](tests/phase3_static_fixture.rs), [tests/phase3_workflow_fixture.rs](tests/phase3_workflow_fixture.rs), [tests/standalone_command.rs](tests/standalone_command.rs), [tests/standalone_node.rs](tests/standalone_node.rs), [tests/standalone_shutdown.rs](tests/standalone_shutdown.rs).

## Related documentation

- [Standalone node](../../docs/reference/standalone-node.md)
- [Configure standalone providers](../../docs/reference/standalone-providers.md)
- [Standalone echo quickstart](../../docs/development/standalone-quickstart.md)
- [Canonical protected state startup](../../docs/development/canonical-state-startup.md)
- [Installed transaction RPCs](../../docs/development/installed-transaction-rpc.md)
- [Run a node in a Linux container](../../docs/operations/container-runtime.md)
- [Execution security profiles](../../docs/runtime/execution-security-profiles.md)
- [Workspace package index](../../crates/README.md)
- [Architecture index](../../ARCHITECTURE.md)
