# Partial physical allocation plan and remaining closure

This is an uninstalled source prerequisite for #738/#739/#740 under the accepted
ADR-0061. It authenticates 25 complete files (2,415,384 bytes) and 37 allocation/
lifetime functions at historical Linux commit
`adc218676eef25575469234709c2d87185ca223a`. Eighteen files add 2,011,850 bytes to
the seven-file cookie handoff baseline. These observations are a partial graph,
not a complete call graph or a maintained/running kernel/config/BTF binding.
There is no kernel build, installation, live factory or physical qualification.

The exact file identities and function texts are recorded in
`tools/tests/fixtures/host_stream_kernel_allocation_graph.json`. The additive
recipe requires every whole preimage; a different patchlevel, missing/extra
member or changed byte refuses. It fetches nothing implicitly:

    python tools/host_stream_kernel_physical_derivation.py --source-dir exact-linux-source --output fresh-derived-source

The 18 added files are emitted unchanged. The three earlier networking files
retain every upstream statement, all earlier admission and cookie-handoff
insertions and every pre-free copied token. Exactly five existing post-allocator
notifications now call a private allocator-return keeper. The old recipes,
mechanisms, controls and historical observations are not rewritten.

## Slot return is not backing-allocation retirement

The authenticated `__slab_free` can retain objects in a partial slab;
`napi_skb_cache_put` retains headers in a per-CPU cache and may free a batch later.
`free_slab` can defer backing destruction through RCU. Thus a callback after
`kmem_cache_free`, `kfree` or bulk return cannot alone prove that a slab/page/
allocator-cache owner no longer exists. A fragment or page-pool return has the
same limitation. Existing post-allocator model results cannot be promoted to a
complete physical-kernel result.

The additive keeper moves the original captured record into `PHYSICAL_HELD`.
Its full original charge, owner/allocation generations and nonempty table slot
remain. This phase cannot parent a new allocation or be reused. A duplicate,
stale or mismatched return poisons without refund; the historical object-free
helper also refuses a held record. There is no release operation for it. All
five object kinds are retained, including separate socket, TIME_WAIT, ordinary
SKB header, physical fclone header block and data-head allocations. Normal
capacity can therefore exhaust permanently; this is conservative retention,
not completed retirement or a usable supported profile.

## Disjoint pre-allocation consistency plan

The new private planner uses the same original checked bundle, owner and 256
allocation slots. There is no second ledger/table, retry, heap allocation or
capacity increase. TCP remains 98,304 bytes and DNS 65,536 bytes. It checks the
entire one/two-record sum and available slots before the original bundle can
reserve its first record. Factory roots are socket-only; descendants require
the original live parent and complete copied admission. Live parents can still
produce prepaid descendants while their owner drains.

For the closed constructor shapes, the plan distinguishes:

- Object bytes from the complete backing extent. The latter is charged.
- Aligned payload plus aligned shared-info within one data-head extent. Shared
  info is not a third separately charged allocation.
- Both logical fclone SKBs within one physical header block, separately from
  their shared data extent. A logical view is not another physical block.

Overflow, zero/unknown sizes, insufficient/unsorted classes, shared-slab facts,
unsupported origin or incomplete geometry refuse. A geometry struct is only a
private consistency input, not an authentication interface. **The actual
constructor adapter supplies no geometry and still refuses before allocation.**
Only a future compiled, reviewed layout/factory can provide real facts. The C
reference supplies explicit invented test geometry and origin/cookie doubles;
neither its numbers nor an operator/caller certificate qualifies a layout.
The private plan does not authorize a currently missing clone-view handoff,
head replacement, NAPI/page-pool or route allocation path.

## Source-observed graph and precise open work

| Path | Source-observed ownership/lifetime | Required implementation before support |
| --- | --- | --- |
| Socket and TIME_WAIT | Earlier exact constructors and copy/cookie handoff; deferred descendants can outlive close | Trusted pre-first-allocation factory scope; all socket security/protocol/auxiliary allocations; actual slab/backing bounds and final-free lineage |
| Linear TX SKB | `tcp_stream_alloc_skb` allocates header before socket page-fragment data; `__alloc_skb` has small-head/rounded/emergency allocator choices | Bind every allocator choice and physical extent before entry, including ancillary and emergency paths; no requested-length estimate |
| Fclone, clone and copied/expanded heads | `skb_clone` may reuse its second view or allocate a separate header; `pskb_expand_head` allocates before old shared data drops | Alias/reference lifetime tied to original physical records; new head prepayment without refunding still-shared old data; complete copy/coalesce/retransmit paths |
| RX before socket lookup | Driver data can precede `__build_skb`; NAPI header-cache refill is bulk; `napi_alloc_skb` uses small/normal page fragments | Trusted bounded infrastructure or preallocated RX owner **before** NIC/page/header allocation; a later socket, `skb->sk`, task context or endpoint lookup cannot retroactively pay |
| Fragment, page-pool and bulk paths | Whole/compound backing pages, fragment references, DMA/cache/ring recycling and deferred pool destruction | Complete driver/NAPI/GRO/GSO/XDP/DMA/page-pool closure; one backing owner across all views; physical final-free rather than pool return |
| Slab/kmalloc caches and metadata | Partial slabs, optional slab metadata, allocator rounding, RCU and per-CPU backing-page caches | Source/config-derived complete physical costs and separately prepaid bounded shared infrastructure, or exclusive whole extents; no per-object refund of retained backing |
| IPv4/IPv6 routes and neighbours | Separate route slab, metrics/neighbour allocations, head expansion and deferred route destruction | Bound/classify all shared/per-destination owners and ancillary policy hooks before allocation; cover invalidation/currentness and final descendants |
| DNS and all deferred close work | Current source capture includes UDP/page/IP/TCP allocation inputs; this is not a DNS allocation proof | Complete resolver/send/receive/error/timeout graph under original64KiB, descendants during retirement, and sealed final consumer linked to original host quarantine |

This is deliberately not a claim to enumerate every kernel allocation. Driver,
architecture, allocator/debug/security/netfilter/BPF, error and configuration
branches outside these files remain unqualified. The graph records every shown
node's physical closure as false.

## Trusted classification and final consumption

No current registrar binds a kernel owner to the eight original sealed scope
words. A real factory must derive that identity from the actual admitted
activation/tenant/publication/provider/session/epoch and original retained
charges; it cannot accept arbitrary userspace assertions or create a second
allowance. Before-lookup traffic needs its own bounded trusted infrastructure
classification before allocation, including genuinely unowned/denied traffic.
The current unfiltered experiment intentionally cannot certify a normal kernel.

A supported build must bind the complete allocation graph and compiled layout
to the maintained kernel image/config/compiler and the actual running kernel/
BTF. All relevant physical allocation/free paths and shared fixed infrastructure
must fit the original reservations before socket creation. The sealed private
backing producer and original bounded maintenance owner must then consume a
nonreusable terminal fact without losing scope/generation or admitting later
unaccounted descendants. No such producer or consumer is supplied here.

`ss`, FIN/RST, an absent descriptor, allocator-slot return, elapsed time, sampled
plateau, buffer setting, a bare page-return event or an empty logical mechanism
cannot substitute for those gates. The normal provider remains unsupported;
`ACCOUNTING_QUALIFIED=false`. All physical/kernel/production criteria stay open.

## Supplemental controls

Two old-model controls exit2: requested-byte inputs fit while the disjoint
whole-extent plan cannot, and post-slot-return accounting refunds model backing
that remains live. Eighteen new controls pass, including exact scope/parent,
rounding/disjointness, fixed-slot denial, descendants during drain, all five
held kinds, duplicate/stale returns and the still-closed actual constructor.
The actual private keeper/constructor/core translation units execute under
explicit C geometry/origin/cookie/spinlock doubles in the cached freestanding
Wasm reference. These controls do **not** execute the 37 upstream functions or
Linux, measure physical allocations or authenticate any numeric layout.

Nine additive source controls authenticate the frozen graph, preserve all five
pre-free copies and original statements, check source drift refusal and retain
the normal installation gate. Every earlier C input and source-control body
remains unchanged; no broad guest, native-host or kernel campaign is added.
