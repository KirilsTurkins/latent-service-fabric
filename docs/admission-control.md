# Single-node admission and overload control

`latent-admission` implements the Phase 1 `AdmissionController` and local
`QuotaProvider` contracts. The controller rejects invalid, unauthorized,
incompatible, infeasible, and overloaded work before execution-cell allocation.
It creates no execution cell, cancellation registration, artifact preparation,
worker, runtime, socket, service-specific queue, or periodic task.

The embedded deployment catalog supplies immutable typed execution policy via
`RevisionPolicySource`. The [fair scheduler](scheduling.md) consumes the permit
and retains its reservation with the assigned cell. The generalized activation
manager remains #11 work; these APIs do not turn the Phase 0 test executable
into the Phase 1 invocation service.

## Ownership and trust boundaries

Create **one `LocalQuotaProvider` per node** and share clones with every local
admission controller. The provider owns immutable startup policy and one mutex
protecting all node, tenant, trust-class, queue-class, and cell-backlog counters.
Changing the route view with `with_policy_source` retains this same ledger.
Creating independent providers for services or new route generations would
create independent limits and is not a supported node composition.

`AdmissionRequest` is an internal input from an authenticated adapter, not an
untrusted wire identity. The adapter must authenticate the principal, derive its
tenant and service identity, and measure the actual payload length. It must not
copy an untrusted Content-Length or derive a principal from arbitrary metadata.
Admission checks exact tenant equality, a configured subject/kind allowlist,
non-anonymous identity, bounded identifiers, and a service identity for service
principals. Claims and attributes cannot grant access, priority, trust, or cells.
External identity providers and a general policy language are not implemented.

Resolve and admit against the **same `PinnedRouteResolver`**:

```rust,ignore
let pin = std::sync::Arc::new(deployments.pin()?);
let revision = latent_routing::RouteResolver::resolve(
    pin.as_ref(), &envelope.target, routing_key,
)?;
let controller = node_admission.with_policy_source(pin);
let permit = controller.admit_now(latent_admission::AdmissionRequest {
    activation_id: envelope.activation_id.clone(),
    principal: envelope.principal.clone(),
    revision,
    requested_budget: envelope.budget.clone(),
    deadline_unix_millis: envelope.deadline_unix_millis,
    payload_bytes: envelope.input.len().try_into().expect("payload length fits u64"),
    priority: envelope.priority,
    attributes: envelope.metadata.clone(),
})?;
```

The catalog verifies the entire tenant/service/route/contract/function/revision/
release/generation tuple. It does not reselect a revision with a different routing
key. Forged `ResolvedRevision::attributes` do not provide deployment policy. The
returned permit removes these untrusted attributes and exposes typed, immutable
obligations instead. A held catalog view continues serving the exact old policy
after deployment replacement or deletion; a newer view rejects an old generation.
Pins are trusted-local lifetime capabilities, not externally serializable bearer
tokens. The embedding owner must not retain unbounded historical pins.

Catalog compilation retains a small charged policy record per revision, not a
full artifact, contract tree, or component bytes. Lookup is a bounded immutable
index operation with no filesystem access or compilation. Persisted catalog
format, checksums, logical revision identities, and route ordering are unchanged;
restart rebuilds the same typed policy from verified release metadata.

## Configuration and exact limit semantics

There is no permissive default tenant or wildcard authorization. Configuration
is explicit through `NodeAdmissionPolicy`; `LocalQuotaProvider::new` validates it
before retaining any activation state. Policy is immutable for the ledger's
lifetime. Changing a controller's catalog source does not change its node policy.

| Configuration | Meaning |
| --- | --- |
| `budget_ceiling` | Hard per-activation node budget, including a positive finite relative wall-time ceiling. |
| `limits` on node, tenant, and trust class | Independent maximum live activations, queued reservations, reserved CPU fuel, and reserved memory bytes. |
| `maximum_payload_bytes` on node and tenant | Independent exact byte ceilings; equality is accepted. |
| `maximum_priority` on node and tenant | Independent authorization ceilings. Every allowed priority must map to exactly one configured queue class. |
| `queue_classes` | Named, nonoverlapping priority ranges with independent queue bounds. |
| `cell_classes` | Startup-defined capabilities for a subset of tiny, small, standard, large, and extra-large. Each configured class has positive memory capacity and usable parallelism, supported threading models, and features. |
| Tenant subject/kind/trust/cell allowlists | Exact authorization; empty allowlists deny access. Extra-large requires explicit tenant and trust-class permission. |
| `maximum_identifier_bytes` | Bounds caller-selected activation/target names; empty, whitespace-containing, and control-containing identifiers are rejected. Generated revision/release identities have a separate bounded allowance of at least 83 bytes and must match the pinned catalog exactly. |
| `maximum_metadata_entries` / `maximum_metadata_bytes` | Aggregate bounds across principal claims, request attributes, and resolved-revision attributes, checked before retaining quota state. |
| `overload` | Independent CPU and memory pressure thresholds and maximum observation age. Pressure at or above its threshold rejects admission. |
| `deadline` | Estimated service time, minimum useful execution time, and a safety margin for bounded-backlog feasibility. |
| Architecture, region, zone | Node placement identity checked against the pinned deployment restrictions. |

Every numeric quota is finite and exact. Zero grants no capacity. In particular,
zero queue capacity disables admission at that scope; it does not mean an
unbounded queue or an immediate-execution-only mode. Every admission initially
reserves a queue slot, even when a downstream cell is immediately available.

`active_activations` means **queued plus executing** reservations, not only guest
execution. CPU fuel and granted memory are reserved at admission for both states.
They measure concurrent promised capacity, not CPU billing or a replenishing
rate bucket. `QuotaSnapshot::reset_at_unix_millis` is therefore `None`.
Completion returns the entire reservation, regardless of actual consumption;
activation consumption is separately finalized by `ActivationBudget` from #6.

The budget grant is the bounded intersection of the request, capsule ceiling,
deployment ceiling, and node ceiling. CPU or memory zero makes execution
infeasible. Later-phase resource dimensions must be zero in Phase 1 requests.
An omitted relative wall-time request adds no restriction at that layer; it
cannot bypass the node's finite relative ceiling. An absolute caller deadline is
separate and can only shorten the grant.

The selected cell is the smallest memory-capable, threading-compatible,
feature-compatible class permitted by both the tenant and trust class. Ties use
the fixed tiny-to-extra-large class ordering. Admission does not reserve a cell
or grow a pool; `CellClassPolicy::parallelism` must match the downstream usable
pool capacity. A node that loses usable capacity must publish conservative queue
delay or stop accepting work until configuration and scheduling agree.

## Deadline feasibility and node overload

A grant binds wall time to a monotonic deadline once, at admission. For a class
with `n` existing live reservations and configured usable parallelism `p`, the
local queue estimate is:

```text
local_wait = floor(n / p) * estimated_service_time
required = max(local_wait, observed_queue_delay)
           + minimum_execution_time + safety_margin
```

Admission rejects when the remaining monotonic duration is less than or equal
to `required`. All arithmetic is checked; overflow rejects instead of wrapping.
The quota critical section includes this calculation, so concurrent callers see
previously accepted reservations. Live admission resamples monotonic time after
policy lookup and quota-lock contention, without moving the original deadline.
Expired grants and stale observations cannot become accepted merely because a
previous clock sample was valid. `admit_at` is an explicitly trusted deterministic
clock seam; do not expose it to a caller.

This is a conservative configured estimate, **not a completion-time guarantee**.
Use measured service-time assumptions and conservative load input. The scheduler
must still check the original deadline and cancellation immediately before cell
allocation and handoff. Priority ordering/fairness belongs to #8, not admission.

`NodeLoadSource` supplies node-wide trusted observations. `NodeLoadState` is an
externally updated shared value, not a monitoring worker. Missing/unavailable,
malformed, future-dated, stale, or out-of-order samples fail closed. Sampling is
not an atomic transaction with hardware pressure: a new overload after the
sample remains a downstream scheduling/execution concern. Never populate load
observations from request metadata. Diagnostic errors disclose no load numbers.

## Permit lifecycle and downstream obligations

`AdmissionPermit` and `ExecutionPermit` are non-cloneable and cannot be minted by
callers. Their identity, effective budget, deadline, and obligations are exposed
only through immutable accessors. A compile-fail test protects affine ownership.

1. Admit before cancellation registration, queue insertion, or cell allocation.
   The successful permit owns the queue/concurrency/CPU/memory/trust reservation.
2. Transfer ownership of the permit with the queued work. On enqueue failure,
   queued cancellation, expiry, panic, or abandoned future, drop that permit.
3. Immediately before cell allocation, check cancellation and
   `ensure_schedulable_at`. After obtaining a lease, consume the queued permit
   with `start_execution`. It resamples the live monotonic clock under the quota
   lock. On success only queue capacity is returned; other reservations remain.
   On error the permit is dropped, and the scheduler must also release or
   quarantine its independently owned lease. `start_execution_at` is the trusted
   deterministic-clock equivalent, not a caller-supplied timestamp.
4. Enforce the exact selected cell/queue/trust class, priority, backend,
   threading/state model, features, call-depth limits, all granted budget
   dimensions, and the original deadline. Initialize accounting from
   `effective_budget`; never reset the relative wall-time ceiling at dequeue.
5. Retain the execution permit until the guest has stopped, accounting has been
   finalized, and the cell has been released or quarantined. Then drop it.

The generalized activation owner must retain the permit in the task that actually
owns execution. Dropping a transport future while detached execution continues
must not release that task's quota prematurely. Admission deliberately does not
create a second cancellation registry or attempt to kill execution from `Drop`.
The existing affine cell lease remains the authority for reuse/quarantine.

All reservation checks and checked additions happen before ledger mutation.
Duplicate activation IDs cannot replace a live reservation or release another
call's capacity. Only configured tenants may create counters, and zero-use
entries are removed. Live bookkeeping is bounded by the configured node
concurrency limit, identifier sizes, and the fixed configured class/tenant sets.
No map or queue grows with rejected service cardinality.

## Structured failures

Admission errors use the existing platform codes and one `admission.limit`
detail with stable `scope`, `dimension`, and `reason` fields. Reasons identify the
limiting dimension without echoing principal names, tenant identifiers, request
attributes, raw payloads, filesystem paths, or other tenants' counters.

| Failure | Typical platform code / reason |
| --- | --- |
| Unknown/unauthorized principal or tenant | `permission-denied` / `principal-not-authorized` |
| Unauthorized priority or trust/cell class | `permission-denied` / corresponding `*-not-authorized` reason |
| Invalid identifiers, metadata, unsupported request budget | `invalid-argument` / dimension-specific reason |
| Missing or mismatched pinned revision | `admission-rejected` / `revision-not-available` |
| Unsupported capsule requirements or placement | `admission-rejected` / `unsupported-execution-requirement`, `placement-not-compatible`, or `no-compatible-cell` |
| Payload too large | `resource-exhausted` / `payload-too-large` (not retryable unchanged) |
| Reserved concurrency, queue, CPU, or memory exhausted | `resource-exhausted` / `capacity-exhausted` |
| Node pressure threshold reached | `resource-exhausted` / `node-overloaded` |
| Queue cannot reasonably meet deadline | `admission-rejected` / `queue-deadline-infeasible` |
| Expired deadline | `deadline-exceeded` / `deadline-exceeded` |
| Load or quota source unavailable | `unavailable` / source-specific sanitized reason |
| Duplicate live activation ID | `already-exists` / `activation-id-unavailable` |

Retryability is set for transient unavailability, occupied capacity, node
overload, and queue infeasibility. It is not set merely because the platform code
is `resource-exhausted`; increasing retries cannot fix an oversized payload or
an intrinsically infeasible zero budget.

`QuotaProvider::snapshot` and aggregate usage observations are trusted-local
administrative surfaces. Their embedding API must separately authorize access
to the requested tenant; they are not included in rejection details.

## Validation

Run the feature tests, affine compile-fail test, catalog integration, and existing
pool/runner regressions with:

```sh
cargo test -p latent-admission --locked
cargo test -p latent-control-store --lib --locked
cargo test -p latent-node -p latent-scheduler --locked
cargo clippy -p latent-admission --all-targets --locked --no-deps -- -D warnings
```

Admission unit tests cover independent limits, exact boundaries, all unsupported
budget dimensions, class selection, sanitized errors, ownership, stale load,
deadline arithmetic, and coordinated concurrent reservations. An isolated Linux
regression submits 1,000 distinct rejected service targets and completes 100
reservations, checking unchanged thread/descriptor/socket/child counts and empty
retained tenant counters. The child has a fixed deadline and is reaped on failure.
The larger 100,000-target variant is ignored by ordinary CI and requires explicit
selection:

```sh
cargo test -p latent-admission --locked \
  tests::stress::admission_state_does_not_grow_with_100k_rejected_services -- \
  --exact --ignored --nocapture
```

Catalog tests verify every pinned identity field, deterministic weighted policy
selection, generation replacement/deletion, restart, and no artifact access on
admission. Additional tests exercise the real `Phase0ActivationRunner` and
`FixedCellPool` with explicitly injected backend success, declared error, trap,
deadline/fuel interruption, platform failure, and uncertain cleanup. They verify
cell disposition and quota/cancellation cleanup after terminal outcomes, real
queue overflow, queued/running cancellation, and dropped futures. This is not a
claim of new Wasmtime execution coverage; the retained Phase 0 runtime suite
continues to supply that evidence.

These tests belong to the maintained workspace CI, not a permanent workflow for
each completed issue. No WIT, Protobuf, JSON Schema, SDK, or persisted catalog
format changes are required. The Rust admission structs intentionally evolve:
caller deadlines are explicit, snapshots include queued reservations, and permits
become affine capabilities instead of cloneable freely constructible metadata.
