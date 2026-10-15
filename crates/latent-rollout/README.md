# latent-rollout

Bounded node control coordinator for durable manual rollout operations, canary review and rollback. It adds finite control admission, response ownership and audit around the deployment catalog. Invocation does not consult this worker or its queue.

The catalog owns committed routes and progress. A canary diagnostic report or historical rollout receipt cannot independently authorize promotion or revive denied content.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/coordinator.rs](src/coordinator.rs) | RolloutCoordinator, shared handle and explicitly driven worker. |
| [src/limits.rs](src/limits.rs) | Independent control admission and response-owner bounds. |
| [src/ticket.rs](src/ticket.rs) | Accepted control ticket and original operation identity. |
| [src/lease.rs](src/lease.rs) | Owned response/encoding reservations retained through final transport frames. |
| [src/canary.rs](src/canary.rs) | Bounded cohort observation and promotion integration. |
| [src/rollback.rs](src/rollback.rs) | Explicit rollback preview with current source eligibility. |
| [src/deployment_audit.rs](src/deployment_audit.rs) | Inline deployment auditing without an extra coordinator worker. |
| [src/trigger_audit.rs](src/trigger_audit.rs) | Inline trigger auditing on the existing owner. |

## Execution and ownership

1. Authenticate and preflight the exact manual operation, preconditions and response capacity.
2. Reserve required audit/control ownership before accepting the mutation.
3. Ask the original deployment catalog to commit the route/progress transition; seal canary evidence only through the configured telemetry owner where required.
4. Return a bounded historical receipt while retaining response/audit work through physical completion, and reconcile uncertain audit separately from durable mutation outcome.

## Integration boundaries

Rollback is an explicit operator action, not automatic replay or permission to use revoked content. Audit bookkeeping contention can wait only before accepted work and within the original deadline; an accepted write is not retried. Dropping a response waiter does not cancel a committed catalog transition.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-control-store](../latent-control-store/README.md), [latent-audit](../latent-audit/README.md), [latent-artifacts](../latent-artifacts/README.md), [latent-telemetry](../latent-telemetry/README.md), [latent-manifest](../latent-manifest/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-wire](../latent-wire/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-rollout.lib.latent-rollout
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`brief_bookkeeping_contention_does_not_fail_startup`](src/audit/pending.rs)
- [`capacity_and_other_audit_errors_are_not_retried`](src/audit/pending.rs)
- [`original_deadline_bounds_contention_and_prevents_expired_reads`](src/audit/pending.rs)
- [`enqueue_retries_stop_once_an_owned_ticket_or_uncertain_error_exists`](src/audit/pending.rs)

## Related documentation

- [Control-plane architecture](../../docs/architecture/control-plane.md)
- [Versioning and deployment](../../docs/architecture/versioning-and-deployment.md)
- [Standalone management services](../../docs/reference/management-services.md)
- [Release lifecycle and evidence renewal](../../docs/reference/release-lifecycle.md)
- [Durable single-node rollouts](../../docs/phase-2-rollouts.md)
- [Controlled canary promotion](../../docs/phase-2-canary-promotion.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
