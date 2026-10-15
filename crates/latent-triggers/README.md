# latent-triggers

Common trigger event, cursor, registry, source and dispatch interfaces. This small contract layer maps external events to activation requests without coupling every event source to HTTP or a particular message broker.

The file contains interface vocabulary, not a universal trigger engine. Concrete HTTP selection and NATS pull-trigger ownership live in other packages and have their own admission, acknowledgement and cleanup rules.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | TriggerCursor/Event/Dispatch and TriggerRegistry, TriggerSource and TriggerDispatcher ports. |

## Execution and ownership

1. An installed source polls a finite event batch within its source-specific ownership model.
2. A dispatcher maps a checked event to an activation using trusted trigger configuration.
3. The ordinary activation manager admits and executes the request under the appropriate principal and budget.
4. The source acknowledges according to its qualified transport contract; a cursor alone cannot establish durable processing.

## Integration boundaries

Event IDs and idempotency keys are correlation inputs, not a blanket exactly-once promise. Durable broker positions, HTTP route publication and application transaction inboxes have different owners. Adding a source implementation must define finite polling, cancellation, acknowledgement and authority rather than relying on these traits to supply them.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-manifest](../latent-manifest/README.md), [latent-activation](../latent-activation/README.md).

Consumers with normal workspace dependency edges include [latent-ingress](../latent-ingress/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-triggers.lib.latent-triggers
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

## Related documentation

- [Ingress and trigger architecture](../../docs/architecture/ingress-and-triggers.md)
- [Bounded NATS JetStream triggers](../../docs/runtime/nats-triggers.md)
- [State and effect architecture](../../docs/architecture/state-and-effects.md)
- [ADR-0014: Do not promise universal exactly-once external effects](../../adr/0014-do-not-promise-universal-exactly-once-external-effects.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
