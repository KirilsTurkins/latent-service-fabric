# Proposed observer profile for the owned cleanup constructor

This finite profile was reviewed for unselected source development. Its concrete
implementation and full writer/retirement inventory are in
cleanup-observer-writers-r1.md. It remains unselected: the existing consumer
still refuses and no kernel build follows. This document states the proposed
contract; the companion inventory describes its actual enforcement details.

The authenticated selected config enables PROC_EVENTS, TRACEPOINTS, FTRACE,
KPROBES, OPTPROBES and KRETPROBES. FUNCTION_TRACER is disabled, but that does
not remove tracepoint registration or kernel probes. Perf attachment and
inheritable groups already have separate explicit unsupported-operation guards.

## Proposed finite contract

Before the original backing allocation, require no registered tracepoint
callbacks, kernel probes or process-connector listeners. While this one owned
programme holds its original Root, reject new admission of those observers with
a real unsupported error. This is a global observer restriction for this bounded
profile, not a claim that observers are naturally absent. All ordinary event
calls, notifications and error paths remain. No callback is silently skipped.
Do not disable a kernel config, overwrite an existing probe or detach an
existing listener to make admission succeed. If any existing observer prevents
admission, return before the original bank/Task allocation.

Each seal is stored in its original subsystem's static metadata. Actual sizeof
of all extra static metadata must be included in the same existing bootstrap
ceiling before allocating backing. These seals are admission serialization, not
allocation owners, Task origins or a second lifetime ledger.

Acquire the three subsystem seals sequentially, without holding another
subsystem's mutex. Before any original bank admission, failure may unwind
previously acquired seals; no private Task or source exists then. After actual
bank admission, keep every successful seal until the real last Root/native
backing release. Current physical backing release remains unqualified, so no
post-birth unseal or generic reuse is currently proposed.

## Actual tracepoint sites and lock order

In authenticated kernel/tracepoint.c, every public registration path enters
tracepoint_add_func under tracepoints_mutex. The new sealed check belongs at
the start of tracepoint_add_func, before tp->regfunc and func_add. It must
return -EOPNOTSUPP and retain each original public caller's real error return.

Seal acquisition must take tracepoint_module_list_mutex BEFORE
tracepoints_mutex. Existing tracepoint_module_coming holds the module-list
mutex while invoking its notifier chain, whose consumers may register probes.
The reverse order would introduce a deadlock. With both actual mutexes held,
scan built-in tracepoints and the actual module list directly, checking every
tp->funcs with rcu_dereference_protected. Do not call the public module iterator
while already holding its mutex. Refuse if any callback array exists, then
publish sealed under tracepoints_mutex. A later module cannot register a new
callback through tracepoint_add_func. Module tracepoint metadata initialized
with preexisting callbacks must be rejected at actual module admission, before
publishing that module's tracepoints; normal metadata remains initialized NULL.

The proposal must additionally bind every actual funcs publication to this
central helper and preserve ordinary removal/RCU cleanup. An unlocked read of
a static key, NULL callback pointer or empty module list is insufficient.

## Actual kernel-probe sites

In authenticated kernel/kprobes.c, register_kprobe mutates kprobe_table under
kprobe_mutex. Add sealed rejection under that mutex before table lookup,
preparation or arm, preserving its out/module_put cleanup. Seal acquisition
checks every actual table bucket under the same mutex and refuses even disabled
registered probes. Thus no preexisting enable operation can become an admission
escape. register_kretprobe ultimately calls register_kprobe; retain its actual
rethook/objpool failure cleanup and real error propagation.

CONFIG_OPTPROBES=y matters. Actual unregister_kprobes removes/disarms under
kprobe_mutex and then runs synchronize_rcu and final arch removal outside it.
Actual wait_for_kprobe_optimizer acquires that mutex itself and flushes
optimizing_work without holding it. After closing new registration, require
the real optimizer drain and real RCU synchronization outside the mutex before
any bank allocation. Recheck empty actual table/optimizer lists under the
original mutex afterwards. Verify the selected arch/rethook unregister tails
before implementing; an empty table alone does not certify delayed trampoline
retirement. This remaining source proof is part of this proposal, not assumed.

## Actual process-connector sites

In authenticated drivers/connector/cn_proc.c, proc_fork_connector returns
before send_msg only when atomic proc_event_num_listeners is less than one.
send_msg otherwise calls the actual allocating connector multicast path.
cn_proc_mcast_ctl can increment that count on LISTEN and allocates sk_user_data
with GFP_KERNEL before changing subscription state. Serialize actual LISTEN
admission and seal acquisition with a new charged static mutex. Reject LISTEN
under it before the original allocation/state mutation; preserve the original
error response outside it. The original multicast cn_proc_ack does not transmit
when count is zero, so the concrete implementation uses the same ACK format
with the real requestor portid for first-LISTEN refusal. The complete original
has one increment and one decrement, both in this control function; no separate
release count writer exists. IGNORE remains functional. Bind both actual count
writers to this mutex; refuse seal if the actual count is nonzero.
Do not forge zero or use an unlocked zero observation.

## Uprobe and selected scheduler route

These routes do not need a fabricated observer absence claim. The private clone
selector now rejects a current kthreadd with a non-NULL mm before Task birth.
Original copy_mm initializes child mm NULL and returns for that real parent.
With the exact non-VFORK flags, real uprobe_copy_process returns before
dup_utask when parent mm equals child mm, even if a parent uprobe_task exists.
Retain that complete original function, its errors and ordinary fork semantics.

The exact selected config has no CONFIG_SCHED_CLASS_EXT definition. Actual
kernel/sched/ext.h provides empty scx_pre_fork/post_fork/cancel_fork stubs and
scx_fork returning zero. The original selected sched_fork/sched_post_fork and
fair-class task_fork_fair remain. This does not pay for the scheduler, shared
runqueues or other original NodeFixed state.

## Remaining completion evidence

The owned constructor now has actual Task/stack/metadata, descendants, PID/IDR,
Root security, perf, audit, I/O, cgroup, clone/entry/association and close source
routes. The full consumer remains disconnected until:

* This observer contract and exact enforcement/retirement source are reviewed.
* All enabled scheduler/x86/LSM hooks and actual worker callback transitions
  are mapped to their selected real providers, including later audit work.
* Actual original kthreadd, IRQ/RCU/TLB/per-CPU, shared PID/IDR, cgroup and other
  NodeFixed/bootstrap carriers are funded under the existing ceiling.
* Actual runtime geometry, complete 192 KiB/256-record fit, real final IRQ/RCU
  execution and physical backing/native final-free are established.

Source recomposition, metadata controls, stop completion and original view
returns do not establish any of these remaining runtime/native facts.
