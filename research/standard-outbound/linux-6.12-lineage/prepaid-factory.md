# Uninstalled prepaid backing and original I/O ownership

This is the next source prerequisite for #738/#739/#740, under the accepted
ADR-0061. Normal stream installation still returns Unsupported and host TLS
ACCOUNTING_QUALIFIED remains false. There is no Kconfig, Makefile or initcall
that installs this candidate. No kernel, native host or VM was built or run.

The native change is real ownership integration. In RetainUnproved mode,
SocketMemory now retains an opaque StreamKernelOwnership alongside each original
TCP 96 KiB or DNS 64 KiB reservation. It holds the exact accepted IoLease, provider
request/epoch and StreamScope; different SessionCore identity and any other byte
size refuse. SocketOwner and PhysicalSocket retain this entire bundle in the
existing bounded quarantine after failure, cancellation or close. Previously
that quarantine retained memory/scope but could outlive Connection/PoolCall and
lose the original I/O running owner. No new ledger, executor or allowance is
introduced. LogicalReference keeps its memory-only reservation and original
cleanup path. The four new Rust controls are source-complete but have NOT been
compiled/executed in this delivery; a focused execution is required before
claiming native behavior qualified.

ProviderPools also has a fixed one-MiB backing reservation using its existing
reserve_protocol_metadata ceiling. It grants no installation or physical-free
authority. A future actual descriptor owner must hold it after descriptor close
until complete physical destruction; the current source does not pretend that
the disconnected reservation API authenticates a live kernel bootstrap.

## Backing and occupancy are separate lifetimes

The proposed 4 KiB page platform uses one order-7 (512KiB) extent. The candidate
calls alloc_pages once without a lower-order/general-allocator fallback; it does
not use alloc_pages_exact with potentially larger transient backing. A compile
assertion requires that this extent plus the static factory metadata fit the
existing one-MiB reservation. This assertion is source-only, not an observed
kernel layout or a proof covering VFS/security/driver overhead.

prepaid.h divides the extent into two 96 KiB TCP and two 64 KiB DNS occupancy arenas,
leaving 192 KiB for future shared infrastructure. This is a finite proposed
partition, NOT proof that actual socket/SKB/control/RX/security/TLS objects fit.
Oversized or unavailable capacity refuses; none of these limits is increased.
The physical backing occupies record zero and all views share the original
256-record limit. The new backend cannot be selected alongside another
independent 256-record registrar. Its owner storage retains the existing 64-slot
ceiling, with only four candidate contexts eligible.

Each allocation is rounded inside the preexisting extent before its address is
exposed. Returns retain backing and do not reuse space in a live generation.
Closing root admission still permits descendants of an actually live original
parent. Counted deferred work prevents recycling. Only an internal complete
consumer may recycle a sealed, empty context with zero continuations; successor
generations do not wrap. That transition is occupancy reuse, never physical
backing final-free. There is no public free/retire/recycle command.

The 20 tiny freestanding C controls PASS for this arithmetic/lifetime mechanism.
They do not compile factory.c, execute upstream functions or Linux, prove real
locking/physical allocation, or authenticate a trusted factory. Historical
lineage/birth/handoff/physical inputs and controls remain unchanged.

## Protected create-only boundary

factory.c is an uninstalled builtin candidate with one bounded control
descriptor, four private contexts, one in-flight create and one reply slot.
Requests have fixed little-endian fields, no pointers/byte-cost/layout/free
certificates or qualification flags. The descriptor is 0600 and additionally
checks initial-user-namespace capability plus exact opening mm, TGID, credential
and network namespace. These checks are necessary protection, not sufficient
authentication of the maintained native bootstrap. Root privilege cannot
activate the current incomplete source selection.

Registration and open refuse BEFORE candidate allocation because
lsf_factory_selected_consumer returns NULL. No code falls back to
sock_create_kern. A source-selected consumer must carry the original private
context before ANY outer allocation and preserve every mandatory security hook.
The protected writer/real sealed broker-to-kernel bootstrap is still missing;
arbitrary supplied scope words do not authenticate it. No successful registrar
or factory is claimed.

Closing the descriptor fences roots and quarantines everything; it frees no
backing, recycles no context and permits no reopen. This can retain capacity
permanently. Final-free/RCU consumption and a usable stop/restart are unfinished,
not inferred from descriptor close or an empty view table.

## Concrete remaining integration

The authenticated five whole historical source files (265,502B) and eight outer
functions show why sk_alloc-only ownership is insufficient: __sock_create calls
security_socket_create and sock_alloc/new_inode_pseudo before pf->create reaches
sk_alloc. sock_alloc_file adds file state too. All those upstream statements
remain untouched in this slice. The existing physical recipe is not silently
relabelled as a prepaid factory implementation.

Next source work must implement the actual outer socket/inode/security consumer
and its allocation/failure/destruction paths through the private arena; bind the
actual protected native bootstrap to original accepted owners; then implement
selected protocol/SKB/clone/TIME_WAIT/route/cache/deferred consumers. DNS UDP and
TCP fallback share one original64KiB context while UDP tails remain live.

The first candidate virtual platform is a dedicated virtio-net PCI queue pair
and namespace, one RX/TX queue, MTU 1500 and no mergeable buffers/GRO/GSO/TSO/SG/XDP.
The [candidate fields](prepaid-platform.json) are NOT an installed or resolved
configuration, measured geometry or operator assertion. Other host traffic is
unchanged. Its real virtio/DMA/page/header prelookup RX backing, control reserve,
route/neighbour/security/cache owners and mandatory hooks all still need source
closure. Unsupported LSM/device/offload branches must refuse before allocation;
mandatory security must not be disabled to manufacture a fit.

A maintained 6.12.y source/config/compiler/image/running-BTF identity remains
required before a supported profile; the historical v6.12 preimages are not a
deployment endorsement. No kernel/VM campaign is requested by this source
delivery. Complete allocation bounds, sealed final-free, actual supported
kernel/operator/adversarial and language qualification remain open.
