# Ephemeral entity lane integration

`latent_state::entity_lanes` provides bounded local execution eligibility for
[issue #394](https://github.com/KirilsTurkins/latent-service-fabric/issues/394).
The owner table contains accepted queues and physical execution/cleanup owners.
It starts empty after restart and removes a key when both its queue and physical
owner retire. It creates no entity tasks, workers, guest cells, heaps or timers.
Durable state, command outcomes and protective history belong to the shared store.

## Host handoff

1. Derive `EntityScope` from trusted tenant, namespace incarnation and entity
   binding authority. Its constructor checks shape; it does not grant permission.
2. Durably claim the canonical caller-scoped command attempt before queueing.
   `EntityLaneRequest<T>` carries its opaque bounded identity and the original
   immutable accepted envelope `T`, including publication/schema pin. Local
   duplicate suppression covers a live lane only; durable recovery is separate.
3. Charge payload ownership before constructing the request. Configure explicit
   global/tenant/entity queue and retained-byte limits, global/tenant key and
   active-owner limits, scope/identity ceilings and maximum monotonic wait age.
   Configure hot-key queue capacity below shared queue capacity to leave admission
   headroom for independent keys. Backpressure returns the original request.
4. Keep the original `EntityWaiter` while queued. Its drop removes queued work;
   explicit cancellation returns the request for durable disposition. Dropping
   an active waiter detaches it. Explicit active cancellation signals the owner.
5. Drive `try_start_next` from the shared scheduler before leasing a guest cell.
   Each eligible key has one round-robin position, regardless of backlog.
   Cleanup counts against active capacity. Recheck current namespace/publication
   authority through the supplied callback; rejected/expired dispatch returns the
   original request without a guest execution. The node must continue driving
   pending queues so wait deadlines are observed; there is no per-entity timer.
6. Transfer `EntityExecution::into_owned_work()` into the real execution owner.
   The returned `EntityLaneRequest<T>` and `EntityPhysicalOwner<T>` preserve the
   accepted envelope. Every independently owned engine/commit/cleanup operation
   must retain a physical guard before submission. Client cancellation and
   deadlines cannot retire it. Only the last guard's destruction frees the lane.
7. Seal transaction staging and sever guest references before handing owned bytes
   and the physical guard to commit/recovery. Check the local `EntityLaneFence`
   and atomically enforce current namespace/incarnation/publication, command
   attempt and cancellation authority inside the shared store's final fence.
   A local fence check by itself does not establish atomic store authorization.
   Preserve committed disposition after irreversible commitment; retain the lane
   through actual cleanup. Durable outbox dispatch then owns independent work.

Namespace revocation removes queued reservations and invalidates/cancels live
owners without freeing them. Old incarnation, retired generation and foreign
manager fences reject. The lane owner keeps no dormant revocation table, so new
admission must still use current trusted authority. Synchronous transactional
children reject for the same or different entity, avoiding reentrant/cyclic
waits. Existing nontransactional descendant behavior is unchanged.

## Focused validation and remaining integration

The portable library tests cover serialization, unchanged publication pins,
distinct-key progress, round-robin scheduling, tenant active limits, queue/key/byte
caps, actual queued payload destruction, deadline/wall-clock separation, paused
physical buffer/guard retention, cleanup accounting, concurrent live duplicates,
revocation during queued authorization, incarnation/generation/restart fencing,
nested-call rejection and cold-key churn back to zero live lane metadata.
Readiness uses the shared `Rendezvous`/`PollProbe`, and retirement checks the
actual weak buffer reference and owner accounting. These cases are registered in
the existing `latent-state` libtest suite.

```sh
cargo test -p latent-state --lib --locked
cargo clippy -p latent-state --all-targets --all-features --locked -- -D warnings -A clippy::elidable_lifetime_names
```

The Clippy allowance applies to pre-existing explicit lifetimes on placeholder
traits; the new lane modules deny Clippy all/pedantic lints. This substrate does
not complete #394. The standalone invocation contract and trusted entity binding,
durable command admission/result recovery, actual scheduler/cell/guest path,
atomic namespace/store commit fence and real-component trap/commit/cleanup
integration remain required by #382/#384/#387/#388 and #394. No Linux durability,
real guest execution or final Phase 4 qualification is claimed by these portable
owner tests. The unsafe wall-clock-only legacy `EntityLeaseManager` declaration
is not implemented or adopted as the execution authority.
