# latent-capabilities

Concrete activation capability broker and namespace authority integration. `ActivationCapabilityBroker` binds an exact publication/revision and immutable checked import plan to current provider, policy, route and activation owners. Numeric guest resources address finite Store-local tables; they do not carry authority by themselves.

The broker implements bounded call acceptance and accounting. Protocol crates own actual sockets/files and must retain the accepted call through physical work and result lowering.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/broker.rs](src/broker.rs) | Broker owner, authority lock order, session/plan/provider exports and acceptance boundary. |
| [src/broker/plan.rs](src/broker/plan.rs) | CompiledCapabilityPlan: immutable exact identities without a guest instance or live provider connection. |
| [src/broker/session/](src/broker/session/) | Activation-local sessions, resource tables and selected transaction imports. |
| [src/broker/io.rs](src/broker/io.rs) | Affine call, buffer and transfer ownership with bounded producer/consumer streams. |
| [src/broker/pools.rs](src/broker/pools.rs) | Explicit shared node provider resources, queues and actual native ownership. |
| [src/broker/local_service.rs](src/broker/local_service.rs) | Trusted local-call port into the normal child activation lifecycle. |
| [src/namespace/mod.rs](src/namespace/mod.rs) | Current namespace/result authority over existing policy and publication owners. |

## Execution and ownership

1. A trusted catalog compiler binds exact imports to installed providers, policy snapshots and publication dependencies.
2. Each activation gets a fresh session with its original principal, deadline and accounting ledger.
3. Each operation rechecks authority, reserves resources and required audit, then crosses a short acceptance fence before provider I/O.
4. Accepted work, chunks and results retain their original owners until physical retirement. Session close denies new work without refunding still-live resources.

## Integration boundaries

ABI recognition, provider installation and activation permission are three independent requirements. No I/O or await holds an authority fence. Only narrowly classified pre-effect bookkeeping contention may use its bounded wait path; provider/effect uncertainty does not authorize replay. Namespace DTOs and diagnostic inspection never substitute for current sealed authority.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-effects](../latent-effects/README.md), [latent-activation](../latent-activation/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-audit](../latent-audit/README.md), [latent-executor](../latent-executor/README.md), [latent-policy](../latent-policy/README.md), [latent-state](../latent-state/README.md), [latent-routing](../latent-routing/README.md), [latent-telemetry](../latent-telemetry/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-wasmtime](../latent-wasmtime/README.md), [latent-secrets](../latent-secrets/README.md), [latent-http](../latent-http/README.md), [latent-streams](../latent-streams/README.md), [latent-nats](../latent-nats/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `test-support` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-capabilities.lib.latent-capabilities
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`only_the_exact_busy_constructor_can_wait`](src/broker/clock/window/tests.rs)
- [`one_checked_window_never_extends_the_original_deadline`](src/broker/clock/window/tests.rs)
- [`only_exact_authority_bookkeeping_contention_is_waitable`](src/broker/currentness.rs)
- [`partial_consumers_retain_capacity_and_original_activation_after_close`](src/broker/io/tests.rs)

## Related documentation

- [Sealed activation capability broker](../../docs/runtime/capability-broker.md)
- [Exact capability bindings](../../docs/runtime/capability-bindings.md)
- [Durable capability policies](../../docs/runtime/capability-policies.md)
- [Shared provider pools](../../docs/runtime/provider-pools.md)
- [Capability audit and inspection](../../docs/runtime/capability-audit.md)
- [Namespace persistence and current authority](../../docs/development/namespace-authority.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
