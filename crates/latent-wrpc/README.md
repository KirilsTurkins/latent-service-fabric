# latent-wrpc

Remote-invocation transport contracts for a future node-to-node data plane. Endpoint descriptors, invocation receipts, a client/handler/server seam and a node connection factory keep remote transport separate from application WIT contracts.

This is an interface scaffold. It contains no concrete remote wRPC client/server, cluster router or connection pool, and must not be used as evidence that remote capsule invocation is implemented.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | NodeEndpoint, RemoteInvocationReceipt and remote client/handler/server/connection factory traits. |

## Execution and ownership

1. A future trusted placement/route owner selects a node endpoint and exact invocation identity.
2. A concrete connection factory would authenticate and bound a channel; this crate only defines that port.
3. A concrete remote server would validate authority and pass the invocation into its local lifecycle.
4. Acceptance receipts would retain the original request identity; reconnect/retry and effect uncertainty require an explicit protocol.

## Integration boundaries

`latent-wire` implements standalone RPC adapters, while local service calls use the local node activation manager. Neither is an implementation of this remote abstraction. Cluster freshness, delegation and cancellation must be qualified together before promoting a remote path.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-activation](../latent-activation/README.md), [latent-wire](../latent-wire/README.md).

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-wrpc.lib.latent-wrpc
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Cluster topology](../../docs/architecture/cluster-topology.md)
- [Route freshness: Phase 5 implementation handoff](../../docs/architecture/cluster-freshness-handoff.md)
- [Data-plane architecture](../../docs/architecture/data-plane.md)
- [ADR-0012: Place remote invocation behind a WIT-native transport abstraction](../../adr/0012-place-remote-invocation-behind-a-wit-native-transport-abstraction.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
