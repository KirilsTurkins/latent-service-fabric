# User-space state-pager research

[Draft RFC-0009](../../rfcs/0009-optional-mapped-state-and-fault-ownership.md)
proposes read-only image grants and owned fault/mapping retirement for review.

The userfault-pager track investigates loading explicitly structured state only
when accessed and tracking changed pages for later delta capture. **LSF has no
implemented userfault pager or guest mapped-state profile.** Explicit capability
calls remain the portable state contract; this Linux-specific optimization is
optional research.

## Current behavior and likely scope

The [state architecture](../architecture/state-and-effects.md) already provides
selective bounded record reads, consistent retained views and host-owned commits.
The [state WIT](../../wit/platform/state/package.wit) returns owned byte lists;
its `page` resource represents query results, not host memory pages. Paging a
source cannot avoid materialization if the next layer copies the whole value.

[Wasmtime](wasmtime.md) applies selected copy-on-write initialization and compact
pooling settings. Those do not persist mutable application heaps or install a
state pager. Any benefit must be measured over current reads, explicit chunks,
ordinary kernel-managed mappings and prefetch, with equivalent guarantees.

The first proposed scope is one bounded immutable data image in an isolated
harness. Guest-visible mapping and private writable overlays are later, separate
contracts; a native array experiment would not qualify the six SDKs.

## Fault handling changes the execution boundary

A page fault can block an OS execution thread rather than yield through
[asynchronous host I/O](async-host-io.md). Fuel, epoch checks and a client timeout
cannot alone retire an unresolved fault. Fault-service capacity, host-copy errors,
safe cancellation and stale responses after address reuse are primary gates.

Dirty pages do not establish transaction success, complete read dependencies or
serializability. Writes need private staging, a coherent authorized view and the
existing host-owned publication/recovery boundary. Fault counts cannot replace
logical state meters, and resident cache hits cannot become renewed authority.

## Evidence and next work

The [research overview](../../research/userfault-pager/README.md) links the
[kernel/engine and literature review](../../research/userfault-pager/upstream-review.md),
[proposed mapping model](../../research/userfault-pager/mapping-model.md) and
[evaluation plan](../../research/userfault-pager/evaluation-plan.md). They cover
exact feature/container preflight, failure recovery, snapshot consistency,
integrity, tracking epochs, engine allocation limits and complete mapping cleanup.
No kernel experiment or measured LSF speedup accompanies this review.

[Continuation eviction](continuation-eviction-research.md) saves unfinished
computation and releases a complete Store. Paging changes data residency while
execution ownership exists; it supplies no durable program counter, wait or
resume protocol. The tracks require independent evidence.
