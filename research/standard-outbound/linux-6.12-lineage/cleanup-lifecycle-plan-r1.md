# Cleanup task creation and physical stack retirement

This work continues the uninstalled source at development `94f1c0c`. It is one
combined lifecycle implementation, not another object-only qualification. The
original 512 KiB bank, 192 KiB infrastructure tail, 256 records, 64 owners,
TCP/DNS 96/64 KiB limits and 1 MiB bootstrap ceiling remain unchanged.

## Authenticated boundaries

The maintained source is Linux 6.12.113 commit
`7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e`, from the same completely authenticated
official archive. `finish_task_switch` drops the scheduler's stack reference
only after the old task is off its CPU and the runqueue lock is released.
`release_task_stack` separately requires TASK_DEAD; an external stack reference
can delay the actual last transition. `kthread_stop` waits for `mm_release`'s
completion, which precedes the final schedule and is not this boundary.

Ordinary VMAP return can run in interrupt context. It uses per-CPU cached
stacks or embeds an RCU callback in the old stack before `vfree`. Neither the
global cache, lazy VA free nor that deferred owner belongs to this private
request. The private final-stack hook therefore runs at the actual last-stack
reference, before ordinary `free_thread_stack`, and never calls the synchronous
unpublished abort from the exiting task or an interrupt.

## One original-owner handoff

The request already admitted in the original bank is the single retirement
slot. Its factory state is protected by the existing IRQ-safe pool lock. The
hook first resolves the exact born task address and complete root/request/task/
stack generations, then validates the actual stack and VM relationship. The
future complete constructor reserves a real, nonzero task reference at its
private publication transition, before task visibility. This reference protects
the real task even if an external stack reader outlives the scheduler/RCU usage
reference. Final stack capture consumes that original continuation without
incrementing or reviving task usage. A consumed, foreign, stale or duplicate
task cannot acquire a new owner by supplying a pointer.

The hook detaches both `task->stack` and `task->stack_vm_area` before publishing
the retirement slot. Once detached, ordinary VMAP cache/RCU return is never
entered for that task. One pending bit is read under the pool lock; no new
global pointer is needed. The producer never takes `kthread_create_lock`:
ordinary kthreadd holds that lock with interrupts enabled. No pool lock spans
wakeups, VM locks, callbacks, a task put, TLB work or completion.

Existing kthreadd observes pending retirement in its ordinary sleep condition,
claims it once, and processes it outside both creation and pool locks. It
requires the actual held task, zero stack references, TASK_DEAD, the detached
fields and complete generations. The existing maintained synchronous
`vunmap_range` plus conditional adjacent VA absorption runs from this control
context. Only after PTE/TLB/VA return and the stack child's final return does
the consumer drop the held task reference. The task/request/bank cannot be
returned earlier. A failed claim, mapping check, VA absorption or final return
poisons and retains all original owners and the real reference; there is no
automatic retry, overwrite, fallback queue or early refund.

Task structure release is a separate last-reference boundary. The actual
`free_task_struct` dispatch must recognize the born task before normal cache
free, and return its view only after the original task destructors and all
owned children have completed. A stack-returned flag alone is insufficient.

## Creation in the same source group

Advance the source-derived `dup_task_struct` through its unchanged post-stack
initialization and original accounting. Refuse genuinely unowned enabled
instrumentation before birth; do not disable configuration or silently omit
calls. Check the actual kthreadd `user_cpus_ptr` before the copied helper can
allocate. Preserve stack accounting, seccomp reset, notifier/stack-magic,
canary, reference initialization, optional field resets and the ordinary path.

Derive the real `set_kthread_struct` initialization with a child allocated from
the same bank before memset, completion initialization and publication into
`worker_private`/`vfork_done`. The existing request owns the fixed name. The
actual private final destructor validates those identities, preserves the
original BLK_CGROUP warning/retention condition, clears pointers before child
return and never sends bank/name storage to kfree. Failed creation reverses
only the initialization actually reached, before synchronous unpublished stack
and task return. Stop completion does not release request or stack ownership.

The present creator must still refuse and unwind before `copy_process`'s
unclosed PID/IDR, credential/ucount, signal/sighand, perf/delay accounting,
mandatory security/audit, scheduler/cgroup and publication descendants. The
publication transition for a future complete constructor is private and bound
to the actual kthreadd source; it is not a ready flag or caller certificate.

## Integrated qualification path and remaining gates

Next close the selected original constructor/error/final-free chains as one
bounded group, preserving active SELinux/audit and instrumentation. Authenticate
the actual running extended task geometry and aggregate bank use. Then a linked,
booted maintained image must exercise one accepted cleanup, failed creation,
stop while work is live, last-stack reference delayed by a real reader, and
post-switch final-stack/last-task return barriers. Actual RCU and synchronous
cross-CPU TLB completion, CPU hotplug, original kthreadd/control bootstrap
funding and failed-open backing retention require evidence. No existing global
task, stack, PID/IDR node or workqueue is retrospectively adopted.

No campaign is added by this source plan. Source and serialized C controls are
supplemental; they cannot establish actual scheduling, RCU grace periods,
running-task stack retirement, full allocation closure, installation or a
production provider. The selected normal consumer remains NULL and accounting
qualification remains false until the integrated requirements are met.
