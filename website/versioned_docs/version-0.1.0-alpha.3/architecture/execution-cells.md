# Execution-cell architecture

An execution cell is a reusable sandbox allocation slot. It is not associated with a service identity while idle.

The current node retains the Phase 1 fixed in-process cell pools, fresh Wasmtime stores and
affirmative reuse/quarantine through the [local scheduler](../scheduling.md)
and [activation lifecycle](../activation-lifecycle.md). Phase 2 adds optional
isolated native compilation and authenticated native loading; compiler children
are temporary bounded workers, not guest execution cells. Trust-sharded guest
processes, state transactions and external asynchronous capability providers
remain later work.

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

## Isolation model

Each activation receives a separate guest store, memory, budget and host bindings. A guest trap must terminate only that activation. Phase 3 plans the general broker handle table. Stronger guest process isolation remains a planned fixed set of trust-sharded execution hosts.

## Cancellation

Wall-clock deadlines and explicit cancellation are propagated through an `ExecutionCancellation` interface. Cooperative interruption is preferred. An execution backend must also provide a non-cooperative containment mechanism for runaway guest execution.

## Reuse safety

A cell may be returned only after:

1. guest execution is stopped,
2. capability handles are revoked,
3. host-call ownership is released,
4. temporary buffers are cleared,
5. accounting is finalized,
6. activation identity is removed, and
7. backend-specific memory reset guarantees hold.

Conformance tests must detect cross-activation data leakage.

## Measured engine and ownership tradeoffs

The [extension results](../phase-1-extension-completion.md#tuning-and-closure)
retain the on-demand/speed default and the measured pooling tradeoffs.
Pooling does not remove the fresh-store boundary or permit cell reuse
before execution and cleanup have retired. Prepared-cache capacity
describes retained code, not resident service instances or available cells.
