# Local activation lifecycle

`latent_node::LocalActivationManager` composes the stateless Phase 1 lifecycle:
request validation, pinned routing and policy, admission, fair scheduling,
repository-backed owned preparation, capability binding, contained execution,
accounting, and terminal publication. Its dependencies are Rust ports and
node-owned services. Public invocation/management adapters and the standalone
node compose this manager through separate modules.

## Start and identity

`start(ActivationRequest)` validates bounded input and trusted principal scope,
reserves a journal entry and cancellation identity, and returns an
`ActivationHandle`. Its activation ID is available immediately, before polling
or completing the invocation. Awaiting the handle yields an `ActivationReceipt`
with that ID, the pinned `ResolvedRevision` when resolution succeeded, and the
typed `ActivationOutcome`. Early failures can have no resolved revision.

The manager spawns no task; its caller owns and polls the handle. Dropping it,
including before the first poll, abandons the accepted invocation and
terminalizes its record through the same lifecycle owner. The standalone node
instead transfers that exact handle to its bounded cleanup supervisor after an
RPC disconnect or transport timeout. The handle and its resources remain owned
until cleanup finishes or the continuation reaches its cap.

The request preserves optional activation, root, and parent IDs until validation.
Missing activation IDs come from the manager's node-owned `ActivationIdSource`;
present empty IDs are invalid. With neither root nor parent supplied, the root
is the effective activation ID. A parent without an explicit root is invalid.
Otherwise supplied lineage remains bounded opaque correlation. It does not
require parent/root records in the local retention index and does not confer
authority, join a trusted invocation tree, or authorize cross-tenant access.
The manager does not infer ancestry from request metadata.

IDs must be nonempty, fit the configured UTF-8 byte bound, and contain no
whitespace or control characters. Input allocation capacity and aggregate retained
context, including spare string capacity, also have explicit limits. The trusted embedding supplies the authenticated
principal; its tenant must match the target, anonymous principals are rejected,
and service principals must identify their service. Admission additionally
checks the configured subject, principal kind, trust class, and resource policy.
Caller metadata never replaces those checks.

Trace context, idempotency metadata, and retry count are preserved within their
bounds. Activation IDs are correlation identities, not idempotency keys. The
manager provides neither automatic retries nor durable deduplication. Duplicate
active or retained IDs return `AlreadyExists`; bounded retention means an
expired ID may later be reused. Status `not-found` does not prove an activation
never ran. These rules consume the [SDK identity contract](../sdk/README.md).

## Resolution and lifecycle

The manager obtains one immutable `ActivationCatalog` from
`ActivationCatalogSource::pin`. The same view supplies both `RouteResolver`
selection and `RevisionPolicySource` admission policy. The effective activation
ID is the bounded routing key. Repeated keys select consistently within one
catalog generation; different IDs can select different weighted revisions.
Idempotency metadata is not silently substituted for this key. A caller can
influence its routing bucket by choosing its ID, so this is selection rather
than an authorization boundary.

Tenant, target contract/function, revision, release digest, route generation,
execution policy, and granted budget remain pinned. A deployment update while
the call is queued or materializing cannot redirect that activation. Admission
uses the shared node quota ledger and the pinned policy; it does not construct
a replacement ledger or reread mutable catalog policy.

Successful stateless execution advances through:

```text
Received -> Resolved -> Admitted -> Queued -> Materializing -> Running
```

Terminal state is separate from phase. The final event repeats the last live
phase and records its terminal state; it does not introduce a `Terminal` phase.
Stateless calls omit suspension, state-commit, and effect-delivery phases.
Successful and declared-error guest returns finish with `Completed` at `Running`,
while their retained outcome variants remain distinct. Every activation has
monotonically increasing event sequence numbers and exactly one terminal event.

| Outcome | Terminal classification |
| --- | --- |
| Guest success | `Completed`, retained success summary |
| Declared guest error | `Completed`, retained declared error |
| Cancellation or expired deadline | `Cancelled` or `DeadlineExceeded` |
| Fuel, memory, or another enforced resource limit | `ResourceExhausted` |
| Guest trap | `GuestTrap` |
| State conflict | `StateConflict` |
| Unavailable route/dependency | `DependencyFailed` |
| Invalid request, denied admission, incompatible contract, corrupt artifact | `Rejected` |
| Internal failure or dependency panic | `PlatformFailed` |

Each terminal status retains its typed outcome, finalized consumption, and
terminal timestamp. Immediate success contains output bytes; retained success
contains its committed-state, effect, and metadata summary without retaining
those output bytes. State versions and effect IDs remain empty for ordinary
stateless success. Declared errors are never inferred from payload conventions.

## Cancellation, cleanup, and accounting

`status(tenant, id)`, `events(tenant, id)`, and `cancel_for(tenant, id, reason)`
require an authenticated tenant scope from their caller. A foreign tenant sees
no record or events and receives the `NotFound` cancellation disposition.
Knowledge of an ID grants no access. The legacy unscoped `ActivationManager`
cancel method returns `PermissionDenied` on this manager; product adapters must
use the scoped method.

Cancellation returns `Accepted`, `AlreadyTerminal(state)`, or `NotFound`.
Acceptance is idempotent and preserves the first reason. It does not claim that
cleanup has already finished. Cancellation and terminal publication linearize
against the same registration: accepted cancellation wins the terminal race;
publication that wins first makes a later cancel return `AlreadyTerminal`.

One lifecycle owner retains the cancellation registration, journal reservation,
shared activation budget, and affine scheduler assignment. The execution
backend obtains the same ledger through `ExecutionCancellation::budget_accounting`.
Host log charges and observed CPU/memory consumption survive failures and drops;
the owner finalizes only after execution resources and cell disposition settle.
Accepted explicit cancellation takes precedence over deadline expiration at
terminal publication. A raw transport disconnect does not install that explicit
cancellation winner: the original deadline still takes precedence over the
transport stop, and both take precedence over an ordinary guest result.

After admission, the manager calls `ExecutionBackend::prepare_ready_from_repository`
with the owned repository and pinned release's preparation key. The affine
`PreparedReadiness` retains immutable code and all declared imports while the
activation remains `Queued`. Readiness completes before scheduler enqueue;
the original admission permit, budget, deadline and cancellation registration
remain owned throughout. Cold completion therefore affects scheduler eligibility:
arrival order across cold code is not a FIFO guarantee.

Once a cell is assigned, `materialize_ready` transfers the same pin into a
`PreparedActivation` containing an affine `PreparedUse` and the complete import
list, including optional imports. Wasmtime acquires its active-instance permit
at this point; readiness itself owns no Store, instance or execution cell.
The use pins the immutable prepared runtime through cache eviction.
`invoke_prepared_contained` consumes that owner; completion, future drop, and
panic release its guard. Direct callers can still use `prepare_for_use` with
owned artifact bytes.
An activation never calls global prepared-cache release as its cleanup step.
The manager binds only the prepared component's explicitly declared imports;
the backend validates the supported capability surface. Each activation gets
fresh capability handles, host context, store and component instance.

For the directory repository, preparation can reuse a verified immutable
snapshot through a sealed source whose identity lookup and fetch belong to the
same repository owner. A warm cache hit performs no component read/hash or full
manifest/contract traversal. A miss fetches and verifies stored content through
that source before compiling and adopting it. The sealed owned directory source
keeps bounded verified I/O and compilation on fixed compiler workers. Identical
verified misses share a job with bounded waiter registration. Cancelling the last
running waiter leaves the job's resources owned until native compilation actually
returns; its abandoned result is discarded. Repositories without this source
use the fully verified fetch path. These are preparation optimizations, not a
replacement for routing, tenant checks, admission or activation accounting; see
[Wasmtime preparation](runtime/wasmtime.md#node-policy-and-shared-preparation).

Artifact/readiness failure terminates at `Queued` without assigning or disposing
of a cell. Dropping that owner releases its unassigned admission quota. A failure
after assignment releases the cell that never entered execution.
Before backend entry, dropped built-in assignments can synchronously reclaim
their unaccepted lease. Once execution begins, reuse requires a positive backend
cleanup proof. Missing proof, dropped running work, or uncertain cleanup
quarantines the cell before refunding its quota. Panics are contained by the
manager and cannot bypass terminal accounting or affine cleanup.

`cleanup_grace` bounds cooperative backend and pool cleanup; it defaults to
100 milliseconds and must be positive and no more than one second. A missing
execution-cleanup acknowledgment leads to conservative cell quarantine. External
pool/backend implementations must honor their synchronous ownership and cleanup
contracts. This grace does not preempt a running native compiler job: cancellation
removes the activation's waiter, while the factory retains the worker and its
reservations until compilation returns and final shutdown joins the thread.

The trusted `ActivationHandle::interrupt_for_cleanup` port marks
`ActivationTransportInterruption::Disconnected` or `DeadlineExceeded` and returns
the same handle for continued polling. It preserves the original invocation,
budget, deadline, and any already-started cleanup wait. Standalone reserves a
continuation slot before accepting the identity and uses one fixed async driver;
it neither retries the invocation nor starts a task per disconnect. Its handoff
cap is twice `cleanup_grace`, including driver scheduling and both cleanup
stages. An overrun is failed cleanup evidence. Reuse still requires the backend's
positive cleanup proof and successful pool disposition; uncertain cleanup remains
quarantined. Direct handle Drop and the default unsupervised invocation bridge
retain their existing abandonment behavior. See
[standalone shutdown](reference/standalone-node.md#durable-restart-and-shutdown-evidence).

## Bounded status and validation

`LocalActivationJournalConfig` bounds active records, retained terminal count,
per-record bytes, aggregate reserved/retained bytes, and terminal retention time.
An active record reserves its terminal allowance before invocation work starts.
Retention uses monotonic time and evicts terminal records only. It cannot discard
an active cancellation/status owner to make room for more work. Public journal
queries do not grant the capability to advance another activation's lifecycle.

Defaults allow 64 active records, 1024 retained terminal records, 4 MiB per
record, 256 MiB aggregate accounting, and five-minute terminal retention. These
are explicit configured ceilings, not durable journal or restart guarantees.

`activation_lifecycle` tests use real admission and scheduling with tiny
controlled catalog, artifact, and backend implementations. They cover identity,
scope, routing keys and pinning, ordered outcomes, bounded retention, cancellation
and drops at each asynchronous stage, poll/destructor panics, concurrent start/cancel/completion,
and lease/quota/preparation cleanup. Each completed invocation uses a five-second
watchdog; the suite performs no scale or soak workload.

```bash
cargo test -p latent-node --test activation_lifecycle --locked
```

The retained Phase 0 suites continue to test their original containment
composition. Test-only payload controls remain in the containment guest fixture;
product dispatch passes such bytes unchanged to the selected export. Real
Wasmtime owned-preparation and drop tests additionally exercise the runtime
behind this port. These checks do not replace the native reclamation and scale
evidence required by the [Phase 1 completion gate](roadmap.md).
