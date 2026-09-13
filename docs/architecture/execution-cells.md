# Execution-cell architecture

An execution cell is a reusable sandbox allocation slot. It is not associated with a service identity while idle.

The current node retains the Phase 1 fixed in-process cell pools, fresh Wasmtime stores and
affirmative reuse/quarantine through the [local scheduler](../scheduling.md)
and [activation lifecycle](../activation-lifecycle.md). Phase 2 adds optional
isolated native compilation and authenticated native loading; compiler children
are temporary bounded workers, not guest execution cells. Trust-sharded guest
processes, state transactions and external asynchronous capability providers
remain later work.

[ADR-0026](../../adr/0026-require-explicit-execution-isolation-profiles.md) and
[RFC-0001](../../rfcs/0001-minimum-execution-isolation-profiles.md) define the
security-profile boundary. The delivered in-process cell is not a process-compromise
boundary. A workload that requires containment after compromise of the process
executing guest/provider/renderer/native-compatibility work requires a separate
fixed node-owned execution host and remains unsupported until that profile is
implemented and validated.

## Cell contents during an activation

- cell identifier and allocation class,
- isolated guest store and linear memory,
- bounded stack and table allocation,
- activation context,
- activation-local host bindings,
- budget counters,
- cancellation signal,
- temporary input/output buffers,
- trace and accounting state.

## Cell classes

The initial classes are `tiny`, `small`, `standard`, `large`, and policy-controlled `extra-large`. A capsule declares a ceiling, and admission chooses the smallest compatible class.

Fixed classes improve predictable capacity and reduce allocator fragmentation. They do not imply persistent service instances.

## Thread model

The standalone node owns a configured shared async runtime and fixed compiler
workers. Invocations are futures polled on that runtime, not dedicated
operating-system threads. Directory reads and native compilation use bounded
compiler jobs; no worker count grows with registered services. Wasmtime async
calls can yield, but an epoch tick alone is not a general scheduler fairness or
millisecond response guarantee. The optional fuel-yield policy and interruption
limits are documented in [the runtime reference](../runtime/wasmtime.md).

## Waiting activation ownership

[ADR-0028](../../adr/0028-retain-activation-ownership-across-asynchronous-waits.md)
clarifies ADR-0006 for Phase 3 asynchronous providers and descendant calls.
Yielding an invocation future releases the shared runtime thread for other work;
it does **not** release the activation's cell lease, Wasmtime Store, guest memory,
host bindings, budget or cancellation owner. A provider wait additionally keeps
its bounded operation permits and retained buffers charged until physical cleanup
or an explicitly specified affine transfer to a node-owned cleanup owner.

A child service call is a separate activation with a fresh Store and normal
scheduler assignment. The waiting parent keeps its own cell. Before the parent
can block on a descendant, the Phase 3 child-call implementation must either
establish progress inside fixed declared capacity or reject promptly. It may not
create hidden cells/workers, overcommit the pool, wait indefinitely on cells held
by its ancestor chain, or refund a still-live parent cell to manufacture capacity.

`WaitingProvider` and `WaitingDescendant` are ownership descriptions, not new
public lifecycle phases and not dormant-service states. LSF does not checkpoint
or evict an active guest stack in this phase. Reuse still requires affirmative
cleanup; a watchdog timeout identifies a failed bound but is not evidence that
provider work, descendants or the cell were actually retired.

## Isolation model

Each activation receives a separate guest store, memory, budget and host bindings.
A guest trap must terminate only that activation. Phase 3 plans the general broker
handle table. The current `local-experimental-v1` profile trusts the standalone
node, Wasmtime, host bindings and operating system. Guest Store limits constrain
guest-visible resources; they are not a complete process-RSS boundary.

This default covers T0 operator-trusted preparation and execution. Supporting
external/adversarial capsule admission also requires the enforced admission,
protected configuration and isolated compilation of the planned
`external-capsule-v1` profile. Guest sandboxing alone does not supply those
preparation and configuration boundaries.

A future stronger profile may use a fixed/bounded pool of trust-class execution
hosts. Host count must remain independent of service count. A failed, stuck or
compromised host may not return to the reusable pool until its supervisor has
terminated/reaped it; replacement capacity remains charged to the same node-owned
ceiling.

## Cancellation

Wall-clock deadlines and explicit cancellation are propagated through an `ExecutionCancellation` interface. Cooperative interruption is preferred. An execution backend must also provide a non-cooperative containment mechanism for runaway guest execution.

For the delivered in-process profile, a failure that cannot safely interrupt and
clean a guest cannot be converted into a guest-process containment claim. The
cell must not be reused; node-level recovery may be required. A future separate
host profile uses process termination and actual reap as its non-cooperative
refund boundary.

## Reuse safety

A cell may be returned only after:

1. guest execution is stopped,
2. capability handles are revoked,
3. host-call ownership is released,
4. temporary buffers are cleared,
5. accounting is finalized,
6. activation identity is removed, and
7. backend-specific memory reset guarantees hold.

For Phase 3 asynchronous work, "host-call ownership is released" means that
provider operations and descendant reservations have physically retired or were
affinely transferred to a bounded owner that cannot reference the old cell,
Store, guest memory or activation-local handles. Cancellation acceptance alone
does not satisfy this requirement.

Conformance tests must detect cross-activation data leakage.

## Measured engine and ownership tradeoffs

The [extension results](../phase-1-extension-completion.md#tuning-and-closure)
retain the on-demand/speed default and the measured pooling tradeoffs.
Pooling does not remove the fresh-store boundary or permit cell reuse
before execution and cleanup have retired. Prepared-cache capacity
describes retained code, not resident service instances or available cells.
