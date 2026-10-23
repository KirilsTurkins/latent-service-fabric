# Physical provider execution and operation authority

Unselected source proposal, following the corrected provider boundary note.
No global ACPI hotplug/termination prohibition is proposed. Ordinary ACPI work
continues on the same original ordered queue. No kernel/test/build is run and
no physical fit, native bootstrap or complete retirement is certified here.

## Separation is feasible, but the current Task classifier is insufficient

The current private constructor owns physical Task/stack/children through the
original provider bank and `lsf_cleanup_task_source` generations. Its
`lsf_factory_cleanup_worker_operation_current` authenticates the born Task and
then returns one for its entire execution interval. That is correct only for
the current finite private-operation worker. Reusing that positive result for
a physical provider worker would wrongly give unrelated ordinary ACPI callbacks
Root provenance, and would apply our module/helper refusals to their work.

Existing source already separates storage and operation identity elsewhere:
the closed `lsf_factory_blob` owner-domain dispatch and device SIGIO work carrier
validate an actual LIVE WORK plus its creator ancestry before passing explicit
source through the original mandatory security algorithms. A NodeFixed address
or NULL application pointer is not authority. The provider executor can use
the same principle without inventing a second ledger or an ambient allocator.

The proposed physical role is a closed internal discriminator in the original
charged request/Task ancestry: private-operation worker versus provider-executor
worker. It is selected only by the real factory caller that has authenticated
the concrete target pool/worker and exact entry function. It is not supplied by
a guest, a work producer, a Task flag, name, PID or opaque pointer. Its bytes
must enter the existing complete bootstrap geometry. All physical constructor,
error, refcount, stack, RCU and final-return responsibilities remain unchanged.

The provider-executor role does not itself authorize an operation. The private
role retains its current behavior. A provider-role Task must prove its current
actual WQ work before any Root operation result is returned. No physical Task
owner is transferred when a different ordinary callback runs.

## Actual source feasibility of identifying the current operation

Original `kernel/workqueue.c:process_one_work` sets the actual worker's
`current_work`, `current_func`, `current_pwq` and color beneath the original pool
lock before dropping that lock and invoking `worker->current_func(work)`. That
same Task clears those fields after the callback returns. This is the real
dispatch lifetime, not a producer's copied certificate. The original worker
body and scheduler helpers already rely on the physical Task/worker relation.

The new no-argument guard would do the following:

1. Require `in_task()` before any pool lock. An IRQ/NMI/serving-softirq callback
   must not inherit the interrupted operation's source.
2. Authenticate the actual current physical Task against the same full born
   owner/Root/request/Task generations and lifecycle before any Task field read.
   For the provider role, authenticate its actual typed worker and pool records,
   original parent relation and exact stored Task address before reading worker
   fields. Do not infer a worker from `worker_private` or kthread_data alone.
3. Read that validated worker's real `current_work/current_func`. During an
   operation guard reached synchronously inside its callback, those fields have
   this same Task as their writer and cannot transition until its call stack
   returns to `process_one_work`. No extra WQ pool lock is needed merely to
   snapshot this same-Task state; avoiding it also avoids an invented factory
   pool-lock/WQ pool-lock inversion. This argument does not authorize cross-Task
   lookups or NMI access.
4. A work address outside the bank is ordinary provider work and returns zero:
   it receives only the original Linux callback semantics, not an LSF grant.
   An address inside the bank is only a candidate. Require the exact firmware
   descriptor/work-member extent, kind, LIVE/QUEUED lifecycle, original owner,
   Root and PCI generations, and actual expected callback function before
   reading its fields or returning one. Unknown/stale bank candidates retain
   and refuse; they never become ordinary fallback.
5. Thread initialization, the idle loop and final Task destructors have no
   current Root operation. Physical child frees still use the original born
   Task source. Explicit Root operations and their security carriers instead
   use the actual current WORK source, with complete owner comparison.

The actual firmware callback can continue to pass explicit original descriptor
source to its helpers. Module/helper guards need the new operation classifier
so ordinary callbacks are untouched. The mandatory LSM/audit calls belonging
to our callback must receive the same exact WORK source where their allocating
paths require it. Physical Task birth identity is not a substitute for that
operation carrier. Existing outside-bank callbacks retain their own original
provider/resource owners. That boundary is not a universal exemption for NEW
allocations required by our callback.

An authenticated terminal descriptor after its final logical return cannot
start another Root operation. Original workqueue epilogues remain original
provider activity. `process_one_work` expressly permits callback-side freeing
of the work item; it traces only its address afterward. Our actual last access
and real physical owner lifetime still must be proven independently.

## Finite executor candidate using the same ordered queue

A provider-funded dedicated pool can preserve every ordinary producer only if
those ordinary callbacks remain ordinary by the operation classifier above.
The proposed target remains the actual original `kacpi_hotplug_wq`; no new
application queue, producer-side transport or replacement callback ordering is
introduced. Its original ordered PWQ installation/plugging enforces ordering
between accepted old work and newly queued work during migration.

The smallest candidate has one dedicated worker Task and one active ordered
PWQ. Under that explicit exclusivity, max_active one means another worker cannot
advance a second callback from the same queue. A callback waiting for another
callback on that same ordered queue would already deadlock under the original
ordered semantics, regardless of spare worker count. Dependencies on other
queues retain their original separate provider workers.

However, original `worker_thread` calls `manage_workers` when no idle spare
exists, so simply limiting create_worker to one would strand accepted work in
the manager's retry loop. A private finite-pool execution branch must explicitly
handle the exclusive ordered case before that manager call. It must prove the
actual sole PWQ/pool relation, max_active, no alternate pool users and actual
worker membership under the existing locks. It may then execute the same
original claim/callback/completion loop without trying to create a spare that
cannot run another active callback. The original ordinary branch and all
original callback bodies remain intact. This is a new physical executor
implementation, not a guessed guarantee of the current unmodified shared pool.

No normal attribute lookup may borrow this private physical pool. The existing
single `get_unbound_pool` caller is `alloc_unbound_pwq(wq, attrs)`, so the actual
target WQ can provide the authenticated provider association before normal pool
lookup. A private pool in the normal pool hash must be skipped by ordinary
lookups; private lookup may select only the exact already-born pool. The
original pool IDR, scheduler, CPU-mask and retirement references still apply.
Unexpected new-pool/PWQ allocation must fail at its real allocation boundary,
using the original fallback/error semantics, never an uncharged pool borrow.

Every NEW worker/pool/PWQ/attribute/temporary allocation needs the same original
bank admission before initialization. Original WQ metadata and borrowed old
pool references remain existing provider objects. The sole Task can reuse the
current single-Task constructor lifetime shape, but entry validation must accept
only the actual known private provider worker function and its authenticated
worker argument. It cannot broaden the current fixed-function guard to arbitrary
kernel functions or arguments.

## Concrete migration/retirement difficulty to solve before implementation

Original ordered migration plugs the new PWQ until old PWQs really retire.
Holding an extra reference to the old PWQ would prevent its normal release and
can therefore prevent unplugging the new PWQ indefinitely. Merely retaining an
old PWQ as a close shortcut is incorrect. Holding an original pool reference
is different: it can keep existing backing alive while the old PWQ retires.

At close, ordinary producers must continue and already accepted work must retain
its order. The queue must stop selecting NEW private physical storage, switch
to a valid original-provider target under the original ordered migration rules,
and let actual private PWQ callbacks/RCU/worker-stop/Task/stack tails retire.
Any newly allocated restoration PWQ or temporary state also needs an original
provider owner before allocation. It cannot be allocated in the retiring bank
and then reclassified as ordinary memory. Alternatively, preserving a reusable
original PWQ requires a concrete park/unplug implementation after real old
in-flight work reaches zero; an extra reference alone is insufficient.

These are bounded source problems, not a reason to adopt the whole OS. They
must be resolved concretely before wiring a consumer. In particular, this note
does not claim that a correct native restoration owner, private single-worker
loop, CPU/topology migration or full physical retirement already exists.
