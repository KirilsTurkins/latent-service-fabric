# Data-plane architecture

The delivered data plane is a standalone Linux stateless runtime. Phase 2 adds
current catalog authority, bounded raw and native caches, isolated compilation
and canary observations to the retained Phase 1 activation owner. Its
[completion review](../phase-2-completion.md) records the accepted scope and
bounded currentness/resource evidence. Historical
[Phase 1 evidence](../phase-1-completion.md) and its
[performance extension](../phase-1-extension-completion.md) retain their scope.

## Current invocation path

```text
authenticated loopback invocation RPC
  → pinned local route and execution policy
  → admission controller
  → bounded repository-backed preparation readiness
  → fair scheduler
  → cell assignment and prepared-use materialization
  → final current lifecycle/admission decision
  → context/log/clock binding and fresh Wasmtime store
  → execution and contained cleanup
  → cell release or quarantine, accounting, status and result
```

Release authority is also checked during routing and preparation. Holding a
route, compiler job or readiness object is not acceptance to start. Lifecycle
mutation and the final start decision share a fence; a call already accepted at
that decision may finish. Subsequent decisions reject old capabilities. The
audit worker and rollout coordinator are absent from this path.

## Route and admission ownership

Resolution selects an exact revision from the node's immutable tenant/service
snapshot. The activation pins its route, release and execution policy for its
lifetime. Rollout, promotion and rollback affect new selections by publishing a
new snapshot; they do not rewrite an existing invocation's pin.

Admission occurs before allocating a cell. It checks authenticated identity,
payload bounds, requested trust/cell class, policy, quota, deadline feasibility
and overload state. The scheduler uses bounded class queues, tenant fairness,
admitted priorities, deadlines and aging. Preparation readiness completes before
scheduler enqueue; cold arrivals are not guaranteed FIFO cell eligibility.
Overload never creates a worker or process for a dormant service.

## Materialization and caches

The [runtime](../runtime/wasmtime.md) retains immutable compiled code in a bounded
prepared cache. Verified warm identity lookup can reuse a preparation without
component I/O. Cold reads and preparation run on fixed compiler workers with
finite jobs, input bytes and waiters. Cancellation does not release a running
job's resources until the work actually stops. Readiness owns no cell, guest
store or activation heap.

The implemented storage and execution owners have different authority:

| Owner | Contents and permission |
| --- | --- |
| Authoritative catalog | Immutable original package/component metadata and evidence, plus durable lifecycle. Its sealed current capabilities authorize use. |
| [Raw cache](../reference/raw-artifact-cache.md) | Replaceable digest-addressed manifests/blobs with file pins and verified buffers. A hit grants no trust and cannot evict catalog content. |
| Native cache | Locally authenticated serialized output plus a bounded receipt locator. Exact source, compiler, host and engine checks precede loading. |
| Prepared cache | Linked immutable runtime preparation, with use pins that may outlive eviction. It retains no guest store. |
| Activation | Fresh store, host state, transfer values and execution permits; released or quarantined after actual cleanup. |

The default runtime compiles portable components in process. Opt-in
[native AOT](../runtime/trusted-aot.md) uses a bounded isolated Linux x86_64
compiler and persistent reuse. A persistent hit still performs a fresh verified
catalog source fetch. Receipt authentication precedes the claimed raw-blob read;
exact immutable bytes and actual engine compatibility are authenticated before
the private copying loader. A malformed cache entry can trigger one configured
recompile. Capacity, deadline, cancellation and authority failure do not select
an unrestricted fallback.

Image permits charge page-rounded native mapping bytes before loading and remain
held until the last runtime/readiness owner releases the image. These are logical
mapping limits, not total process RSS or all Wasmtime allocations. Raw-file pins,
output byte leases, mapped image permits and prepared-cache accounting are
separate resources; eviction of one cannot refund another.

Snapshots of guest state, fused derivatives, distributed native-image trust and
cross-node materialization remain future work.

## Capabilities and execution

Declared imports, deployment grants and admitted policy constrain the supported
context, structured log and monotonic/wall clock interfaces. Each activation has
fresh host state. General HTTP, blob, secret, event and service-call providers
remain unavailable until their Phase 3 implementations; a WIT declaration is
not a host implementation. Capsules cannot acquire unrestricted filesystem,
socket, process, environment or thread access.

Execution enforces CPU fuel, monotonic deadline/wall time, aggregate linear
memory and accepted log-byte budgets, plus stack, context, transfer and canonical
value limits. Unsupported budget dimensions must remain zero. Conserved
descendant reservations and cancellation trees accompany Phase 3 local service
calls, rather than being inferred from today's root activation budget. See
[resource budgets](../runtime/resource-budgets.md).

## Observation and reclamation

Bounded telemetry observes activation selection, admission and terminal outcomes.
When configured, canary capture attributes these observations to the selected
compiled generation and revision. A promotion window does not create a timer,
sampler or execution resource for each service. Loss, unattributed work or an
undrained interval cannot become successful evidence.

On success, cancellation, trap, deadline or permanent failure, the activation
owner drives cleanup. Cell reuse requires affirmative backend proof and pool
disposition; uncertain cleanup quarantines the cell. After a transport loss,
one fixed supervisor keeps polling the same owner under its original deadline.
A terminal response alone does not establish safe reuse, and dropping a waiter
does not end underlying compiler, file or child-process work.

## Later execution surfaces

Phase 3 adds one shared application HTTP ingress, external event consumers,
bounded provider I/O and renderer execution profiles. Listeners, provider pools
and consumers belong to shared node owners, never individual dormant services.
Phase 4 adds transactional state and outboxes. Phase 5 adds remote routing and
placement. Phase 6 adds durable workflow timers and continuations. Current
stateless calls return output or typed failure without guest state commits,
outboxes or durable suspension.
