# Cached ACPI companion ownership (uninstalled)

This source extends the maintained 6.12.113 PCI constructor prefix. It does not
install the factory, execute ACPI, certify kernel final-free, or complete a
supported device profile. The selected consumer still returns `NULL`. Original
TCP 96 KiB/DNS 64 KiB, 64 owners, 256 allocation records, the 512 KiB backing and
its 192 KiB infrastructure tail remain unchanged.

The selected subset requires initialized ACPI and successful nonblocking entry
to the original scan mutex, deletion mutex and companion-lookup read semaphore.
It refuses queued or in-flight deletion, a saturated/uncertain deletion counter,
custom lookup hooks and bridge scoring. One traversal counts every child before
the normal ACPI filter, stopping at 32. A second matching address is unsupported
before the original ambiguity scorer can execute AML `_STA`. These are explicit
unsupported cases, not successful no-companion results or skipped policy.

Before lookup, the original NodeFixed domain allocates one explicit
`LSF_DEVICE_ACPI_REFERENCE` child of the actual PCI ticket and generation. That
descriptor includes the real work item and remains inside the original backing.
The first matching callback takes `acpi_dev_get()` while the original iterator
still holds the device alive. The descriptor records the real companion and
handle; it does not adopt an address as proof. Association occurs while the same
deletion mutex is held. The existing companion-hook writers use the same original
lookup semaphore; the private path cannot silently bypass an installed hook.
Known queue closure refuses before descriptor allocation or reference get. A
queue teardown racing a previously admitted reference still retains that charge
if dispatch is refused; the readiness snapshot is not lasting queue authority.

A reference prevents deallocation, not invalidation. The original namespace
deletion callback revokes the matching private descriptor under its existing
deletion mutex, before it writes `INVALID_ACPI_HANDLE`. This sets original factory
uncertainty without returning either owner. A separate checked in-flight count
spans the original worker's list removal through its actual final `acpi_dev_put()`.
The worker's notifier, device removal, power transition, put, loop, ordering and
requeue behavior remain intact. No added lock spans those callbacks or puts.

Setup failure can still hold the original factory mutex. Therefore both failed
setup and final PCI cleanup record retirement without directly putting the
companion. The constructor-active fence prevents scheduling until the real
factory mutex is unlocked. Exactly one `lsf_device_queue()` reservation in the
original table precedes dispatch to the original ordered ACPI hotplug queue.
The child descriptor and PCI parent remain live while work is pending. A missing,
stopped, refused or uncertain dispatch poisons and retains both; there is no retry,
alternate queue, generic allocator or early refund.

The cleanup callback validates the same ticket, generation, whole extent and
original PCI parent. Outside factory/ACPI/pool locks, it detaches the exact
companion fwnode and performs the real `acpi_dev_put()`. Only after that call
returns may it finish the descriptor and then the PCI view. Unknown fwnode
replacement, duplicate retirement, stale generation or an uncertain callback
retains capacity. Dropping this reference is not proof that every ACPI or deferred
kobject allocation has physically freed.

Private queue admission and original queue destruction share a small spinlock.
Initialization publishes availability only after the original queue allocation
and `BUG_ON` checks. Termination closes private admission before the unchanged
destroy calls, with no private lock held across destruction. Queue existence is
not a capacity certificate: full shared hotplug-worker/queue/native stack and
static metadata accounting is still unqualified.

The retained serialized freestanding reference separately reproduces the old
borrowed-pointer failure and exercises reference, invalidation, pending-work and
retirement ordering. Linux structures, locks, refcount primitives, klist backing,
workqueue scheduling and removal callbacks are explicit doubles. Actual maintained
object compilation for this new prefix has not run. None of these controls is a
Linux concurrency, hardware, AML, queue-capacity or physical-memory bound.

Remaining mandatory work includes the original host-bridge/ACPI bootstrap and
parent companion graph, physical shared-worker ownership, all later ACPI binding
and PCI setup allocations, real driver/virtio/DMA/per-CPU/RX initialization,
failed-open native backing retention, remaining packet/neighbour/DNS/deferred
closure, exact resolved layout, sealed image/BTF final-free installation and
actual node/provider/operator/adversarial qualification. Runtime device currentness
after this setup association still needs every later consumer fence; this prefix
does not promote a snapshot reference into lasting authority.
