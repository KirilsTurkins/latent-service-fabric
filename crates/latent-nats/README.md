# latent-nats

Shared bounded TLS JetStream publication, explicit pull triggers and a qualified deferred event adapter. Topic mappings and endpoints are configured by the operator; protocol parsing and receipts use a restricted finite NATS profile.

Immediate event publication is not an application transaction. Durable deferred delivery requires the separate outbox/authority contract and an explicitly qualified duplicate window.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/config.rs](src/config.rs) | NatsConfig, endpoint and exact topic mappings. |
| [src/provider.rs](src/provider.rs) | NatsPublisher and finite shared pool observations. |
| [src/network.rs](src/network.rs) | Pooled actual socket owner without a separately spawned protocol driver. |
| [src/protocol.rs](src/protocol.rs) | Bounded frames and checked JetStream publish receipts. |
| [src/request.rs](src/request.rs) | Actual request length/capacity checks before retention/encoding. |
| [src/triggers.rs](src/triggers.rs) | Operator-installed pull-trigger configuration and dispatch ownership. |
| [src/deferred.rs](src/deferred.rs) | Committed unordered event dispatch with finite deduplication qualification. |

## Execution and ownership

1. Install explicit TLS credentials/peers, subject mappings and pool/trigger limits.
2. A current broker call or sealed deferred-effect grant authorizes the exact publication.
3. Send bounded frames and validate the exact stream/sequence acknowledgement; uncertainty does not become automatic replay.
4. Pull triggers retain broker consumer positions and normal child activation ownership; shutdown retires accepted socket/trigger work.

## Integration boundaries

No guest can create an endpoint, durable consumer or unlimited subject subscription through a DTO. A JetStream acknowledgement and an LSF command commit are different durability observations. The deferred adapter does not promise ordering or deduplication beyond the qualified stream configuration and horizon.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-effects](../latent-effects/README.md), [latent-activation](../latent-activation/README.md), [latent-node](../latent-node/README.md), [latent-routing](../latent-routing/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-policy](../latent-policy/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-nats.lib.latent-nats
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`retained_endpoint_capacity_cannot_bypass_the_configuration_bound`](src/config.rs)
- [`qualified_stream_rejects_recreation_eviction_retention_transform_and_window_changes`](src/deferred/qualification/tests.rs)
- [`stream_qualification_decoding_is_finite_and_requires_pinned_identity`](src/deferred/qualification/tests.rs)
- [`receipts_require_exact_stream_positive_sequence_and_unambiguous_shapes`](src/protocol/tests.rs)

Integration targets: [tests/deferred_events.rs](tests/deferred_events.rs).

## Related documentation

- [Bounded NATS JetStream publication](../../docs/runtime/nats-events.md)
- [Bounded NATS JetStream triggers](../../docs/runtime/nats-triggers.md)
- [Deferred JetStream delivery](../../docs/development/deferred-jetstream.md)
- [Shared provider pools](../../docs/runtime/provider-pools.md)
- [Ingress and trigger architecture](../../docs/architecture/ingress-and-triggers.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
