# Budgets and cancellation trees

Issue [#208](https://github.com/KirilsTurkins/latent-service-fabric/issues/208)
adds explicit Phase 3 accounting to RPC validation, request normalization,
admission, the original activation ledger and managed Wasmtime execution.
The default remains the [Phase 1 profile](resource-budgets.md). This accounting
foundation does not install providers or authorize a guest to call a service.
The local invocation adapter is delivered separately by
[#209](https://github.com/KirilsTurkins/latent-service-fabric/issues/209).

## Configuration and enforcement

The optional `budgetProfile` member of standalone node configuration selects
one profile before startup. Its [schema](../../schemas/node-budget-profile.schema.json)
defines the closed set of fields. For example:

```json
{
  "mode": "phase3",
  "maximumChildCalls": 16,
  "maximumOutboundRequests": 8,
  "maximumBlobReadBytes": 1048576,
  "maximumBlobWriteBytes": 1048576,
  "maximumDepth": 8,
  "maximumLiveDescendants": 64,
  "maximumLiveChildren": 8
}
```

Omission or `{"mode":"phase1"}` preserves existing behavior. In Phase 3, omitted
counter ceilings are zero; choosing the profile alone grants no additional
capacity. Limits are node ceilings, intersected with the request, deployment and
execution policy. Each operation also requires its own capability authorization.
Request metadata cannot select a profile. Unmanaged executor calls still use the
Phase 1 profile; managed execution must carry the exact admitted ledger.

| Dimension | Phase 3 contract |
| --- | --- |
| CPU fuel, log bytes | Additive across the activation and descendants. |
| Child calls | One for each accepted child, plus that child's accepted descendants. Rejected admission spends none. |
| Outbound requests | Additive accepted provider operations, using the original ledger's reservation ownership. |
| Blob read/write bytes | Additive independently metered byte counters. |
| Memory | The parent's own observed peak plus full simultaneous child memory reservations must fit the parent grant. Actual observed child peaks propagate to aggregate telemetry. |
| Wall time | An absolute monotonic deadline. A child may shorten it and cannot extend or reanchor it. |
| State bytes, effects | Nonzero requests and consumption remain unsupported. |

Depth defaults to 8 and is capped at 16; the root has depth zero. Global live
descendant frames default to 64 and are capped at 256. Live children per parent
default to 8 and are capped at 32, and cannot exceed the global limit. These
counts include reservations awaiting admission and retired ancestor frames still
retained by live descendants. They are separate from node admission and fixed
cell capacity. No root owns a background task.

## Sealed delegation and retirement

`ActivationBudget::delegate_at` reserves against the original parent ledger
before normal child admission. It intersects requested capacity with parent
remaining capacity, deployment and node ceilings, reserving the child's grant
and one additional child-call counter atomically per cumulative reservation.
Concurrent reservations cannot exceed the original grant. Memory is reserved
before a delegation can be returned. A failed preparation refunds its reservations.

The affine `ChildBudgetDelegation` is the authority to accept that reservation.
Copying its descriptive grant does not create another delegation. `accept` may
only narrow the reserved grant and its original deadline; it produces one
`ChildBudgetOwner` with the original child ledger. Root/parent activation IDs
remain correlation fields and cannot reconstruct this ownership.

Accepted execution and every retained child/provider/result owner must hold the
same child ledger until their resources are reclaimed. The last ledger reference
retires the original parent reservation once. An accepted child consumes one call
even when its execution fails. Valid completion settles actual additive usage;
unfinalized or invalid completion consumes the full accepted grant conservatively.
An accepted grant narrowed by admission retains the larger preparation reservation
until retirement. This is conservative headroom, not extra execution permission.

Parent finalization closes delegation, publishes a conservative frozen report
including occupied reservations, and wakes descendants. It does not refund live
work. Later owners can settle or refund their reservations as housekeeping,
without changing that terminal report or permitting new work. A grandchild keeps
its intermediate parent's accounting frame charged until the grandchild retires.
The ancestry retains bounded ledgers and cancellation signals; it does not retain
guest Stores, cells, payloads or bearer credentials.

Memory reservations retire only with the actual child ledger owner. Confirmed
memory observations propagate from child to ancestor under locks in that one
direction. Historical aggregate peaks remain recorded after memory is released.
The accounting covers its specified guest and provider charges, not total process
RSS or every embedder allocation.

## Cancellation and waiting

Each admitted Phase 3 root is linked to its actual node cancellation and transport
owner. Each accepted child supplies its own owner signal and inherits its sealed
ancestry. `descendant_is_cancelled` checks the bounded chain;
`descendant_cancelled` waits on at most 17 signals without spawning a task.
Parent cancellation, disconnect or finalization wakes linked waiters. New
delegation after terminal state is rejected. No detached durable child mode or
credential forwarding is introduced.

Trusted implementations of `BudgetCancellationProbe` must provide prompt
cancellation notifications and a distinct terminal signal for each accepted
ledger. The probe must never retain its own budget or descendants, which would
create a cycle. Finalization notifies the probe after releasing the accounting
lock. Wait futures belong to their callers; dropping a wait does not release a
child ledger retained by running work.

The [asynchronous ownership decision](../../adr/0028-retain-activation-ownership-across-asynchronous-waits.md)
still applies: a waiting parent keeps its cell, Store, admission permit and actual
resource charges. The local-call adapter must ensure progress or prompt rejection
when fixed cells are occupied. Creating a budget delegation does not itself
provide an execution cell or authorize starting a child.

Wasmtime reports its own guest fuel and memory separately from settled descendant
usage; host/provider counters are authoritative on the shared ledger. An adapter
that resumes a parent after a child must checkpoint native fuel before delegation
and adjust the fuel watermark on resumption so child usage cannot be spent again
or counted as the parent's own instructions. The delivered
[local service adapter](local-service-invocation.md) implements this boundary.
Pending Phase 3 guest memory growth reserves aggregate capacity before allocation;
confirmation records the peak, while failed growth refunds only its pending claim.

## Validation

Normal Rust tests cover explicit profile selection and zero ceilings, unsupported
state/effects, simultaneous delegation, exactly-once retirement, invalid completion,
partial usage, retained grandchildren, aggregate memory, finite tree saturation,
absolute-deadline regression, and cancellation/finalization races. Node tests use
the actual cancellation, transport and terminal signals while a provider retains
the child ledger. Request, admission, RPC and Wasmtime accounting tests verify the
profile across each boundary. None requires a 100,000-invocation load run.
