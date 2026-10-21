# Private route-cache parent ownership and close drain

This uninstalled source layer follows the exact maintained Linux6.12.113 route
prefix. It retains the original fixed prepaid backing,96KiB TCP/64KiB DNS
allowances and allocation-slot limit. It adds scalar cache metadata inside the
same birth record; it creates no second ledger, hidden queue or allocator.

Before a private route can enter a shared FIB or exception cache, its actual
producer acquires a real fib_info reference or a real leaf nexthop reference.
The reference transfers into that exact live route birth. Unsupported families,
foreign/stale births and an already closed root refuse before publication;
failed transfer puts only the reference just acquired. Normal maintained route
functions and parent destructor bodies remain unchanged.

The original root-close fence and the actual cache hold/CAS or exception
publication share the pool lock. Publication first is visible to the later
drain; close first refuses without adding a cache hold. A failed CAS preserves
the original loser cleanup. Output publication pins the current CPU until its
metadata and actual cache cell agree. Original replacement cleanup runs outside
the pool lock, with its original refcount and exception-lock behavior.

Drain retains a separate real dst_hold_safe while validating the exact live
record, owner and generation under the pool lock. A live allocation record
cannot resurrect a dead destination. It then derives the current cache cell
under original RCU and, for exceptions, fnhe_lock. It never follows a saved
replaceable nh_info, per-CPU allocation or exception pointer. A nexthop reference
does not pin nh_info: current identity is revalidated; even address reuse causes
current cell recomputation. An old replaced info's original retirement remains
responsible for its outstanding cache references.

Only an exact won cache cell drops its cache reference. A replacement belonging
to somebody else is left intact. The temporary drain reference is separate and
returns afterward. The original exception hash/key and ten-node retained chain
bound are used; an unproved longer chain poisons the context and retains the
original owners. No timeout, empty lookup or close acknowledgement certifies
retirement. Original final dst cleanup puts the real parent before the prepaid
view return; the latter refuses uncleared metadata and stale generations.
Backing itself remains held at its original full-retirement boundary.

The source fixture binds45 complete upstream files and42 complete function
preimages, including original FIB/nexthop/exception cleanup chains. Derivation
retains62 of68 preceding outputs byte-for-byte, with six explicit generated
extensions and seven new outputs. No previously owned source file is rewritten.

The separate freestanding reference executes exact selected factory/cache and
maintained FIB/nexthop get/put/exception cleanup bodies with explicitly serialized
type, lock, RCU, refcount and CPU doubles. Original cache bodies reproduce two
failures: publication after root close and a cached route outliving its
unreferenced parent. Current source passes24 lifetime controls, including CAS
loss, actual parent puts, replacement/address reuse, close/publication order,
long-chain quarantine and a dead destination with a still-live birth. Earlier
reference setup/assertion failures are retained separately. These controls are
not actual Linux layout, parallel locking, RCU, FIB/XFRM lookup or final-free
installation proof. Actual Kbuild for this layer is still pending.

The selected factory consumer remains NULL. Complete RX/TX/SKB/page/neighbour,
DNS/deferred allocation closure, compiled-layout bounds, sealed image/BTF and
trusted final-free production evidence, real node/operator conformance and all
remaining #738/#739/#740 acceptance gates remain open. No accounting or
production-enable flag changes from this source layer.
