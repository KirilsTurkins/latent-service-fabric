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
owner limits and application budgets stay fixed. The campaign reuses the
historically identified 357e native products and builds no host or engine.

Source controls and the authenticated Go source derivation pass locally.
Actual signed v6 execution is pending; this guide records the intended owning
programme and grants no qualification from source inspection alone. The full
cost matrix, result/host buffers, production streams and the remaining #742
requirements stay open until their own evidence is complete.
