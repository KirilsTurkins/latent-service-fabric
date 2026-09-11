# Bounded single-node fair scheduling

`latent-scheduler::LocalScheduler` implements Phase 1 #8 above the existing
fixed execution-cell pool. It consumes an affine admission permit, selects
queued work fairly, and returns one execution-owned cell and quota reservation.
It creates no dispatcher task, worker thread, runtime, listener, or per-service
queue. Enqueue futures cooperatively dispatch on the caller's async runtime.

Live entries use bounded reusable slots and linked tenant queues. Cancellation
looks up the activation's live registration and unlinks its exact slot without
scanning or shifting unrelated queue entries; sequence checks protect reused
slots. Final cancellation owners are dropped outside the scheduler mutex.
Selection within the chosen tenant still scans its live candidates to apply
priority, deadline and aging rules. Slot storage retains its bounded high-water
capacity for reuse.

This Rust API is composed by the [activation lifecycle](activation-lifecycle.md)
and [standalone node](reference/standalone-node.md) with generic Wasmtime
dispatch. The retained Phase 0 execution path continues to provide its separate
echo/containment regression coverage.

## Construction and resource topology

Construct the scheduler with
`LocalScheduler::new(config, node_quotas.clone())`, sharing the exact
`LocalQuotaProvider` used by admission. A permit from an independently created
ledger is rejected even if that ledger has identical policy. Class, tenant,
priority, trust requirements, granted budget, and original deadline come from
the immutable permit; callers do not resubmit a second mutable scheduling policy.

| Configuration | Meaning |
| --- | --- |
| `LocalSchedulerConfig::node` | Bounded node identity, checked against returned pool leases. |
| `queue_capacity_per_class` | One exact finite queue bound for every configured admission cell class. Missing or extra classes are invalid. |
| `starvation_after` | Positive monotonic waiting duration after which older requests precede newer high-priority work within their tenant's turn. |
| Admission `cell_classes[*].parallelism` | Fixed capacity used to construct each class's `FixedCellPool`. |

The supported class names are `tiny`, `small`, `standard`, `large`, and
`extra-large`. Admission selects the smallest permitted compatible class;
extra-large still requires its explicit admission policy authorization. The
scheduler does not borrow capacity from another class or inflate a class after
quarantine.

Each class has one scheduler-owned bounded queue, containing only tenants with
queued work. Its underlying fixed pool is constructed with its legacy FIFO
queue disabled. Admission queue/concurrency/CPU/memory/trust limits remain
independent bounds in the same ledger. A scheduler queue capacity of zero denies
the class, including requests that could otherwise acquire a cell immediately.

`LocalScheduler::with_pools` accepts external node-owned `CellPool`
implementations. Startup validates the exact class set, configured capacities,
initially available/empty/unquarantined state, and change-notification support.
The external implementation must exclusively serve this scheduler and honor
nonqueueing acquisition, node identity, budget/lease identity, bounded wakeups,
and issuer-owned cleanup. Startup observations cannot prove a custom pool's
implementation correct. Returned activation ID, node, class, and granted
budget are checked before handoff; a mismatched lease is not marked reusable.

## Fairness and progress

Scheduling is independent within each fixed class:

1. Tenants with queued work take round-robin turns. New active tenants join the
   tail; tenants with remaining work rotate after a grant, and empty tenant
   queues are removed.
2. Within the selected tenant, requests normally sort by descending admitted
   priority, earliest original monotonic deadline, then enqueue sequence.
   A missing deadline follows finite deadlines.
3. Requests waiting at least `starvation_after` precede newer requests within
   that tenant's turn. Among aged requests, the oldest enqueue sequence wins.

Priority therefore does not let one tenant consume every other tenant's turn.
Aging prevents a continuous stream of higher-priority requests from overtaking
an older request indefinitely within its tenant, provided compatible capacity
continues to become available and the request remains live. It is not a
guaranteed wall-time service bound or preemption of an executing guest.

The scheduler calls `CellPool::try_acquire_now`, which either returns a lease,
reports no available capacity, or fails without placing another waiter in the
pool. A bounded coalescing `subscribe_changes` watch is registered before
observing or acquiring capacity, so a concurrent release cannot be lost between
the failed probe and the wait. Notification values are hints to recheck the
pool; they do not constitute capacity accounting.

Enqueue futures must remain polled by the caller's shared async runtime. There
is no detached dispatch loop. Each synchronous dispatch pass selects at most
64 candidates, including candidates rejected before handoff. A contended or
exhausted pass retries through a cooperative yield while continuing to poll
cancellation and the original deadline before accepting a handoff. Continuous
queue replenishment therefore cannot make one pass process unlimited work.

Selection and bookkeeping inspect bounded live queues, not registered services
or dormant deployments. Sequence allocation is checked and fails rather than
wrapping. If every cell in a class is quarantined, queued work fails explicitly
instead of waiting for permanently unusable capacity.

## Ownership, deadlines, and cleanup

`ActivationScheduler::enqueue` consumes an `AdmittedSchedulingRequest` holding
one `AdmissionPermit` and an `Arc<dyn SchedulingCancellation>` for the same
activation ID. Its result is an affine `ScheduledActivation`, not a detached
`CellLease` whose quota reservation could be released too early.

| Stage | Owned resources and terminal behavior |
| --- | --- |
| Queued | Admission permit, bounded queue entry, and cancellation capability. Rejection, cancellation, expiry, shutdown, or dropped future removes the entry and refunds the permit. |
| Selected, not accepted | Internal `PendingAssignment` holds the untouched lease and permit. Lost receiver, failed acceptance, cancellation, deadline, or shutdown reclaims the unaccepted lease through its issuer before returning quota. |
| Accepted | `ScheduledActivation` privately retains `CellLease` and `ExecutionPermit`. Only immutable lease/permit accessors are exposed. |
| Proven cleanup | The execution owner calls `ScheduledActivation::release().await`; quota stays owned through the pool disposition. |
| Uncertain cleanup | The execution owner calls `quarantine(reason).await`. Dropping an accepted assignment without disposition conservatively abandons/quarantines the lease before refunding quota. |

Before selection and acceptance, scheduling checks the permit's original
monotonic deadline and cancellation. The admission-to-execution transition
checks that deadline again under quota ownership; acceptance rechecks after
the transition before exposing the assignment. Queue time is not granted a new
relative wall-time allowance, and the pool's wall-clock deadline is not used
as a substitute for the original monotonic deadline.

Only queue reservation is returned when execution starts. Concurrency, CPU,
memory, and other admission reservations remain held until cell disposition.
Dropping a pending release/quarantine future must preserve the same order:
the pool's lease ownership settles or conservatively abandons first, then the
execution permit is refunded. External pools must honor that ownership contract.

The generalized activation owner must retain the accepted assignment in the
task that actually owns guest execution. A dropped client/transport future
must not release quota while detached guest work continues. The scheduler does
not run a backend, prove guest cleanup, finalize all activation accounting, or
publish a terminal activation status; those are the execution/lifecycle owners'
responsibilities.

## Shared cancellation and shutdown

`SchedulingCancellation` exposes activation identity, cancellation state,
`request_cancellation`, and a cancellation future. `CancellationHandle` from
`latent-node::ActivationCancellationRegistry` implements it using the original
registration state and watch signal. The scheduler owns no second cancellation
registry or terminal-state authority.

A scheduler request calls the handle's bounded `cancel("scheduler cancellation")`.
It returns `true` only when it installs the first cancellation; repeated or
post-terminal requests return `false` and do not replace the first reason. The
upstream token and registry observe the same cancellation, and upstream
cancellation wakes scheduler waiters. Successful terminal publication does not
itself complete the cancellation future. Terminal publication and cancellation
retain their existing single linearized state transition.

`ActivationScheduler::cancel` looks up a live scheduled activation and delegates
to this upstream capability. An unknown activation returns `not-found`; the
method does not manufacture the public invocation API's richer cancellation
disposition or release an executing cell. Guest interruption and final cleanup
remain with the activation/execution owner.

`shutdown` stops new scheduling and settles queued waiters. An unaccepted
handoff rechecks shutdown. Already accepted activations retain their cell and
quota until explicit release/quarantine or conservative abandonment; shutdown
does not declare them cleaned up or forcibly return their cells.

## Observations and errors

`observations(class)` returns a `SchedulerSnapshot` containing pool capacity,
availability, active leases and quarantine; queue depth and queued tenants;
rejections, cancellations, expirations and grants; total/maximum wait time; and
oldest live lease age. Timing uses monotonic elapsed time. Cumulative counters
saturate and retain no history keyed by activation, tenant, or service.

Queue and pool observations are individually coherent and sampled separately;
the combined result is not an atomic cross-layer snapshot. The observation path
uses bounded live bookkeeping and pool counters without scanning service or
deployment catalogs. `SchedulerInventorySource` exposes these snapshots to the
[implemented node inventory](telemetry.md#inventory), which the
[standalone node](reference/standalone-node.md) serves through management RPCs.

Scheduler-generated errors carry the existing platform code and one
`scheduler.limit` detail with a stable `reason`, excluding caller payloads and
tenant metadata. Admission and pool errors can retain their owning subsystem's
structured details.

| Condition | Scheduler code / reason |
| --- | --- |
| Invalid configuration or initial pool topology | `invalid-argument` / `configuration` or `pool-topology` |
| Permit from another quota ledger | `permission-denied` / `foreign-admission` |
| Mismatched cancellation identity | `invalid-argument` / `cancellation-identity` |
| Class queue at its exact bound | `resource-exhausted` / `queue-full` |
| Duplicate live scheduler identity | `already-exists` / `duplicate-activation` |
| Cancellation or deadline before acceptance | `cancelled` / `cancelled`, or `deadline-exceeded` / owning deadline reason |
| No usable class capacity remains | `unavailable` / `all-cells-quarantined` |
| Shutdown, closed pool watch/handoff, or exhausted sequence | `unavailable` / corresponding bounded reason |
| Pool returns incompatible lease metadata | `internal` / `pool-lease-mismatch` |

`LocalNodePlacement` implements the existing placement seam by selecting only
the configured local node from supplied candidates. Missing local membership
fails explicitly. It is not cross-node placement, cluster health, autoscaling,
or authorization from candidate attributes.

## Validation and compatibility

Run the focused deterministic suites with the pinned toolchain:

```sh
cargo test -p latent-scheduler --all-targets --locked
cargo test -p latent-node --test scheduling_cancellation --locked
cargo test -p latent-node --lib --locked
cargo test -p latent-admission --locked
```

The fair-scheduler integration tests use real admission permits and fixed cells
with small configured capacities. They cover class and queue bounds,
round-robin tenants, priority/deadline/aging order, monotonic wait observations,
queued cancellation/expiry/drop, unaccepted versus accepted handoff, shutdown,
foreign permits, malformed pool leases, disposition failure, and short bounded
concurrent churn. Nonqueueing pool tests cover atomic acquisition and coalescing
notifications, including release/observe races and unusable-capacity changes.
Node adapter tests verify shared cancellation identity/reason/wakeup, terminal
publication ordering, and isolation when an activation ID is registered again.
Existing Phase 0 pool and activation-runner regressions remain required.

These checks are focused scheduler regressions. The completed
[Phase 1 gate](phase-1-completion.md) combines the separate scaling/soak evidence
and the standalone release-to-invocation flow. The
[extension results](phase-1-extension-completion.md) retain the scheduler's mixed
timings: eliminating cancellation scans and shifts did not produce uniformly
faster settlement or lower selected allocations.

The Rust `ActivationScheduler` seam intentionally evolves to consume an admitted
request and return an owned assignment. Independent legacy `CellPool`
implementations remain source-compatible through defaults for the new
nonqueueing/change methods, but must implement those methods to serve
`LocalScheduler`. WIT, Protobuf, schemas, SDK wire contracts, and persistent
catalog formats are unchanged by scheduling.
