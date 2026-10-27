# ADR-0064: Admit q35 IRQ infrastructure before birth

- Date: 2026-10-27
- Status: Proposed; owner decision required. No implementation or runtime qualification.
- Decision owner: [provider #738](https://github.com/KirilsTurkins/latent-service-fabric/issues/738).
- Contract: [#737](https://github.com/KirilsTurkins/latent-service-fabric/issues/737),
  [ADR-0061](0061-bound-standard-outbound-streams.md) and its
  [recorded owner acceptance](../docs/runtime/outbound-stream-acceptance-2026-10-16.md#accepted-scope).

## Decision requested

Approve an original node-lifetime reservation for the bounded shared IRQ
capacity introduced by the selected q35 provider, admitted through existing
accounting **before its covered kernel allocations or publication**. Keep
tenant/operation Roots and fresh connection leases separate. Select the initial
qualification topology below. This is a proposed ownership bridge, not an
existing admission API, an accepted amendment or permission to enable IRQs.

The existing userspace provider admission reserves 1 MiB before protected
factory entry; neither it nor the separate accepted-operation owner supplies
a kernel node-bootstrap attachment.
[The actual API](../crates/latent-capabilities/src/broker/pools/protocol.rs)
charges existing provider metadata: 1 MiB is the per-reservation ceiling,
not a global node/tenant aggregate quota. The native prototype separately
checks its covered factory/bootstrap footprint against
[`LSF_BOOTSTRAP_CEILING`](../research/standard-outbound/linux-6.12-lineage/prepaid.h)
of 1 MiB. Neither fact establishes an existing node-lifetime parent or a
combined node/operation admission API; that lifecycle attachment is missing.

The requested decision includes creating and attaching that original parent
before covered births, with node and factory shares partitioning the SAME
1 MiB covered envelope, never an additional node allowance alongside the full
factory reservation. Its genuine charge must participate in existing configured
provider accounting alongside operation/tenant charges, without duplication or
reparenting already-born state. The combined admission/partition proof must be
implemented; it cannot be inferred from either current ceiling or `NodeFixed`.
The 512 KiB private backing, 192 KiB infrastructure tail, 256 records and
64 owners remain unchanged within their existing constraints. The proposal
creates no second ledger, cap increase, cursor reuse or physical refund.
There is no evidence that the complete IRQ graph fits these bounds or that
192 KiB remains available. If a complete peak cannot fit, selection must fail
closed and report the exact unsatisfied bound; this decision cannot waive it.

## Contract and existing OS boundary

The literal [#737 criteria 6 and 10](../docs/runtime/outbound-stream-acceptance-2026-10-16.md#literal-design-criterion-reconciliation)
require native/kernel costs, finite cleanup/quarantine and separate
implementation gates. [ADR-0061's ownership clause](0061-bound-standard-outbound-streams.md#authority-and-ownership)
requires original budgets and existing cleanup owners; its
[gate 1](0061-bound-standard-outbound-streams.md#exact-gates-and-partial-delivery)
requires explicit acceptance of the selected profile and resource bounds.
The October 16 acceptance did not select this new node admission bridge or
CPU topology. This draft requests that additional scoped decision, leaving
the accepted authority, TCP/TLS operations and all downstream gates intact.

Preserve the [existing OS/provider boundary](../research/standard-outbound/linux-6.12-lineage/cleanup-provider-boundary-r1.md#contract-scope).
Original Linux bootstrap objects are references to an existing provider;
they are not retrospectively adopted into the private bank. Their finite
configured capacity, original owner and lifetime remain platform prerequisites.
`NodeFixed` is a classification, not evidence of payment or an admission API.
Any new shared capacity required by this implementation needs original
pre-birth admission and a real owner. If a required allocation already occurred
without that admission, a later lookup or size measurement cannot repair its
provenance. The protected bootstrap integration must establish the boundary
before the covered births, or refuse this profile.

## Proposed initial platform identity

Use the selected QEMU 11.1.2 `pc-q35-11.1` machine, KVM, virtio-net-pci and
pinned Linux 6.12.113 source
`7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e`, without a virtual IOMMU or interrupt
remapping device. Propose exactly one vCPU with `maxcpus=1`, no CPU hotplug,
and a verified one-CPU possible mask. QEMU arguments alone do not prove the
kernel possible mask; any needed protected boot parameter must be separately
bound before use. Keep the existing kernel configuration, including its
`CONFIG_NR_CPUS=64` ceiling, NUMA and security settings. That ceiling is not
an observation of the online or possible CPU count.

Capture the exact emulator/source, arguments, configuration, controller chain
and observed topology in qualification. No emulator archive/signature, boot,
hardware or fit success is asserted here. Topology/controller drift refuses
selection. This initial profile gives no SMP, hotplug, virtual-IOMMU or general
hardware qualification and does not replace historical configuration coverage.

## Coherent implementation and lifetime boundary

Close the whole reachable IRQ graph before opening its gate:

| State | Admission and retained lifetime |
| --- | --- |
| Shared vector matrix, per-CPU maps and sparse/global mapping carriers | Establish original provider capacity and funding before any new growth. Retain new node-owned capacity through actual last use and node retirement; never attach it to one PCI/operation merely because that operation first used it. |
| Device IRQ descriptors, statistics, child/parent domain data and reverse maps, APIC/vector state | Reserve complete typed extents and allocator envelopes before publication, with original Root/bank/parent/generation. Shared nodes that can contain unrelated IRQs need their original shared owner. A private statistics accessor alone does not pay those nodes. |
| MSI/IRQ sysfs, action and proc state, plus selected thread/context children if reached | Include every transitive native birth and temporary/error peak before IRQ enable/publication. Preserve actual request flags and policy; do not add `IRQF_NO_THREAD` or invent a no-threading result. |

Use actual allocating-TU `sizeof`, alignment and dynamic extents, actual
possible-CPU geometry, and native retry/cleanup paths. Preserve the selected
3/3/2 MSI-X attempts: at most eight cumulative per-vector births is not a bound
on shared tree or per-CPU allocator growth. Establish current occupancy and a
complete byte/record/owner peak, including failed attempts and deferred frees.
Use aggregate typed envelopes only where native layout and complete lifetime
prove them valid. A metadata record or logical view return never refunds the
monotonic physical bank or permits address reuse.

Keep original callbacks and ordering: synchronize hard IRQs and any real
threads, finish vector cleanup/timer users, detach proc/sysfs references,
complete sparse-tree/RCU and final kobject release, and prove no remaining
legitimate caller before retirement. Node-owned shared state cannot retire
with an operation or a PCI device. Unknown lineage, incomplete cleanup or an
unproved physical tail retains ownership and reports failure/quarantine.

The [existing final-stack/IRQ relay obligations](../research/standard-outbound/linux-6.12-lineage/cleanup-irq-relay-plan-r1.md#honest-incomplete-paths)
remain. Earlier GRO/NAPI, native writer/race, RX/virtqueue/DMA, task and full
TCP/useful-fit gaps also remain; IRQ accounting cannot certify them.

## Alternatives and approval boundary

1. **Recommended: original shared admission plus complete device closure.**
   Preserves native shared state and its true lifetime. Requires a protected
   bootstrap bridge, complete incremental peak proof and evidence of the
   existing platform providers' finite capacity; none is implemented here.
2. **Source-owned statistics/accessors plus a node reservation.** Can reduce
   one per-CPU allocator coupling, but adds a maintained statistics path and
   still needs original funding for matrix, global maps and deferred users.
   It is not the already-selected ADR-0061 implementation and offers no fit
   proof by itself.
3. **Retain the closed IRQ gate.** Correct when original admission, complete
   lifetime or unchanged-bound fit cannot be established. Another paid prefix,
   post-birth adoption or cap increase cannot substitute for closure.

Owner approval would select the first ownership approach and the proposed
one-vCPU qualification identity for implementation and review. It would not
qualify any allocation, physical retirement, real TCP exchange or production
installation. Until complete source, compiled geometry, peak admission and
focused actual platform evidence pass review, all IRQ/funding/runtime/fit
gates stay closed and the selected consumer remains NULL. #738, #739 and #740
remain independent implementation/operator/conformance obligations.
