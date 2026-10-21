# Uninstalled PCI enumeration and NodeFixed birth prefix

This source prerequisite follows the accepted ADR-0061 and #738/#739/#740. It
is not an installed device profile, complete PCI or RX closure, protected native
bootstrap, measured physical bound, Linux runtime result or final-free proof.
The original selected factory consumer still returns NULL. Registration and
open therefore refuse before backing allocation. No production gate is enabled.

## Why driver-probe deferral is too late

Maintained Linux 6.12.113 commit
`7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e` allocates `struct pci_dev` in
`pci_scan_device` through `pci_alloc_dev`, before `pci_setup_device` names the
device, `pci_device_add` initializes capabilities and sysfs, and `really_probe`
configures DMA and driver sysfs. `virtio_dev_probe` also marks every failed
probe, including a deferred error, FAILED. Delaying only `virtnet_probe` would
not establish prepaid origin for those existing objects.

The source prefix reserves one proposed dedicated modern virtio-net coordinate:
domain 0, bus 0, slot 3, function 0, vendor 0x1af4, device 0x1041. These are
compiled candidate constants, not a hardware observation, any-vendor match,
caller certificate or shipped operator configuration. A supported platform must
actually reserve that coordinate for this device. Other coordinates retain the
entire original scan and constructor bodies. Nothing adopts a normal device
which was already discovered there.

## Same physical store, before the first device birth

The shared NodeFixed domain uses slot 63 of the original 64-owner storage and
records from the same original 256-record array. Its state is physically born
inside the original 192 KiB infrastructure tail of the 512 KiB extent; there is
no second ledger or allocation table. The four application contexts and their
original TCP 96 KiB / DNS 64 KiB allowances remain untouched. This shared domain
has no tenant/activation scope words and cannot pass the original application
context lookup. Its actual native backing carrier must remain held separately.

`lsf_factory_device_initialize` runs only after original factory open acquired
backing and the actual opening mm/TGID/credential/network references. Its exact
root birth precedes exposing the state pointer. This necessary ordering is not
authentication of the still-missing sealed native bootstrap. Root credentials,
matching words and this header alone supply none of that authority.

If device initialization fails after the original pages/mm/TGID/credential/net
references and opened=1 are retained, the generated open path preserves them in
static quarantine. It sets pool poison and uncertain, returns the original error
without assigning file->private_data, and neither releases backing nor permits
reopen. A failed open therefore provides no usable descriptor or release callback.
The future native bootstrap must retain its original StreamKernelBacking owner on
this uncertain failed-open path too; that native integration is still missing.
This is bounded permanent retention, not a successful or usable restart path.

The selected scan fences before `pci_get_slot`; while unavailable it performs
no constructor or retroactive lookup/adoption. Once genuinely available, it
acquires the existing factory mutex through real construction and
`pci_device_add`, so the original close path cannot interleave its root fence
with that publication. Every selected exit releases the mutex. This is a private
source call path, not a per-task allocator override or a new public device token.
The fixed vendor/device is checked before allocation. A changed device or an
existing normal object refuses without broadening the match.

The private `pci_alloc_dev` clone changes only its signature and actual kzalloc
call. Original list/type/resource/lock initialization and `pci_bus_get` remain.
The failed-setup path puts that actual bus reference before returning the view.
The original final `pci_release_dev` capability/OF/platform/bus/bitmap cleanup
all precedes private return; genuinely ordinary addresses keep original kfree.
An unknown or double-returned interior address poisons and retains, never falls
back to a normal allocator. The original setup, device-add and security bodies
are preserved, not replaced with empty successful implementations.

The private setup clone now closes its known naming allocation. It requires the
entire original LIVE PCI birth before dereferencing it, then exact fixed
coordinate/vendor/device and actual is_kernel_rodata membership for the name
literal. The same normal dev_set_name API emits 0000:00:03.0; every other upstream
setup statement is reversible to its complete original definition, including OF,
ACPI and early fixups. Normal kvasprintf_const routes this no-percent/no-slash
literal through kstrdup_const, which reuses actual kernel rodata. Unknown
placement refuses before any setup effect, rather than using the normal heap
fallback. No firmware, fixup or mandatory security hook is silently skipped.

The original core release ordering is also explicit: device_release calls the
PCI callback before kfree(device_private), and kobject_cleanup releases its
cached name after the type callback. The constant name requires no late private
heap owner. Future core metadata/other child allocations must retain their real
Node backing through those later callbacks; returning the PCI view alone cannot
refund that infrastructure or certify final-free.

A same-domain LIVE parent and its exact generation are recorded in the existing
birth fields before every child is exposed. A parent cannot return while a
LIVE child still names it. Close fences roots/publication while genuine private
late descendants remain retained. Returning a view never reuses its address in
a live generation, releases backing or refunds the native NodeFixed carrier.
Only one PCI construction attempt is admitted; there is no hidden reprobe or
allocator retry after failed setup. Unproved cleanup can retain capacity
permanently; this is not a usable restart implementation.

## Actual bounded source and supplemental mechanism evidence

The source packet authenticates 58 whole maintained files and 19 complete PCI/name/cleanup
function definitions, layered over the prior packet source. Its 95 outputs keep
81 prior outputs byte-exact; the two prior factory files have explicit reversible
extensions. Twenty focused source controls cover unchanged normal bodies,
early fence placement, identity checks, bus-reference cleanup, closed selection,
original store/caps, Node/application separation and close/publication ordering.

The cached Zig/Clang-to-Wasm reference executes the actual maintained PCI
constructor/scan/final-return bodies and the private same-store functions. The
old pre-enumeration path produces the retained allocation-before-backing RED
(exit 2); the current path reaches exit 0 with 40 checked assertions. These
include normal-device preservation, missing/foreign owner refusal, existing
object non-adoption, changed identity refusal, setup failure and actual reference
puts, no reprobe, final return/no backing refund, close/publication serialized
ordering, child retention, late private descendants, exact tail/record
exhaustion, stale generations and unknown-interior quarantine.

The reference supplies serialized type, lock, the unclosed PCI-setup remainder, device-add, section-bound and hardware
doubles. It does not execute those external Linux constructors, real mutex
contention, PCI enumeration, DMA, security, RX or kernel callbacks. The retained
failed reference compile reports NULL/type declarations in its doubles, kept
separately; no production source fix was inferred. The earlier isolated r3 reference retains its 27-versus-29 reader-count
correction without recompiling that successful binary. The grouped r5 reference
also executes the original normal naming and post-PCI core cleanup C bodies:
the original same-coordinate formatted name allocates; the constant spelling does
not. Unknown modeled rodata placement refuses, and the exact IOV prefix is
exercised with original pure geometry helpers. Those section bounds and the
unselected IOV tail are explicit doubles; actual Linux/linker placement is not
proved. IOV remains disabled in the unchanged recorded kernel configuration,
so neither an enabled IOV object nor actual VF execution is claimed.
No kernel, host/native engine, SDK or VM was built or run.

## Concrete remaining chain; no enablement shortcut

The actual full PCI consumer is still incomplete. Before replacing the existing
NULL selection, all allocation/free edges reachable through `pci_setup_device`
and `pci_device_add` must be owned: kobject names, capability-save buffers,
ACPI/firmware, DMA/IOMMU, MSI/IRQ, device/sysfs/kernfs/devres/notifiers and their
failed, reference-counted and deferred cleanup paths. The source audit also
confirmed that pci_iov_add_virtfn calls exported pci_alloc_dev directly, after
virtfn_add_bus, bypassing ordinary scan. Its new exact-coordinate guard now
refuses before either allocation, while all other targets keep the complete
original body. This is not a claim that every future exported-pci_alloc_dev
caller or unsupported platform has been qualified. The protected native
writer must really reserve and retain the original one-MiB backing carrier
before opening/rescanning. No descriptor or rescan command is claimed shipped.

Next are the real virtio PCI/core/virtio-net constructors, fixed queue pair and
ring state, per-CPU references (original PCPU_DEV_REFCNT/HOTPLUG_CPU remain),
actual DMA mapping choice and cleanup, RX header/data birth before socket lookup,
and charged Node-to-application copying. No fake page reference, forced DMA
bypass, security disable or retrospective frame origin is permitted. NodeFixed
must include the complete live platform costs before allocation; 192 KiB being
available is not proof that those costs fit.

Neighbour/ARP, DNS UDP and TCP fallback, netfilter/LSM, cache/deferred ownership
and the remaining SKB/page paths must then close under the original allowances.
Complete physical bounds, sealed built image/running BTF/final-free producer,
trusted installation, actual stop/restart, operator and signed language/provider
conformance remain required. Normal installation and host-TLS accounting remain
disabled, and no whole acceptance criterion is completed by this prefix.
