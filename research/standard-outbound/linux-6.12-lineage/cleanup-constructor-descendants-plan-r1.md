# Remaining actual constructor descendants

The lifecycle, entry and IRQ-relay source packets are frozen separately. This
inventory uses the authenticated maintained 6.12.113 originals and changes no
kernel configuration, capacity or production selection. No constructor below
is currently called as a successful full private copy_process implementation.

## Next coherent source group

Implement actual credentials and their composite LSM blob, signal/sighand,
delay accounting, plus once-only final-task child drain as one constructor
group. Every new physical object must be born from the same original request/
task ancestry before its first write. Original full generations, actual
kthreadd constructor extent, actual size/alignment and finite records are
checked before birth. There is no PCI parent yet: worker creation precedes PCI,
so the existing PCI security carrier cannot simply be reused or relabelled.

The full original normal functions remain unchanged. Private copies replace
only actual allocation/return sites and keep all original reference, lock,
security-hook, initialization and error-unwind statements in order. Existing
shared files/fs/namespaces and inherited group/user/key/ucount references keep
their real original owners. They are not retrospectively charged as new private
allocations. Their NodeFixed/bootstrap ownership still needs qualification.

### Credentials and security

Actual prepare_creds allocates cred_jar, copies the current credentials, sets
non_rcu=0/usage=1, obtains group/user/userns/key/ucount references, clears the
inherited security pointer, and invokes security_prepare_creds. Its actual
error calls abort_creds. For the fixed ordinary kthread flags there is no
CLONE_THREAD shortcut: copy_creds creates real credentials, discards the
appropriate process/thread keyrings, takes the actual two task credential
references and increments the original NPROC ucount. All those actions remain.

The composite cred blob uses the actual initialized blob_sizes.lbs_cred before
allocation, not a guessed SELinux-only structure. The real selected LSM
cred_prepare/cred_free callbacks must all be authenticated and preserved;
unknown extra callback allocations are not accepted as free or absent.
selinux_cred_prepare itself copies its actual task_security_struct, but this
does not establish that the complete callback graph is allocation-free.

Private credentials keep their real embedded rcu_head. Actual __put_cred still
performs the real usage/current-cred checks and queues the original RCU callback
when non_rcu is zero. Actual put_cred_rcu runs security_cred_free and all real
key/group/user/ucount/userns releases before the private credential storage
return. Composite security storage returns only after its original callbacks.
No child is refunded at pointer unlink, stop completion or call_rcu enqueue.

### Signal, sighand and delay accounting

The real sighand slab constructor initializes siglock AND signalfd_wqh. A
zero-only private allocation is incorrect. The private producer must execute
that exact constructor before the original copy_sighand action copy. Ordinary
SLAB_TYPESAFE_BY_RCU protects storage type after cache free; privately carved
storage cannot claim that property without retaining a charged actual RCU
wrapper until the real grace-period callback. signalfd_cleanup and original
lock/currentness semantics remain mandatory.

Actual copy_signal initializes counters, task/thread lists, waitqueue, pending
signals, POSIX hrtimer and rlimits, then runs tty_audit_fork/autogroup and other
configured initialization. Those are real descendant paths, not optional
statements to omit. free_signal_struct must preserve its actual taskstats,
autogroup and possible mm cleanup before physical signal return.

delayacct_tsk_init clears the inherited pointer and branches on the real
delayacct_on value. Its enabled allocator and raw spinlock initialization need
owned storage. The actual delayacct_tsk_free runs from bad fork and final task
destruction where upstream says no other accessor exists. Preserve that
boundary and enabled behavior; do not force the static key/runtime setting off.

### Once-only final task destruction

__put_task_struct calls sched_ext/io_uring/cgroup/NUMA/security/credential/delay/
signal/sched-core destruction and then free_task. exit_creds may queue a real
credential RCU callback which outlives this task destructor chain. The current
cache guard conservatively retains on children; full constructor integration
must distinguish legitimate child drain from corruption.

At the actual final cache-return boundary, latch that original destructors ran
exactly once, retain the physical task record at usage zero, and return it only
when all actual children are physically returned. A final child callback may
request process cleanup after its own real storage return and outside original
locks. A retry must perform ONLY the physical view return: it must never revive
the task refcount, call __put_task_struct/free_task/destructors again, or follow
a stale child pointer. Pending/late-child checks and task generation validation
must be serialized by the original pool lock. Actual final-put caller contexts
and the process notification/bootstrap ownership remain qualification gates.

## Subsequent mandatory constructor/installation closure

* PID: alloc_pid's real namespace cache, pidmap lock, IDR preload/insert/replace
  and delayed_put_pid RCU final free. A shared init PID IDR node may outlive this
  task's idr_remove; it cannot borrow an uncharged preload or transfer its owner.
* Task LSM blob and actual selinux_task_alloc PROCESS/FORK AVC/audit chain with
  a cleanup-task carrier. No PCI ancestry or no-audit assertion substitutes.
* Actual enabled audit_alloc/task filters/filter keys/context; real perf event
  inheritance/context descendants, scheduler/autogroup/cgroup callbacks and
  x86 copy_thread/FPU state. No racy NULL observation or forced config-off pass.
* Original interrupted create, full copy_process publication/failure order,
  task/stack/metadata/descriptor final retirement and no unpublished ordinary
  free escape. The existing private entry preserves the real completion/stop
  tail and does not itself supply constructor closure.
* Original kthreadd and per-CPU IRQ/SMP/RCU/TLB/bootstrap owners; actual runtime
  task geometry and aggregate fit in the original 192 KiB/256 records; bounded
  hotplug/caller/instrumentation proof, linked/booted selected kernel/BTF,
  real physical allocator final-free measurements and controlled protocol/
  conformance observations. These are needed for installed-profile success.

This groups actual dependent constructor families rather than proposing another
isolated refusal-only PR or object campaign. Source/control review precedes any
integrated qualification plan. All production and complete-allocation gates
remain false until the actual remaining chains and evidence are complete.
