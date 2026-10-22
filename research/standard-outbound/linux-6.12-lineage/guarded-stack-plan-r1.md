# Private cleanup task: guarded stack birth and unpublished return

This is an uninstalled continuation of the reviewed six-file task prefix. It
does not create a Linux worker, select a provider, or qualify a supported kernel.
The original 512 KiB physical bank, 192 KiB infrastructure tail, 256 records,
64 owner slots, TCP 96 KiB and DNS 64 KiB limits are unchanged. The existing
1 MiB bootstrap ceiling includes that bank and actual static metadata.

## Actual maintained chain

Linux 6.12.113 commit `7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e`
is authenticated from the existing whole official archive. Its `fork.c` stack
allocator first borrows `cached_stacks`, then calls `__vmalloc_node_range`.
Its return first tries the cache and otherwise places RCU data in stack storage.
`vfree` and `vunmap` enter the global lazy VA lists, which may schedule
`drain_vmap_work`. An external process-context caller alone does not close that
deferred work, TLB, metadata or original owner lifetime.

The new private path uses neither cache nor lazy return. One child record born
under the actual already-admitted task contains the real VM/VA descriptors,
page-pointer and PTE-pointer arrays, page-alignment slack and four whole bank
pages. The byte operand uses actual `sizeof`, PAGE_SIZE and THREAD_SIZE before
the original device allocator admits or writes storage. Complete root/request/
task generations and the actual bank task address are validated in the same
pool-lock extent. Returned views do not refund the monotonic bank cursor.

Under the actual free-VA lock, the path inspects only the first existing free
range. It requires an aligned left edge and strictly more than the actual
THREAD_SIZE + PAGE_SIZE interval; shortening that normal node needs no split
node, per-CPU preload, global purge, notifier or retry. The guard remains an
unmapped page. Before the first PTE write, all four target leaves and the guard
must have existing ordinary empty leaf tables. Missing, huge or nonempty
entries refuse; no new page-table allocation or retrospective table ownership
is represented. Shared pre-existing table ownership remains unchanged.

The actual original trace allocation call remains outside the VA lock. Its
callback allocation/admission closure is still required for installation;
checking a static key once cannot certify the absence of future callbacks.
The ordinary VMAP allocator, cache paths and lazy return bodies are unchanged.
A private guard before ordinary `remove_vm_area` prevents foreign unmap from
giving the bank descriptor or payload pages to normal SLUB/page free paths.

## Return ordering and retention

Only the actual kthreadd constructor may abort this still-unpublished stack.
It validates the whole source and actual task/VM relationship. It checks the
same actual PTE addresses, expected page PFNs/protection and empty guard before
clearing anything. Hardware accessed/dirty bits are allowed; other changes
poison and retain. The actual maintained `vunmap_range` performs cache flush,
PTE clear, architecture synchronization and synchronous target TLB flush before
any descriptor view can return. No hidden work or RCU callback is substituted.

The busy VA is removed before space can be published back into the free tree.
The range may be absorbed only into actual adjacent normal free ranges under
the original free-VA lock. With both neighbours, the original unlink-before-
augment ordering and original normal-node cache free are retained. The private
VA descriptor never enters the global free tree and is never passed to SLUB.
If no adjacent free range exists, the unmapped reservation is put back in the
busy tree and the descriptor, task, request, bank and original reservation stay
held. There is no automatic retry or assumed VA retirement. This conditional
VA return is a remaining supported-layout/teardown requirement, not a general
successful retirement claim.

Only after synchronous unmap and actual VA restoration does the child record
return, followed by its original task view. A failed child return cannot retire
its parent. The constructor then still refuses before the remaining original
task initialization/security/PID/scheduler chain. No task is published or run.
The guarded path is real source progress, not a ready-worker result.

The kthreadd mailbox's outside-lock READ_ONCE now has WRITE_ONCE publication
and consumption writers under the original creation lock. The completion
handshake remains the receiver's last request/completion access.

## Required next closure

Running-task final stack release is separate: `kthread_stop` completion precedes
the final scheduler/RCU task lifetime, and the exiting worker cannot unmap its
own currently executing stack. An original retained control owner must do final
mapping return only after the real task/stack final-use boundary. This patch
does not install that handoff, forge an RCU proof, or create a reaper queue.

The rest of fork/kthread still needs same-owner task instrumentation and
auxiliary data, PID/IDR sharing/final RCU return, credentials/security/audit,
actual worker publication, bounded queue/stop, scheduler/CPU-hotplug and
bootstrap/control-owner final lifetime. The leaf-table availability and VA
absorption conditions need a real maintained layout/profile or further owned
allocation source, not an operator assertion. Shared CPU/TLB infrastructure and
mandatory trace callbacks require source/accounting closure and actual proof.
Geometry is not claimed to fit from a serialized C layout.

No link, boot, BTF/image seal, physical allocator/final-free installation,
protocol conformance or production enablement is established. Tiny C controls
exercise source bodies with serialized VM/lock/TLB/task doubles only.
