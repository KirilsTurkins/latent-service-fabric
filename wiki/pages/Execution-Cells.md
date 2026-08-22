# Execution Cells

> **Document role:** Conceptual explanation. The authoritative requirements are the execution-cell architecture, ADRs, and conformance tests.

## Definition

An execution cell is a reusable sandbox allocation slot. While idle it has no service identity and is not a dormant service process.

A node owns a fixed, policy-configured pool. Active work leases cells; completed or durably suspended work releases them.

## Contents during an activation

A leased cell may contain:

- cell identity and allocation class;
- an isolated guest store and linear memory;
- bounded stack and table allocation;
- activation identity and context;
- an opaque capability-handle table;
- budget counters and deadline state;
- cancellation signaling;
- temporary input and output buffers;
- trace and accounting state.

All activation-owned material must be removed or reset before reuse.

## Cell classes

The initial architectural classes are `tiny`, `small`, `standard`, `large`, and policy-controlled `extra-large`. A capsule declares a ceiling and admission chooses the smallest compatible class.

Fixed classes support predictable capacity and lower fragmentation. They do not imply preassigned service instances.

## Worker model

The node owns fixed compute and I/O worker pools. Invocations are asynchronous tasks, not operating-system threads.

- Guest code occupies a compute worker only while executing.
- An asynchronous capability operation yields and returns the worker to the pool.
- A logical activation may remain pending without monopolizing an OS thread.
- Durable suspension releases the entire cell.

## Isolation

Every activation receives separate guest memory, store, budget, and handle table. A guest trap should terminate only that activation.

Stronger blast-radius containment can use a fixed number of trust-sharded execution-host processes. Arbitrary native compatibility may require an ephemeral process, container, or microVM, but that is a fallback rather than the normal capsule model.

## Reuse protocol

A cell is reusable only after all of the following are true:

1. guest execution has stopped;
2. capability handles have been revoked;
3. state transaction ownership has been released;
4. temporary buffers have been cleared;
5. accounting has been finalized;
6. activation identity has been removed;
7. backend-specific memory reset guarantees hold.

Conformance and leak tests must detect cross-activation disclosure of input, output, state, handles, or secrets.

## What a cell is not

| Cell | Not equivalent to |
|---|---|
| Generic allocation slot | Service instance |
| Temporarily leased | Permanently assigned worker |
| Sandboxed guest context | Shared trusted plugin address space |
| Fixed node capacity | Autoscaled process per service |
| Reclaimable | Required resident cache entry |
| Budgeted execution | Unbounded thread |

## Capacity planning

Plan nodes by cell classes and counts, compute workers, I/O concurrency, bounded caches, provider-pool bounds, expected active concurrency, and trust-class partitions. Do not plan one heap, listener, or connection pool per registered service.

## Proof obligations

The implementation must demonstrate:

- constant process, OS-thread, socket, and cell counts while dormant release count grows;
- bounded memory, file descriptors, handles, timers, and provider leases after repeated calls;
- no cross-activation memory or handle leakage;
- correct containment of traps, deadline violations, and cancellation;
- compatible semantics across inline, isolated-local, and remote bindings.

## Canonical sources

- [Execution-cell architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/execution-cells.md)
- [Data-plane architecture](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/architecture/data-plane.md)
- [Test invariants](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/docs/testing/invariants.md)
- [ADR 0005: forbid per-service idle execution allocation](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/adr/0005-forbid-per-service-idle-execution-allocation.md)
- [ADR 0006: reusable generic execution cells](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/adr/0006-use-reusable-generic-execution-cells.md)
- [ADR 0017: fixed trust-class execution hosts](https://github.com/KirilsTurkins/latent-service-fabric/blob/release/adr/0017-use-fixed-trust-class-execution-hosts-for-stronger-containment.md)
