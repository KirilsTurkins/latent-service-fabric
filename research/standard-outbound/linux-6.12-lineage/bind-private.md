# Maintained bind-bucket ownership source

This uninstalled source prefix uses Linux 6.12.113 commit
`7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e`. The closed derivation authenticates
complete upstream files and twelve exact function preimages before rewriting.
It preserves the previously derived protocol, Netlabel, Netport, SID-cache and
AVC and mandatory audit chain. The complete factory consumer remains unavailable.

The actual owned socket already reaches `__inet_hash_connect` and
`inet_csk_get_port`, but the maintained misses allocate bind buckets from SLUB.
`__inet_bhash2_update_saddr` also preallocates a new bind2 bucket before changing
the socket address. These are real producers, not retrospective registration
sites. The private branch validates the original socket's allocator-born
address, full context and record generation, then creates typed child views
inside the same prepaid backing before the original initialization and hash
publication. Both cache identity and network identity are checked. Unknown or
inconsistent origin refuses; allocation failure has no ordinary-heap fallback.

The original port range, reserved-port policy, conflict checks, reuse behavior,
random perturbation, locks, rescheduling, established/TIMEWAIT interaction and
address-change cleanup remain unchanged. Normal sockets retain their original
allocator and all function remainders. Existing cache hits retain their actual
creator's ownership; they do not transfer a charge to the latest caller.
Owned listening inheritance is explicitly unsupported before cache lookup or
allocation. The protected factory's selected profile is outbound IPv4 TCP.

Bind buckets are not RCU-freed. Their original hash locks and empty-list checks
govern lifetime: bind2 stays live while any socket or TIMEWAIT owner remains;
bind1 stays live while any bind2 bucket remains. Only the original destruction
site, after its real unlinks, returns the original view. The address-change
preallocation loser returns at its original unused-candidate cleanup site.
The metadata uses no extra queue or independent ledger. A view's live record
remains charged throughout these real cache users. Root close is not an empty
bucket proof. Poisoned private storage is still logically unlinked when the
original code requires removal, but never falls through to SLUB or an early
backing refund. The original 96 KiB TCP/64 KiB DNS allowances, fixed 256 records,
fixed contexts and monotonic per-context allocation remain unchanged.

The supplemental freestanding C programme executes selected maintained
constructors/destructors, the private allocator/classifier bodies and serialized
list/lock/type doubles. It retains the original general-cache allocation RED
and checks 25 bounded lifetime/refusal cases. It does not execute actual Linux
types, port scanning, TIMEWAIT, networking, concurrency or RCU. Focused Python
controls require exact normal-body projection and source provenance. Neither
programme is physical kernel qualification.

Route ownership remains a separate concrete gap. `ip_route_connect` and
`ip_route_newports` must continue to share the same real flow key and perform
the final-port IPSEC/policy lookup. Their lower chain reaches `rt_dst_alloc`,
`dst_alloc`, FIB/exception caches, metrics COW, `rt_dst_clone`, XFRM and lwt state,
and retains netdevice/reference tracker owners. Those producers cannot be
replaced by a direct route, ignored transform, forced cache miss or guessed
later pointer attestation. Remaining route, RX/SKB/NAPI/page, DNS, protocol
retirement, layout, trusted installation and sealed final-free proof still
block complete allocation closure and production enablement.
