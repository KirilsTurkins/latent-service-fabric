# Local IRQ relay for a final private stack reference

This is an uninstalled source continuation of the separately frozen lifecycle
and entry packets. It creates no task or executor and supplies no Linux NMI,
CPU-hotplug, physical final-free, bootstrap or runtime qualification. The
512 KiB backing, 192 KiB infrastructure, 256 records, 64 original owners,
TCP/DNS 96/64 KiB and 1 MiB total bootstrap ceiling remain unchanged.

## Why the old release context cannot take locks

The complete same-archive literal inventories retain all direct stack-get/put
references and the next layer of generic readers. In particular, actual x86
`__get_wchan` performs the get/put within `get_wchan`'s target `pi_lock` extent.
Another external reader may retain the dead stack after the scheduler's put.
The old post-switch observation therefore does not prove a later last put is
free of scheduler locks. Exported readers and selected MODULES also prevent an
unqualified assertion that NMI callers are impossible. These are source call
observations, not a sealed transitive/dynamic caller-context proof.

## Permanent hint, embedded descriptor, original owner

One permanent static hint contains the actual born task/request addresses,
full owner/root/request/task generations, backing range and atomic phase.
It is an immutable single birth: there is no reset or address-generation reuse.
Its actual TU `sizeof` is checked in the original factory open path against the
remaining original bootstrap ceiling before references, locks, tap admission
or `alloc_pages`. The actual `struct irq_work` lives inside the original request:
the existing pre-allocation `sizeof(*owned)` charges it before the first write.
Neither descriptor nor hint constitutes a second allocation/ownership ledger.

Only kthreadd resolves the exact born addresses under the original pool lock.
The request extent must equal the checked 64-byte rounding of the actual
request size, and metadata parent generations and `worker_private` must match.
The hint is prepared before publication, with HARD IRQ work and a real
`arch_irq_work_has_interrupt()` result. The selected source is x86_64,
CONFIG_IRQ_WORK, non-RT; no configuration value is changed. The hint arms only
after the original factory has acquired the real continuation task reference,
validated the publication and retained the exact task in the original owner.
The future complete constructor still must place this before Linux visibility.

The last-put hook reads only permanent immutable hint fields. An ordinary
outside task returns to the original ordinary path without following a bank
pointer. A bank-interior wrong address sets static uncertainty and retains.
The exact born task may atomically win one ARMED-to-QUEUING transition, then
call the maintained NMI-safe local `irq_work_queue` on its already admitted
descriptor. It takes no pool/VM/runqueue lock, reads no task fields or mutable
record, detaches nothing, acquires no ref and performs no direct task wake.
There is no remote queue, second attempt or queue-failure ordinary-free path.

The hard-IRQ callback only publishes READY and wakes existing kthreadd. It does
not return records or inspect task/VM fields. Kthreadd drops the original
creation lock, claims READY once, and invokes the real `irq_work_sync` with
IRQs enabled and no pool/VM/runqueue/creation lock. Synchronization precedes
the reviewed original-record and VM checks, field detachment, queue transition,
synchronous PTE/TLB/VA return and final task-reference put. The task reference
and original bank protect the callback and the later irq_work BUSY-clear
epilogue. A callback wake alone is never physical completion.

## Honest incomplete paths

An undelivered local IRQ has no READY state. Kthreadd does not wait, poll, retry,
send a remote IPI or fabricate its completion. The descriptor, real task ref
and original bank remain retained. The actual dying-CPU flush is authenticated
but does not prove that a later NMI cannot enqueue after that flush. Integrated
qualification needs the real selected hotplug/caller ordering. Existing per-CPU
IRQ/SMP/IPI and mandatory tracing infrastructure still need their original
NodeFixed/bootstrap funding; this source does not adopt them retrospectively.

There is currently no actual physical backing-return path in the factory.
The single hint and backing remain held, including on uncertainty. Before any
future bank return or reuse, the full provider must establish final task/stack
return, no pending or executing descriptor, no future legitimate caller, and
withdraw the hint before releasing the backing. This source does not infer
those facts from a static phase or supply an operator assertion for them.

The complete unpublished bad-fork path is also unfinished. The present partial
constructor still uses its explicit never-published abort and never calls this
publication chain. Before a full copy_process can run, its early failures must
retain/return each original child without reaching an ordinary bank free or
relying on a hint that has not yet been prepared. PID/IDR, credentials, signal,
sighand, delay/perf/audit/cgroup/security and final RCU descendants remain
mandatory. Uncertainty discovered without a delivered IRQ is retained; the
future full producer/teardown integration must also close admission and report
that state before it can be a usable provider.

## Supplemental controls

The reference compiles actual new resolver/relay bodies and five exact
maintained IRQ function bodies. CPU, atomic, lock, llist, task, VM, TLB and
scheduler behavior are explicitly serialized doubles. Seventeen fresh Wasm
instances cover held-lock/NMI-shaped entry, outside and wrong-bank addresses,
duplicate release, early/unarmed release, APIC refusal, queue refusal, callback
epilogue, generation/VM corruption, wrong consumer context, undelivered work,
missing publication ref, repeated preparation and invalid callback/source.

The current controls pass. Three counterfactuals fail: removing synchronization
allows physical model return while the descriptor is BUSY; direct capture in
the locked final-put context trips the lock checks; a second queue attempt
violates the single-claim oracle. None is a Linux concurrency or hardware proof.
Two failed reference setup builds and the initial exact-size-versus-rounded
record mismatch are retained separately. The latter failed closed before any
publication and is corrected to exact checked rounded geometry, without a
larger admission allowance. Old lifecycle and entry programmes are not rerun.
