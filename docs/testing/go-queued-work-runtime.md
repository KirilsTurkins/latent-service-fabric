# Independently owned Go queued work

The opt-in `go-component-activation-v6` compiler profile extends v5 with one
original `QueuedWork` reservation per live logical goroutine. Admission reserves
the task and then its queue owner before `gfget`, `malg` or scheduler publication.
A refused queue rolls back the unpublished task; unconfirmed rollback traps and
leaves uncertainty with the original activation. Park, wake and compiler
checkpoint cycles retain the same queue owner. Destruction confirms queue
settlement before task settlement.

The eight existing, source-pinned maintenance slots also prepay their queue
owners before runtime initialization. Selecting a GC slot during canonical
lowering performs no new component import. The original dispatcher-idle checks
still precede maintenance retirement, and retired identities still fence late
resumes. Eight is the existing maintenance allowance, not an application task
ceiling. Heap, stack and queue storage remain inside the original limited Wasm
memory; this profile does not separately qualify every physical memory cost.

The conservative reservation covers both runnable and parked work that can
resume. A v6 deployment therefore needs queue capacity for its maintenance slots
and application goroutines. Existing v1 through v5 selections retain their
previous transformations; the default `go-component-async-v1` selection remains
unchanged. The separate v5 raw-stream selector does not implicitly accept v6.

`go-queued-work.yml` prepares one normal captured component from the existing
unchanged outside resource library and its transitive data module. The same
component is signed for independent tenants under fixed task16 and queue8,
queue9 and queue16 profiles. Queue8 must refuse the first application admission;
queue9 must permit ordinary fresh work, refuse parallel child admission and then
permit fresh work again. Queue16 must pass the original thirteen-outcome
resource, callback, cancellation, deadline, trap and tenant-reuse programme.
Every case requires physical retirement and provider cleanup. Other original
owner limits and application budgets stay fixed.

The initial `729531d` campaign refused the stale v5 capture selector before
compilation. The corrected `2a9fc15` campaign completed all 22 normal build
commands and produced the original 3,219,953-byte component
`d5e6d61d5d21fa42a3877ef7f00d1eff825cb1afd982b187ede5ef9af8d3e31f`.
Its old 357e signer then refused the unrecognized v6 provenance profile, before
any guest execution. Both campaigns remain failed.

The new native cohort builds the affected CLI, daemon and signer example, and
inherits the unchanged package and contract examples from f625. It adds v6 to
the closed Go provenance list while keeping an unknown v7 profile refused.
The owning programme uses those authenticated products through the existing
normal build and signing path. It builds one guest and performs no host or
engine build. Per-case invocation and retirement progress use separate files,
preserving the original exclusive-create evidence behavior.

The [signed programme](evidence/go-queued-work-signed-2026-10-21.json) passed
all25 outcomes at source `d889f0d3ec911c43375ac0679528c3303bad95fb`: six
pre-entry grant denials and19 entered guest executions across the three queue
ceilings. Every case records five physical owners and18 active provider counters
retired; all three nodes and peers stopped cleanly. One ordinary guest was
compiled. The native cohort retains its original three-current/two-inherited
product attribution. A later Clippy-only semicolon in an admission test is
recorded separately and does not rewrite that actual native/source snapshot.

The complete cost matrix, result/host buffers, production streams and the
remaining #742 requirements stay open.
