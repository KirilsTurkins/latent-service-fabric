# Final signal return and the original cleanup work

This uninstalled source plan uses the same maintained Linux 6.12.113 archive.
The actual `call_rcu`, `__call_rcu_common`, `rcu_do_batch` and API header are
authenticated as whole files before selected definitions are accepted. There
is no kernel build, boot, installation or physical RCU accounting result.

The original `__sigqueue_free` checks PREALLOC, decrements its real ucount and
performs its original free last. Dequeue and flush remove/copy the signal data
before that call; private PREALLOC storage is already refused. The ordinary
struct, ordinary allocator and ordinary final-free algorithm stay unchanged.

A private allocation can instead admit a wrapper containing that unchanged
struct followed by an embedded `rcu_head`, all in its same original bank record.
Its actual `sizeof` is charged before allocation; no new slot, owner, queue,
allowance, pointer-prefix lookup or detached retirement certificate is added.
The original 512 KiB bank, 192 KiB tail and 256-record bounds remain fixed.

The private return validates the whole wrapper before reading it, marks only
QUEUED under the pool lock and requests RCU after releasing that lock. It does
not return the occupancy there. A private read-side extent covers this handoff.
In the maintained `call_rcu` contract, IRQ/preemption/softirq-disabled regions
also delimit read-side critical sections. The actual non-RT sighand spinlock
therefore delays this callback beyond the original locked extent; a source
guard must refuse the private signal producer under PREEMPT_RT rather than
pretend the same lock contract. The observed object configuration is historical
evidence, not a replacement for a sealed installed configuration.

The callback may run on another task. It must classify the actual embedded-head
address and exact original bank/PCI generations before dereferencing private
storage; it requires QUEUED, then performs the sole final return. Only afterward,
outside pool and original sighand locks, can it request the already prepaid
ACPI cleanup work. No private storage is read after final return. Actual
`rcu_do_batch` releases its callback bookkeeping without dereferencing the head
after invoking its function. A missing/failed callback retains the bank.

This closes no shared infrastructure gate: actual RCU per-CPU queues, debug and
trace callbacks, worker bootstrap, cache-tail scheduling and physical backing
retirement still require their complete source and installed-profile proof.
The consumer remains unavailable. No sleep, polling retry or direct final put
under the sighand lock is introduced.
