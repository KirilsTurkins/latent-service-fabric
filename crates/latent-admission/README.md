# latent-admission

Concrete local resource admission before scheduling and execution. `LocalAdmissionController` combines trusted revision policy, node/tenant ceilings, load observations, deadline feasibility and shared quota reservations to issue an owned permit.

Admission reserves capacity; it does not fetch artifacts, compile code, create execution cells or authenticate incoming network requests. Keeping those phases separate prevents rejected work from allocating downstream execution resources.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/controller.rs](src/controller.rs) | Policy intersection and admission decision under the actual quota/deadline acceptance boundary. |
| [src/policy.rs](src/policy.rs) | Node, tenant, cell/trust/queue class, overload and deadline policies. |
| [src/quota.rs](src/quota.rs) | Shared LocalQuotaProvider and instantaneous reserved-capacity observations. |
| [src/permit.rs](src/permit.rs) | Affine AdmissionPermit/ExecutionPermit and transition from queued admission to execution. |
| [src/timing.rs](src/timing.rs) | Deadline feasibility timing used during admission. |

## Execution and ownership

1. Receive authenticated request measurements and a revision selected from a pinned trusted catalog.
2. Intersect caller, capsule, deployment, tenant and node limits under the selected budget profile.
3. Check current load/deadline feasibility and reserve quota atomically, issuing one permit.
4. Move the permit through queueing, execution and cleanup. Release capacity when its real owner retires, including cancelled queued work.

## Integration boundaries

All catalog generations must share the same quota owner; replacing a route snapshot must not reset active capacity. `QuotaSnapshot` reports live reservations, including queued work, rather than billing or a replenishing fuel bucket. Metadata claimed by a request cannot choose its own trusted ceiling or load observation.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-routing](../latent-routing/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-scheduler](../latent-scheduler/README.md), [latent-wire](../latent-wire/README.md), [latent-node](../latent-node/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-admission.lib.latent-admission
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`injected_feasibility_clock_is_read_while_the_actual_quota_mutex_is_held`](src/quota/clock_tests.rs)
- [`phase3_admission_intersects_every_ceiling_without_enabling_state_or_effects`](src/tests.rs)
- [`valid_admission_pins_identity_grants_smallest_cell_and_owns_quota`](src/tests.rs)
- [`budget_intersection_includes_capsule_deployment_node_and_caller`](src/tests.rs)

## Related documentation

- [Execution-cell architecture](../../docs/architecture/execution-cells.md)
- [Resource budgets, deadlines, and cancellation](../../docs/runtime/resource-budgets.md)
- [Phase 0 activation containment](../../docs/development/activation-containment.md)
- [Native admission and recovery capacity](../../docs/development/native-admission-capacity.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
