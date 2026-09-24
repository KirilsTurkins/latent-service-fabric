# Isolated local service invocation

The `lsf-local-service-invocation-v1` provider implements the canonical async
`latent:service/invoke@0.1.0` interface. A guest can invoke a
checked application export through the broker and the normal node activation
manager. Each child gets a fresh Store and activation state. Compiled code may
be shared; permission, identity, cells and budgets remain activation-owned.

## Installation and exact target selection

A trusted node composition installs one provider registration with the above
profile and capability, supplies its `ConfiguredBindingProvider` with an exact
local deployment, and publishes a `BindingDefinition` with explicit
`isolated-local` mode. The consumer contract is the canonical service interface;
the provider contract is the application's exported interface. This explicit
profile is the only exception to direct bindings requiring equal contracts.
The provider configuration, deployment grant and policy must all permit `call`.
The service policy names the exact target service and scoped publication.

The compiler separately verifies the consumer's complete canonical host WIT and
the target's actual exported value signatures against its retained package.
This profile selects one application target per imported dispatcher, with at
most 128 sorted, unique function names and 4 KiB of combined function-name bytes.
The checked descriptor pins tenant, service, contract, deployment revision,
component, publication and route. A guest may select only one of those functions.
Unknown functions, different contracts, mismatched explicit routes and catalog
fallback are denied. Omitted tenant means the caller's tenant. A foreign tenant
requires the configured target, an explicit policy for that scoped publication
and the target tenant's normal admission of the derived service principal.
Cycle/depth checks use actual `(tenant, service)` edges, including foreign targets.

The runtime composition calls `LocalActivationManager::local_service_invoker`
with a finite child ceiling and installs the resulting shared adapter through
`ActivationCapabilityRuntime::install_local_services`. The manager reference is
weak, so the adapter cannot create a backend/manager ownership cycle. The node
must select [descendant and provider budgets](descendant-budgets.md). Standalone startup installs
the adapter when that profile and a capability runtime are supplied; standalone
JSON provider configuration supplies only HTTP and local-blob host bindings.
Configure the checked local target and its binding through the trusted catalog
composition described above. A declared import or policy CRUD alone cannot
install this authority.

## Guest values, identity and deadlines

An application export that waits for the canonical async service import must
itself be a freestanding async Component Model export. Exact WIT, binary and
contract metadata must agree on this function kind. Package inspection accepts
this form; production preparation admits it only with the local service adapter
installed. Synchronous callees remain supported. This extends the selected
application execution profile without changing the frozen host WIT. It does
not enable resource, future or stream values.

The caller passes an opaque payload and media type. The generic application
dispatcher uses [WIT values](../protocol/wit-values.md), including positional JSON
arrays. A top-level declared `result.err` remains a declared error, distinct from
platform failure. Input is capped at 64 KiB including retained string/vector
capacities and metadata overhead; identifiers are at most 512 bytes, with at
most 64 unique metadata pairs. Output, declared errors and platform details have
a 64 KiB aggregate owner, at most 128 metadata pairs, 16 error details and 4 KiB
per string. Capacity is reserved before child admission. The actual output owner
remains charged through guest lowering and Store destruction.

The node derives child ID, parent/root IDs and trace correlation from the actual
accepted caller. The child principal is `service`, has the source service and a
length-framed subject `service:<tenant-length>:<tenant>:<service-length>:<service>`,
and is admitted in the target tenant. User credentials and administrative claims
are not forwarded. Guest metadata carries no identity authority. Idempotency keys
remain correlation data and do not provide durable deduplication or exactly-once
execution. Calls accepted before interruption may already have executed.

The guest's optional Unix deadline is converted once using the node's clock
sample and intersected with the broker's exact monotonic policy deadline, the
parent deadline, deployment/node ceilings and delegated wall budget. Preparation,
scheduling and execution retain the resulting instant. Resuming a caller never
starts a new deadline.

## Fixed cells and conserved descendant budgets

The initial allocation policy delegates at most half the parent's currently
unreserved fuel, memory, wall time and supported cumulative provider dimensions,
then intersects the configured and normal admission ceilings. One child-call
unit is consumed on accepted child admission; half the remaining child-call
allowance may be delegated onward. Existing depth, live-child and whole-tree
limits apply. Concurrent calls reserve separate affine owners. Settled unused
capacity can be reused; spent work and still-retained results cannot.

Before a nested child prepares code, the normal scheduler performs one fair
dispatch pass through `try_enqueue`. A child gets an existing free cell or a
prompt capacity rejection. It does not remain queued behind its own parent.
Parents keep their cells while waiting; no overflow cell, service worker, inline
execution or call-graph fusion is created. Ordinary root cold preparation keeps
its existing behavior and does not reserve a cell before readiness.

The adapter checkpoints the parent's native fuel before delegation and adjusts
the Store fuel watermark on reservation and resumption. Child instructions are
charged once. A pending guest memory growth reserves aggregate capacity before
allocation, preventing a concurrent child from spending the same memory grant.
Failed growth refunds only that pending claim; observed memory remains charged.

One bounded task per accepted child drives the normal lifecycle through cleanup,
even after its result waiter disappears. Parent cancellation and terminal closure
propagate through the existing descendant tree. The child ledger remains owned
until execution and result cleanup actually finish. Explicit cancellation follows
the normal reusable-or-quarantined disposition. Abruptly dropping an executing
parent without a cleanup receipt conservatively quarantines its own cell; this
does not prevent its node-owned child from completing cleanup. No later refund
silently unquarantines that parent cell.

## Validation

Required [capability audit](capability-audit.md) is admitted before child creation.
Its digest covers the real typed target, payload and options. A recorded
`LocalDispatchAccepted` means the lifecycle was accepted even if the child guest
later fails. A full required journal prevents admission; a failed terminal write
never causes automatic child retry.

`cargo test -p latent-wasmtime --test local_service --locked` uses real canonical
async caller and callee components with the catalog, policies, compiled bindings,
admission controller and scheduler. It covers success, concurrent calls, spent
child-call limits, declared errors, denied and cross-tenant policies, exact routes,
revocation after warm preparation, cell saturation, parent cancellation and
abandonment, oversized input, expired deadlines and fresh activation identity.
The package/catalog fixture uses an injected trusted admission authority; these
are execution and authorization tests, not cryptographic verification claims.
Policy, scheduler, packaging, core and node unit tests separately cover wrong
publication dependencies, graph bounds, type proofs, shared memory and deadline
precision. These tests do not require large load runs.
