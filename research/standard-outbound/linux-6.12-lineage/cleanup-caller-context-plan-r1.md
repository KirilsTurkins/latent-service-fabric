# Final stack caller contexts and the private IRQ relay

The prior eight-file source group is frozen separately and root-reviewed. This
continuation is not installed, runtime-qualified or published as a provider.
No build campaign is proposed. The original backing/occupancy/record limits
remain unchanged.

## Complete literal reference inventory

The same held official Linux 6.12.113 archive was hashed before and after a
streaming scan of all 92,471 members / 1,480,537,904 expanded bytes. All literal
`put_task_stack` and `try_get_task_stack` references occur in 17 whole files
(711,084 bytes). A second complete scan collected all references to their
generic task-stack readers (2,003,633 bytes). These are token inventories, not
proof of a transitive or dynamically selected call graph. The exact actual
configuration remains separately bound to the passed four-object receipt.

For selected x86 / THREAD_INFO_IN_TASK / VMAP_STACK, direct users are:

* `finish_task_switch`: after the old task stops and the runqueue lock drops.
* `copy_process` failure: its original unpublished failure cleanup.
* x86 `__get_wchan`: invoked by `get_wchan` while the real target `pi_lock`
  is held with IRQs disabled. A stack reader that began before exit may
  retain the stack after the scheduler's put. Concurrent readers can then
  make a later get-wchan put the last one; merely requiring TASK_DEAD does
  not establish a lock-free caller.
* `sched_show_task` and generic `stack_trace_save_tsk{,_reliable}`: used by
  process diagnostics, RCU stall reporting and other scheduler diagnostics.
  RCU stall readers hold their original `rnp` lock. That observation alone
  does not prove a final put there: blocked-reader removal / `rcu_exit`
  ordering must also be respected.
* proc stat and `collect_syscall`: process readers. A private kernel thread
  has no mm, which excludes the proc-stat register branch for that task.

The actual baseline has BPF_SYSCALL, DEBUG_KMEMLEAK, LATENCYTOP and BCACHEFS
disabled. Their source users are not selected; no config was disabled by this
work. Generic task-stack and scheduler diagnostic APIs remain exported and
MODULES is enabled. There is no sealed loaded-module / instrumentation proof,
so NMI absence is not established. IRQ-safe locking does not solve that gap.

## Actual maintained IRQ primitive

The authenticated `kernel/irq_work.c` explicitly supports NMI-safe local
`irq_work_queue`. Remote `irq_work_queue_on` explicitly does not. The selected
source must use one embedded descriptor and local queue only, marked HARD;
there is no lazy queue, worker-thread creation or remote fallback. A real
`arch_irq_work_has_interrupt()` result, existing IRQ_WORK and non-RT x86/APIC
selection are checked before task publication. No operator boolean supplies
these facts.

`irq_work_single` clears PENDING, executes the callback, then clears BUSY and
may still access its descriptor. `irq_work_sync` must therefore run in kthreadd
with IRQs enabled and no pool/creation/VM locks before any descriptor/request
can return. In the selected non-RT/APIC branch, the post-BUSY condition short
circuits without another descriptor read; other branches use the original
RCU synchronization and are not silently treated as equivalent.

## Proposed source handoff

Reserve the actual `sizeof` embedded IRQ descriptor and atomic state in the
already admitted request before creation. Before visibility, validate the
exact born task, root/request/task/stack generations and actual VM/metadata,
hold the original real task reference, initialize the descriptor and publish
one immutable birth hint with release/acquire ordering. The hint is not an
allocator, public registration or a second ownership ledger. Actual release
continues to require the original factory records.

The potentially NMI/locked last-put hook only compares that exact born address
and immutable generation/range data, atomically wins a single enqueue, and
calls the actual local IRQ queue. It never reads mutable pool records, acquires
pool/VM/rq locks, detaches task fields, acquires a new task ref or directly
wakes kthreadd. Duplicates or an unknown bank-interior address mark uncertainty
without repeating the enqueue or reaching the ordinary allocator.

The hard-IRQ callback only publishes the wake indication and wakes existing
kthreadd. It does not validate/return owners or touch VM state. The retained
task/request/bank protects both hint and callback epilogue. Kthreadd claims the
single indication, synchronizes the actual IRQ descriptor, then performs the
existing full generation validation, stack detachment, synchronous unmap/TLB,
conditional VA return, child return and final task put. No wake or callback is
performed while any original pool/creation/VM lock is held.

## Hotplug, accounting and actual qualification remain open

`smpcfd_dying_cpu` flushes queued calls and invokes `irq_work_run`. It does not
by itself prove that a later NMI cannot enqueue after the final local flush.
No successful drain or CPU-offline ordering is inferred from those calls.
The single descriptor, actual task ref and original bank remain retained on
unknown / undelivered work. There is no fallback remote IPI, automatic retry,
synthetic completion or quarantine release.

A supported integrated profile still needs the complete actual caller/order
proof or a separately reviewed real hotplug admission fence, bounded possible
CPUs, and original NodeFixed ownership for per-CPU IRQ/SMP/IPI infrastructure
and mandatory tracing callbacks. Existing queues or CPUs are not adopted by
retrospective accounting. The actual SMP preparation allocates cpumasks and
per-CPU call descriptors; those bootstrap owners remain explicit requirements.

The next combined constructor work also must replace only the private kthread
entry's original `kfree(create->full_name/create)` interrupted-creator escape
with the real retained request lifecycle. Full original PID/IDR, credentials,
signal/sighand, delay/perf/cgroup/security and final RCU descendants remain
mandatory before any worker is published or an integrated runtime run starts.
