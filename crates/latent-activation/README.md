# latent-activation

Invocation requests, validated envelopes, typed outcomes and lifecycle/journal ports. It is the shared contract between ingress, the node and execution services. `ActivationRequestBuilder` supplies concrete bounded request validation and host-assigned identity construction; `ActivationManager` and `ActivationJournal` describe behavior implemented elsewhere.

Activation lineage and trace fields provide correlation. They do not let a caller inherit another activation's principal, grants or accounting ledger.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/request.rs](src/request.rs) | ActivationRequestBuilder, request limits, host ID generation and trusted-context validation. |
| [src/lib.rs](src/lib.rs) | Envelopes, returned/declared/platform outcomes, retained success summaries, status/events and manager/journal traits. |

## Execution and ownership

1. An authenticated adapter supplies trusted principal/context and bounded request data.
2. The builder assigns or validates identity, preserves explicit correlation and discards untrusted pre-resolved route authority.
3. The node resolves, admits and drives the envelope through its lifecycle, producing sequenced status/events.
4. Retained success status keeps summary fields rather than indefinitely retaining the output payload; declared and platform failures remain distinct.

## Integration boundaries

The implementation owner is `latent-node`; admission and backend execution remain separate crates. Journal reads are trusted local ports whose external adapter must enforce tenant access. An idempotency key in an invocation envelope is not durable deduplication or permission to replay an uncertain effect.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-routing](../latent-routing/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent](../../apps/latent/README.md), [latent-scheduler](../latent-scheduler/README.md), [latent-executor](../latent-executor/README.md), [latent-wasmtime](../latent-wasmtime/README.md), [latent-capabilities](../latent-capabilities/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-activation.lib.latent-activation
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`retained_success_keeps_every_advertised_status_field`](src/lib.rs)
- [`only_node_selected_profile_accepts_phase3_counters_and_lineage_is_still_correlation`](src/request/tests.rs)
- [`missing_identity_is_assigned_once_and_root_uses_that_identity`](src/request/tests.rs)
- [`explicit_correlation_and_trusted_context_are_preserved_without_ancestry_lookup`](src/request/tests.rs)

## Related documentation

- [Activation lifecycle protocol](../../docs/protocol/activation-lifecycle.md)
- [Isolated local service invocation](../../docs/runtime/local-service-invocation.md)
- [Budgets and cancellation trees](../../docs/runtime/descendant-budgets.md)
- [Platform error model](../../docs/protocol/platform-errors.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
