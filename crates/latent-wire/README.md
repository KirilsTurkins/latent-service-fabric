# latent-wire

Concrete bounded standalone RPC adapters plus general channel/frame interfaces. The invocation service bridges authenticated requests into the local lifecycle; management services use existing catalogs/inventory; Phase 4 services use the installed transaction/dispatcher/recovery owners.

The root's general FrameKind, DuplexChannel and multiplexer vocabulary is broader than the implemented Tonic path. Those type definitions do not establish a second network protocol or remote cluster invocation.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | General frame, handshake, codec/channel and multiplexing contracts. |
| [src/invocation.rs](src/invocation.rs) | InvocationServiceAdapter, trusted principal context, conversions and local runtime bridge. |
| [src/invocation/cleanup.rs](src/invocation/cleanup.rs) | Bounded accepted activation handoff and cleanup ownership across transport interruption. |
| [src/management.rs](src/management.rs) | Authenticated finite catalog/policy/provider/rollout/inventory services; no listener creation. |
| [src/phase4.rs](src/phase4.rs) | Installed command/query/result/dispatcher/recovery RPC adapters. |
| [tests/invocation_service.rs](tests/invocation_service.rs) | Wire validation and lifecycle adapter integration. |
| [tests/management_service.rs](tests/management_service.rs) | Management identity, bounds, projections and service behavior. |

## Execution and ownership

1. The node listener selects transport identity and authenticates a bounded RPC before domain conversion.
2. The adapter checks tenant/action scope, field presence, lengths and exact request identity.
3. Delegate to the existing node/catalog/transaction owner, retaining original deadline and accepted work rather than allocating another runtime.
4. Bound and associate the response, preserve full-width counters/typed failures, and retire transport/response owners independently of application or durable mutation disposition.

## Integration boundaries

Generated types come from `latent-rpc`; they do not authenticate peers. A disconnected request waiter is not a durable command abort or proof of provider cleanup. Management operation receipts preserve original preconditions and independent audit uncertainty. `latent-wrpc` remains the separate unimplemented node-to-node abstraction.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-activation](../latent-activation/README.md), [latent-node](../latent-node/README.md), [latent-routing](../latent-routing/README.md), [latent-rollout](../latent-rollout/README.md), [latent-rpc](../latent-rpc/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-executor](../latent-executor/README.md), [latent-audit](../latent-audit/README.md), [latent-telemetry](../latent-telemetry/README.md), [latent-control-store](../latent-control-store/README.md), [latent-manifest](../latent-manifest/README.md), [latent-policy](../latent-policy/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-state](../latent-state/README.md), [latent-commit](../latent-commit/README.md), [latent-effects](../latent-effects/README.md), [latent-admission](../latent-admission/README.md), [latent-ingress](../latent-ingress/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent](../../apps/latent/README.md), [latent-wrpc](../latent-wrpc/README.md), [latent-optimization-bench](../../tools/optimization-bench/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-wire.lib.latent-wire
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`transport_cause_is_first_wins_and_visible_before_waiting`](src/invocation/cancellation/tests.rs)
- [`all_registered_waiters_observe_the_same_sticky_cause`](src/invocation/cancellation/tests.rs)
- [`bounded_slots_refund_and_closing_waits_for_reserved_rpc`](src/invocation/cleanup/tests.rs)
- [`reserved_slot_can_handoff_after_close_and_destructs_before_refund`](src/invocation/cleanup/tests.rs)

Integration targets: [tests/invocation_service.rs](tests/invocation_service.rs), [tests/management_service.rs](tests/management_service.rs).

## Related documentation

- [API surface map](../../docs/api-surface.md)
- [Standalone management services](../../docs/reference/management-services.md)
- [Authorized activation inspection](../../docs/reference/activation-inspection.md)
- [Installed transaction RPCs](../../docs/development/installed-transaction-rpc.md)
- [Standalone transport connection deadlines](../../docs/runtime/transport-connection-deadlines.md)
- [Platform error model](../../docs/protocol/platform-errors.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
