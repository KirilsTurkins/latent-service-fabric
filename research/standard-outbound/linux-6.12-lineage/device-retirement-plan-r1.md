# Resume the original cleanup after actual final child returns

This source-only layer consumes the exact maintained recipient derivation.
The factory consumer remains unavailable. No new queue, work item, owner,
record, timer, retry, native product or physical retirement receipt is created.
The original 512 KiB backing, 192 KiB infrastructure, 256 records, 64 owners
and TCP/DNS 96/64 KiB limits are unchanged.

## The concrete liveness gap

Existing device-domain security blob finish and SID-table destruction return
their real child occupancy without waking the original prepaid firmware work.
The parent correctly stays LIVE while an AVC/SID/audit child exists, but after
the last child actually returns no later cleanup attempt is guaranteed.
Waiting, scanning an empty queue or pretending the record itself proves
physical retirement cannot settle this gap.

The existing eight resumption sites also select a current global factory
after dropping the pool lock. A future reusable backing must not let a late
completion choose a later owner's cleanup. Even though the current source
never reopens or frees its backing, bind the wake to the original generation
now rather than relying on that temporary limitation.

## One original continuation and one atomic admission fence

The layer keeps every original constructor, core, registration, sysfs,
uevent, WORK and sigqueue final-return path. After each existing successful
source/parent validation and before returning occupancy, it copies only the
actual device key and PCI ticket while holding the same pool lock. There is
no saved replaceable cell, private object pointer or caller-supplied proof.

The existing schedule function receives those scalar identities. Under the
same pool lock it rejects a missing backing or different owner/PCI generation
before selecting a descriptor. It preserves the real retirement/core-tail/
constructor/queued checks and the full original live-child scan. The no-child
to QUEUED transition remains under that lock, which also admits every child.
Thus a late legitimate child either retains the parent first, or the queued
parent fence refuses a later child; there is no free-then-adopt interval.

Only after unlocking does it dispatch the original embedded work through the
existing ACPI queue admission helper. Dispatch failure poisons and retains the
already queued descriptor and original PCI. No alternative queue or retry is
introduced. A stale wake never poisons or dispatches a newer backing.

The device-domain generic blob final return and original SID policy-destroy
branch gain the same post-return wake. Application-domain paths remain exact.
Neither queue-marking nor a requested RCU callback is treated as a final return.
The existing AVC/SID callbacks, policy destruction and actual SKB/string free
hooks retain their real final-return responsibilities.

## Original-lock and physical scope

AVC node and SID cache RCU final callbacks run after unlink and original cache
unlock. Policy-destroy SID returns occur at the original `sidtab_destroy_entry`
point after the policy grace period. PRIVATE failure cleanup can occur under
a cache lock, but its source WORK or containing live parent still blocks the
no-child dispatch fence. Source checks and serialized controls must establish
that distinction; do not claim every generic finish caller holds no lock.

No pool lock spans a queue call, callback, allocator, final PCI put or RCU wait.
The new snapshot helper is a private lock-local scalar copy, not an admission
API. It does not lend a task borrow or dereference a returned child.

Actual shared workqueue/RCU capacity, worker and callback physical completion,
instrumentation registration/retirement and native bootstrap remain unclosed.
The source still never returns the bank or enables a provider. Full remaining
device/RX/DMA/neighbour/DNS/page/final-free closure, a sealed image/layout/BTF,
link/boot/install and real finite operator/provider conformance are mandatory.
Tiny C controls exercise serialized doubles only; they cannot qualify those
Linux scheduling, lock, grace-period or allocator obligations.
