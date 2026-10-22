# Concrete unselected observer source and retirement inventory

This implements the reviewed finite opt-in observer profile in source. The
factory calls neither observer-enter nor full worker-create; the original
pending consumer still refuses. No seal, Linux kernel build, callback, RCU/IRQ
execution, native ledger, physical backing return or production gate is claimed.

`tools/host_stream_kernel_cleanup_observer.py` authenticates fourteen complete
originals, twenty-one complete original functions and the exact selected
configuration. New official Git captures recompute each Git blob identifier;
they do not claim membership of the earlier kernel archive. Original source is
Linux 6.12.113 at `7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e`.

## Tracepoint writers and modules

Actual kernel/tracepoint.c has five `rcu_assign_pointer(tp->funcs, ...)` sites:
two in tracepoint_add_func and three in tracepoint_remove_func. Both actual
registration entry paths call the former under tracepoints_mutex; the actual
unregister entry calls the latter under that mutex. The add guard returns
-EOPNOTSUPP before tp->regfunc, func_add, allocation or callback publication
when explicitly sealed. Removal and its real stub-on-allocation-failure path
remain intact. The one actual static-call update remains in the original
tracepoint_update_call, still selected only by the original add/remove logic.

All normal funcs publication/removal algorithms project byte-for-byte to the
whole maintained originals when the private inserted blocks are removed.
Notification calls and static keys are not replaced with a forced no-op.

The original module list excludes bad-taint modules. Therefore a list scan
alone cannot establish absence. Additional static registration metadata counts
the actual empty-to-published and published-to-empty tracepoint heads at those
same publication boundaries, under tracepoints_mutex. Array replacement does
not change the count. Stub arrays remain present and conservatively refuse
admission until actual removal. Overflow or inconsistent removal records sticky
uncertainty, and profile admission refuses. This count is registration
serialization metadata; it does not own allocations, attach Task origins,
refund a budget or replace any original source record.

The module-coming check precedes the original bad-taint early return and first
repeats that actual bad-taint predicate under module-list -> tracepoint mutexes.
Bad-taint metadata is never scanned: the maintained original avoids it because
mismatched headers can crash the kernel. Before sealing it records sticky
unknown state and preserves the ordinary return zero; during a seal it refuses
that module with -EOPNOTSUPP. Only good-module metadata is scanned under those
locks. Unexpected prebound callbacks are refused during a seal. Before sealing,
ordinary module loading remains unchanged and records uncertainty, preventing
unsupported prebound metadata from later being mistaken for absent. The
normal DEFINE_TRACE initialization has NULL funcs; ordinary registered
callbacks are admitted only by the actual central registration helper.

Seal acquisition takes tracepoint_module_list_mutex before tracepoints_mutex,
matching the original documented nesting and original module notifier path.
It refuses any active-head count, uncertainty or actual built-in/module funcs
array. It sets the admission seal under the original mutex, releases both,
calls the maintained tracepoint_synchronize_unregister (real SRCU plus RCU),
then takes the same two mutexes for the final complete recheck. No public module
iterator is called while recursively holding its mutex.

## Kernel probes, return probes and actual retirement

Actual kernel/kprobes.c has one kprobe_table hlist insertion in register_kprobe,
one aggregate hlist replacement reached from that guarded registration, and
three deletions: optimized unused-probe cleanup, registration arm failure, and
__unregister_kprobe_top. All mutate under actual kprobe_mutex. Table heads are
initialized by original kernel init, before this factory is available. The
ordinary module kill path leaves GONE entries registered; any such nonempty
bucket conservatively refuses admission. Existing disabled registrations also
refuse; no probe is detached, forcibly disabled or relabelled absent.

The actual register_kprobe guard runs under that mutex before aggregate-probe
preparation, prepare_kprobe, table insertion or arm. It retains original out and
module_put cleanup. Selected KRETPROBE_ON_RETHOOK=y is authenticated. The whole
original register_kretprobe is retained as a private implementation, with a
small public wrapper. Under kprobe_mutex the wrapper either refuses immediately
or reserves its complete in-progress preparation extent before the original
function, including rethook/objpool allocation. Its end runs after every real
return. A concurrent seal refuses any active preparation; no unlocked
precheck is treated as a before-allocation guarantee.

The two real plural unregister functions are also retained whole behind
wrappers. Each wrapper records an actual in-progress retirement before calling
the original and ends only after it returns. Both originals perform their
actual __unregister_kprobe_top/disarm, synchronize_rcu and
__unregister_kprobe_bottom/arch removal. The selected return-probe path calls
rethook_free under the original mutex. Real rethook_stop publishes handler NULL;
real rethook_free queues rethook_free_rcu; the actual trampoline reads that
handler and invokes it only when non-NULL. The wrapper does not manufacture any
of these completions. Counter overflow or inconsistency creates sticky
uncertainty; it never suppresses ordinary unregister cleanup.

Seal acquisition refuses all preparation, retirement, uncertainty and every
nonempty actual table bucket under kprobe_mutex. After publishing the admission
seal there, it drops the mutex and calls the actual wait_for_kprobe_optimizer,
flushes the actual optimizing_work, performs actual synchronize_rcu and
rcu_barrier, then reacquires the mutex and rechecks the complete table and all
three optimizer lists. No empty-table observation before those tails is
accepted. New registration cannot enter during the waits.

Selected OPTPROBES=y uses the maintained optimizer: actual text unoptimization,
synchronize_rcu_tasks, remaining optimization, cleaned-probe physical return,
and its epilogue all finish under the original locks before the flush returns.
Authenticated x86 arch_disarm_kprobe and arch_unoptimize_kprobe retain real
text_poke_sync; arch_remove_kprobe retains actual instruction-slot return.
The RCU barrier also completes already queued rethook_free_rcu -> objpool_fini.
Stopped, handler-NULL rethook nodes can remain referenced on older ordinary
Tasks until their real return/recycle. Their physical storage remains original
NodeFixed lifetime state. No callback-absence check certifies their physical
free, includes them in the private Root, or refunds their original carrier.
That original funding remains part of the separate bootstrap/native gate.

## Process connector control and refusal reply

In the complete cn_proc.c there is exactly one listener increment and one
decrement, both in cn_proc_mcast_ctl. There is no separate release counter
writer in this maintained source. The private insertion acquires a new static
mutex after original request/namespace/event validation and before userdata
allocation, subscription mutation or count change. Under an explicit seal,
LISTEN is refused before that original allocation. Ordinary LISTEN, IGNORE,
invalid-operation handling, count updates and original acknowledgments retain
their full actual algorithms. Every exit after locking releases the mutex;
all replies run outside it.

Original cn_proc_ack returns without sending if listener count is zero. Calling
it for the first refused LISTEN would therefore silently drop the unsupported
error. A separate refusal function preserves its exact original cn_msg and
proc_event ACK fields, including request seq/ack and positive EOPNOTSUPP. It
uses authenticated nsp->portid and the actual cn_netlink_send_mult unicast
branch with group zero, without requiring or creating a listener. The ordinary
multicast acknowledgment is unchanged. This error response retains the
connector's normal transport-allocation/failure behavior; a reply failure does
not admit a subscription or create private Task ownership.

Seal acquisition holds the same subscription mutex and requires exact atomic
count zero. A negative count is not certified as absent. New LISTEN cannot
race the check. Actual proc_fork_connector and all other producers remain
unchanged and take their original no-listener return, before send_msg and its
actual allocating multicast path. No notification call is skipped.

## Original ceiling and prebirth rollback

Each subsystem returns the defining TU's sizeof of its complete static seal
aggregate. Connector mutex/padding and all tracepoint/probe fields are included.
The existing factory aggregate includes its actual prebirth flag. The original
pre-allocation ceiling check now bounds fixed original bytes, actual IRQ hint
and all observer aggregates with ordered subtraction, avoiding underflow. No
caller supplies a byte cost, ownership token or closure assertion.

The prepared factory entry requires its original mutex and actual no-bank,
no-opened, no-device, no-uncertainty state. It acquires subsystem seals
sequentially; partial failure rolls back only previously acquired seals, before
bank birth. A prepared all-success rollback additionally requires its actual
prebirth flag and still no pages/opened/device. There is no post-birth unseal
or physical-final-free API. The entry/rollback are marked unused and are not
called by any consumer in this source state.

Remaining before selection: root review of this concrete source; complete
selected scheduler/x86/LSM and actual worker/audit transition mapping; original
NodeFixed/bootstrap funding, actual runtime geometry/fit, real IRQ/RCU results
and physical backing/native final-free. All production/closure gates stay false.
