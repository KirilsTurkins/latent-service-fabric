# latent-audit

Immutable administrative/security audit facts with a concrete bounded local durable journal. Typed records cover release, deployment, policy, rollout, dispatcher and capability decisions. Accepted append/query tickets retain their actual worker and response ownership.

Audit records describe original decisions; they cannot grant execution, refresh policy or reconstruct a provider call. Their durability and uncertainty must remain independent of the business/catalog transition they observe.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Shared actor/outcome vocabulary and durable/Phase 2 exports. |
| [src/durable.rs](src/durable.rs) | Closed durable journal API and typed error categories. |
| [src/durable/model/](src/durable/model/) | Redacted bounded event models, including capability and dispatcher facts. |
| [src/durable/store.rs](src/durable/store.rs) | Local persistent journal representation and bounded storage. |
| [src/durable/worker.rs](src/durable/worker.rs) | Explicit worker/handle ownership and append/query dispatch. |
| [src/durable/ticket.rs](src/durable/ticket.rs) | Accepted begin/append/query ticket lifetimes. |
| [src/phase2.rs](src/phase2.rs) | Typed management operation/audit associations. |

## Execution and ownership

1. A trusted operation owner creates a typed redacted record from accepted authority and exact identities.
2. When required, reserve audit capacity before starting the protected operation; exhausted audit admission rejects new work.
3. Persist through the single bounded journal worker and retain accepted work after caller cancellation until actual completion.
4. Return exact acknowledgement or uncertainty. Reconciliation uses original operation/audit identities without repeating the protected effect.

## Integration boundaries

This is separate from best-effort telemetry. Required audit failure cannot be silently downgraded to a log line. A durable command/catalog result may remain known even when its audit acknowledgement is uncertain. `test-support` supplies controlled journal fixtures rather than production authority.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-wasmtime](../latent-wasmtime/README.md), [latent-capabilities](../latent-capabilities/README.md), [latent-wire](../latent-wire/README.md), [latent-control-store](../latent-control-store/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Cargo features (the manifest owns their exact expansion):

| Feature | Enables |
| --- | --- |
| `test-support` | No additional feature dependency. |

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-audit.lib.latent-audit
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`dispatcher_audit_preserves_node_actor_epoch_and_original_full_width_revision`](src/durable/model.rs)
- [`dispatcher_audit_rejects_tenant_scope_hybrids_unrelated_action_and_explicit_null`](src/durable/model.rs)
- [`absent_rollout_fields_preserve_old_canonical_identity_bytes`](src/durable/model.rs)
- [`canary_evidence_fields_require_exact_rollout_and_positive_epoch`](src/durable/model.rs)

## Related documentation

- [Capability audit and inspection](../../docs/runtime/capability-audit.md)
- [Standalone management services](../../docs/reference/management-services.md)
- [Release lifecycle and evidence renewal](../../docs/reference/release-lifecycle.md)
- [Dispatcher management contract](../../docs/development/dispatcher-management-contract.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
