# Concrete unsupported module/helper operation proposal

This follows the reviewed finite private-worker profile. The four operation
guards and immutable born-current classifier are now prepared as an unselected
source prototype in host_stream_kernel_cleanup_worker_operations.py and the
matching factory/header fragments. Full consumer and observer entry remain
disconnected; no kernel build, operation execution or closure is asserted.

Exact official Git captures are retained in
kernel-cleanup-constructor-extra-originals-r7: kernel/module/kmod.c,
kernel/umh.c and the module/kmod headers, at Linux commit
`7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e`. Each complete source has its
recomputed Git blob identifier and SHA256; no archive-membership claim is made.

## Actual producers and propagation

Both request_module and request_module_nowait reach the real integer-returning
__request_module, differing in its wait argument. That function formats the
bounded module name, calls security_kernel_module_request, acquires the actual
kmod concurrency slot, emits trace_module_request, checks duplicate request
state and calls call_modprobe. Its actual return passes the producer error
back to the request_module caller. Proposed private-Task refusal belongs after
its local declarations, before current_is_async, formatting, LSM/audit, slot,
duplicate state or allocation. No hook is skipped on a supported operation:
this operation itself returns -EOPNOTSUPP before it starts.

Actual call_modprobe allocates argv and a duplicated module name, then calls
call_usermodehelper_setup with free_modprobe_argv as its cleanup. Setup failure
uses its original free-module-name/free-argv labels and returns -ENOMEM; exec
failure returns that exact exec error after original cleanup. No direct public
producer bypasses __request_module to call this static function. Therefore the
__request_module guard is necessary before those allocations; a guard only in
the eventual workqueue/helper thread would be too late and would lose origin.

The convenience call_usermodehelper has an integer error channel. It first
calls setup, maps NULL to -ENOMEM, then returns exec's exact integer result.
Proposed refusal belongs before setup and returns -EOPNOTSUPP there.

The public two-stage API has different real contracts:

| Boundary | Proposed authenticated private-Task result | Original ownership/error behavior |
| --- | --- | --- |
| __request_module | -EOPNOTSUPP before LSM/audit/allocation | Caller receives actual integer error; no module state/slot created |
| call_usermodehelper | -EOPNOTSUPP before setup | Caller receives actual integer error; no info created |
| call_usermodehelper_setup | NULL before its first kzalloc | Its real pointer API has only NULL failure; existing caller cleanup and its actual error mapping remain |
| call_usermodehelper_exec | -EOPNOTSUPP before helper_lock/queueing/spawn | It consumes the supplied info on failure, using original freeinfo/cleanup once |

Do not return ERR_PTR from setup: its actual callers test only NULL. Do not
claim that setup itself can report EOPNOTSUPP. Its direct callers retain their
real failure channel, commonly -ENOMEM. The module and convenience APIs have
their own earlier integer guards so their callers receive EOPNOTSUPP directly.
If this distinction is unacceptable for the selected profile, the API needs an
explicit new typed error contract and a complete caller migration first.

Exec first validates info.path, takes helper_lock and eventually queues the
actual info work on system_unbound_wq. Proposed denial must happen before those
steps. Since exec consumes info on failure, the denial must run the original
call_usermodehelper_freeinfo once and return its real integer error without
calling helper_unlock for a lock it never took. That original cleanup may
invoke the info's cleanup callback; it must not be silently dropped. Setup by
this private Task would already have been refused. Any selected producer that
passes in info prepared by another actor therefore still needs its actual
cleanup callback/provider lifetime mapped; this proposal does not adopt that
foreign allocation or assert a universal cleanup-allocation exemption.

The unchanged queued worker selects actual call_usermodehelper_exec_sync or
user_mode_thread(call_usermodehelper_exec_async). Sync also uses user_mode_thread
and kernel_wait. The async child prepares/commits kernel credentials and calls
kernel_execve. These are real further Task/mm/cred and workqueue allocation
graphs. Refusing at the original originating Task boundaries prevents them
from becoming an unowned continuation of this private programme. Names,
workqueue identity or a later global helper Task are never used as provenance.

## Actual born-current classifier

Add one kernel-private no-argument classifier in the original factory TU.
Its only candidate is actual current. Bank range is a location check, followed
by exact original owner, Root, request and Task generations, original parent
records and exact born Task address. Only then may it read actual Task usage.
It admits no Task pointer or origin flag from a caller. It never identifies a
Task from a name, PID, UID, worker_private guess or an unvalidated bank pointer.

The implementation first requires actual in_task(), whose maintained non-RT
macro excludes NMI, hard IRQ and serving-softirq execution before pool locking.
Those contexts have their own actual producers and must not inherit the Root
origin of a merely interrupted Task. BH-disabled process context remains Task
execution. The complete original preempt header is authenticated too.

Return values are: zero for a genuinely ordinary Task outside the bank; one
for the authenticated born private current Task; negative for an uncertain
bank candidate, with the original pool quarantined. Integer operation guards
map the latter to -EIO, never ordinary fallback; setup uses its actual NULL
failure channel. The classifier is independent of admission stopped/closed:
the genuine existing Task must still be recognized while it completes close.
It does not grant readiness, create a child, acquire ownership, add a charge
or certify physical return. The selected Task's actual PUBLISHED lifecycle
and positive real usage cover the active entry/worker/exit execution interval.

Each integer guard is a prefix to the complete maintained body. Ordinary
classifications continue through that body unchanged. Setup's denial precedes
its actual kzalloc; exec's denial preserves consuming cleanup. No duplicate
request table, module-name shadow storage or deferred helper executor is added.

## Audit and remaining supported worker operations

Actual audit_alloc_context zero-initializes dummy and sets AUDIT_CTX_UNUSED.
Actual audit_dummy_context tests dummy, not that UNUSED state. Therefore
audit_log_kern_module can reach __audit_log_kern_module and allocate a string
even without a user syscall. The real module-request refusal must precede
security_kernel_module_request and that hook's audit path; forcing dummy,
disabling audit or silently skipping a hook would not satisfy this profile.

Other actual worker callbacks/LSM/audit operations remain to be selected and
mapped. Initial Task-constructor SELinux permission ownership does not yet
qualify every published-worker LSM call. This proposal closes only the named
unsupported operation routes once implemented and reviewed. Original shared
providers, actual worker producer quiescence before stop, runtime fit, IRQ/RCU
results and physical/native final-free remain separate required evidence.
