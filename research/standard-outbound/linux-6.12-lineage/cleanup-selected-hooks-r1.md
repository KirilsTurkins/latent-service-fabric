# Actual selected constructor hook map

The complete selected.config is the existing #1343 actual object artifact:
143192 bytes, SHA256
`b2bcccd5507f3f3a673690b660a2321870b57a3c77e72ce8532975f3c4752176`.
The following source selections refer to complete authenticated Linux originals
at `7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e`, not to a changed config or an
unlocked runtime absence guess. They describe the current constructor shape;
they do not certify the full image, original NodeFixed providers or runtime fit.

## Scheduler and architecture

Actual sched_fork calls the original __sched_fork, TASK_NEW transition,
priority/policy handling, scheduler-class selection, runnable-average init,
embedded sched_info reset and preemption/SMP setup. SCHED_INFO and SCHEDSTATS
are enabled; their actual structures are embedded in the real charged Task,
and their original initialization remains. Real init_dl_entity initializes its
embedded rb-node and two actual hrtimers; no invented timer completion replaces
their normal cancellation/exit paths.

The selected UCLAMP_TASK is disabled. Actual core.c selects its empty inline
uclamp_fork/post_fork stubs. SCHED_CORE and SCHED_AUTOGROUP are disabled. Actual
include/linux/sched/autogroup.h supplies the empty signal-fork/exit stubs.
NUMA_BALANCING is disabled, while NUMA itself is enabled: the separate owned
full mempolicy copy and real final put are still needed and remain implemented.

CONFIG_SCHED_CLASS_EXT has no definition in the complete selected config.
The actual kernel/sched/ext.h is authenticated and selects empty
scx_pre_fork/post_fork/cancel_fork plus scx_fork returning zero. The actual
fair-class selection retains original task_fork_fair and its actual
set_task_max_allowed_capacity. No scheduler option was disabled by these layers.
Shared cfs/runqueue, affinity/migration and per-CPU infrastructure remain
original NodeFixed/bootstrap obligations; an empty per-Task hook does not pay
for those providers.

Actual x86 copy_thread receives the non-NULL fixed function and calls the full
original fpu_clone. Its actual kernel-thread branch resets/initializes the
embedded fpstate before the user dynamic-state branch. X86_USER_SHADOW_STACK is
disabled in this selected config. Actual Task allocation geometry still comes
from arch_task_struct_size and the original alignment, not a guessed C sizeof.

The copied initializer inspects parent user_cpus_ptr under its actual pi_lock,
clears the borrowed destination field and refuses the unsupported nonempty
profile through real unwind. It does not certify the original racy unlocked
NULL check. Entry retains actual scheduler reset and affinity operations;
their original shared migration/CPU providers must still be funded.

KCOV, KASAN and DEBUG_LOCK_ALLOC are disabled; CONFIG_KMSAN and CONFIG_SCS have
no selected definitions. The private initializer also explicitly refuses its
unsupported enabled instrumentation shapes before its Task claim. Original
calls/stubs remain; no profiler or diagnostic outcome is invented. USER_EVENTS
and BPF_SYSCALL are disabled. The complete maintained copy_process success and
bad_fork bodies retain their original configured hooks/error ordering.

## Shared fixed-shape namespaces, credentials and uprobes

The exact clone flags include CLONE_FS, CLONE_FILES, CLONE_VM and
CLONE_UNTRACED, plus the real kernel-thread marker and SIGCHLD. Unsupported
namespace, thread-group, pidfd, userspace-stack/TLS and cgroup-migration args
are rejected before birth by the authenticated fixed request selector.

Actual copy_fs takes its original fs lock, checks in_exec and increments the
shared users count before returning. Actual copy_files increments the original
files count and returns before dup_fd. Actual copy_namespaces selects the
no-new-namespace and CLONE_VM path, takes the existing nsproxy reference and
returns before create_new_namespaces. The fixed shape does not create a new
user namespace; actual copy_creds therefore avoids create_user_ns and
set_cred_ucounts. Its new cred/security storage and real shared group/user/ns/
key/ucount references remain the complete maintained private route. Existing
referenced objects are original provider lifetimes, not free copied budget.

The private request selector explicitly requires actual kthreadd with NULL mm.
Original copy_mm sets child mm/active_mm NULL and returns for that parent.
Actual uprobe_copy_process first clears child utask and returns before dup_utask
when parent/child mm are equal and CLONE_VFORK is absent. Both conditions are
the real selected shape; the whole ordinary function is retained. UPROBES and
KRETPROBES remain enabled. Kernel probes and their real return hooks use the
separate reviewed observer profile, not this uprobe selection fact.

## Compiled LSM and initial audit hooks

The exact security/Makefile always selects commoncap and gates every other
registered LSM object on its own config. The selected compiled Task/credential
provider is SELinux. Smack, Tomoyo, AppArmor, Loadpin, Yama, Safesetid, Lockdown
and Landlock are disabled; BPF_LSM and SECURITY_IPE have no selected definition.
The LSM order string naming them does not compile their object directories.
INTEGRITY and INTEGRITY_AUDIT are enabled, but IMA/EVM are disabled. Actual
integrity/iint.c registers no Task/cred LSM hook. Its existing inode state is a
separate provider; no universal integrity exemption is inferred.

Actual commoncap hook registration contains no task_alloc/task_free or
cred_prepare/cred_free hook. Actual SELinux task_alloc is the maintained
PROCESS/FORK decision with real audit and the explicit original Task-birth
Root carrier. Its blob_sizes contributes no lbs_task, so the actual composite
Task blob may be zero. Full composite initialization and every actual selected
free hook remain. Actual cred_prepare copies into the paid real credential
security child; real security_cred_free and RCU last put precede physical return.

Actual tty_audit_fork only copies audit_tty into the zero-initialized owned
signal. The initial tty_audit_buf remains NULL. Actual tty_audit_exit returns
before push/free when that real buffer is absent. This does not exempt later
TTY operations. AUDIT/AUDITSYSCALL remain enabled and initial audit context/key
allocation/filter/error behavior is preserved. Actual dummy starts zero;
AUDIT_CTX_UNUSED is not a blanket allocation exemption. Module/helper and
other selected worker operations require their real provider/error boundaries.

## Remaining independent evidence

The complete selected cgroup subsystem registration inventory is in the
cgroup source fixture; actual I/O-context inheritance and late setter paths
are in the I/O source layer. Observer writer/retirement details are in
cleanup-observer-writers-r1.md. Module/helper operation proposals are in
cleanup-worker-operations-proposal-r1.md. None selects the full consumer.

Actual supported worker producers and their quiescence before stop still need
their real source ownership; stopping an empty worker alone does not prove a
device programme's producer graph drained. Original kthreadd, shared namespace/
credential/scheduler/cgroup/PID providers and IRQ/RCU/TLB/per-CPU state still
require original NodeFixed/bootstrap funding. Runtime geometry/complete fit,
actual final callbacks, physical pages/native return and production gates
remain unqualified.
