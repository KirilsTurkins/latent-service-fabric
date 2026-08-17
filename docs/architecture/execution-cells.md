# Execution-cell architecture

An execution cell is a reusable sandbox allocation slot. It is not associated with a service identity while idle.

## Cell contents during an activation

- cell identifier and allocation class,
- isolated guest store and linear memory,
- bounded stack and table allocation,
- activation context,
- capability handle table,
- budget counters,
- cancellation signal,
- temporary input/output buffers,
- trace and accounting state.

## Cell classes

The initial classes are `tiny`, `small`, `standard`, `large`, and policy-controlled `extra-large`. A capsule declares a ceiling, and admission chooses the smallest compatible class.

Fixed classes improve predictable capacity and reduce allocator fragmentation. They do not imply persistent service instances.

## Thread model

The node owns fixed compute and I/O worker pools. Invocations are asynchronous tasks, not operating-system threads. Guest execution consumes a compute worker only while running. Async capability operations yield execution and return the worker to the pool.

## Isolation model

Each activation receives a separate guest store, memory, budget, and handle table. A guest trap must terminate only that activation. Stronger process isolation can be provided by a fixed number of trust-sharded execution hosts.

## Cancellation

Wall-clock deadlines and explicit cancellation are propagated through an `ExecutionCancellation` interface. Cooperative interruption is preferred. An execution backend must also provide a non-cooperative containment mechanism for runaway guest execution.

## Reuse safety

A cell may be returned only after:

1. guest execution is stopped,
2. capability handles are revoked,
3. state transaction ownership is released,
4. temporary buffers are cleared,
5. accounting is finalized,
6. activation identity is removed, and
7. backend-specific memory reset guarantees hold.

Conformance tests must detect cross-activation data leakage.
