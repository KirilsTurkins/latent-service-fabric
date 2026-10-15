# latent-effects

Durable deferred-effect identity, authority, transition and dispatch machinery. Effect intents describe work committed with application state; the installed dispatcher later intersects captured scope with current provider/policy authority before an actual send. A fixed node owner drives bounded work from the shared durable indexes.

This crate does not turn arbitrary external APIs into exactly-once operations. It explicitly preserves unknown/uncertain dispositions and separates provider confirmation, operator review and permission to retry.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Generic effect intent, status, retry-policy and provider/store/dispatcher ports. |
| [src/authority.rs](src/authority.rs) | Sealed current rules, per-attempt grants and original physical/native owners. |
| [src/dispatch.rs](src/dispatch.rs) | Generation-checked durable transition state machine before provider work. |
| [src/dispatch_store.rs](src/dispatch_store.rs) | Closed indexes, original effect management plans and atomic store envelopes. |
| [src/payload.rs](src/payload.rs) | Bounded retained payload codec independent of application state schema. |
| [src/runtime.rs](src/runtime.rs) | DispatcherOwner, fixed driver, adapter ports, control and shutdown. |
| [src/runtime/reconciliation.rs](src/runtime/reconciliation.rs) | Explicit provider lookup with original identity and separate send authority. |
| [src/recovery_close.rs](src/recovery_close.rs) | Reviewed restored-effect abandonment, distinct from provider acknowledgement. |

## Execution and ownership

1. A host-admitted command captures bounded intent under its exact publication, namespace, provider and policy ceiling.
2. `latent-commit` durably publishes the linked outbox/payload/state/result transition in the shared store.
3. The dispatcher claims ready work, persists its generation transition and checks current sealed authority before provider dispatch.
4. The physical adapter retains the original grant, buffers and capacity through real completion; claim expiry alone cannot replace a still-live attempt.
5. Persist known outcomes or retain uncertainty. Lookup, review, abandonment and explicit retry keep original identities and their independent current authorization.

## Integration boundaries

HTTP and JetStream adapters qualify different deduplication/lookup horizons. Immediate capability calls bypass neither transaction restrictions nor effect uncertainty rules. Cancellation cannot undo an accepted remote effect. Restored backlog stays paused for explicit review; historical envelopes never renew credentials, namespace access or dispatch permission.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-state](../latent-state/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-http](../latent-http/README.md), [latent-nats](../latent-nats/README.md), [latent-commit](../latent-commit/README.md), [latent-workflows](../latent-workflows/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-effects.lib.latent-effects
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`original_queued_deadline_narrows_context_and_grant_without_late_reopening`](src/authority/tests.rs)
- [`unretired_provider_context_quarantines_original_global_capacity_after_all_grants_drop`](src/authority/tests.rs)
- [`provider_grant_retains_original_native_capacity_after_context_retirement_and_refuses_replacement`](src/authority/tests.rs)
- [`namespace_close_invalidates_accepted_grants_without_refunding_physical_work`](src/authority/tests.rs)

## Related documentation

- [Durable effect authority implementation](../../docs/development/durable-effect-authority.md)
- [Durable effect transitions](../../docs/development/durable-effect-transitions.md)
- [Durable dispatch storage](../../docs/development/durable-dispatch-storage.md)
- [Dispatcher management contract](../../docs/development/dispatcher-management-contract.md)
- [Finite effect management plans](../../docs/development/effect-management-plans.md)
- [Qualified deferred HTTP delivery](../../docs/development/deferred-http.md)
- [Deferred JetStream delivery](../../docs/development/deferred-jetstream.md)
- [ADR-0014: Do not promise universal exactly-once external effects](../../adr/0014-do-not-promise-universal-exactly-once-external-effects.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
