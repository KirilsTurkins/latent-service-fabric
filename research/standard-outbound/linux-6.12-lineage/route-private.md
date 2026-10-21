# Maintained IPv4 route ownership source

This uninstalled source prefix is bound to Linux 6.12.113 commit
`7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e` and the same sealed upstream archive
as the earlier bind and audit work. It authenticates 42 whole files, 2,429,600
bytes, and 28 exact function definitions. Its 68 derived outputs retain the
previous 51-output bind chain, with only three explicit shared extensions:
one new ROUTE kind and its exact allocator/find/return allowlists in `prepaid.h`,
two private declarations, and the two corresponding factory queue/return
functions. The other 48 previous outputs remain byte exact. Existing kinds,
metadata layout, allocation record count and backing capacities do not change.

## Actual lookup and allocation

The owned socket's existing allocator-born context, address and full generation
are checked before the wildcard key lookup and before the ordinary output-flow
lookup. The original `ip_route_connect` initialization, source-address update,
security flow classification and tandem `ip_route_newports` lookup remain. Both
lookups continue to use the same original flow key and final ports.

The private copies of `ip_route_output_key_hash`, its RCU resolver and
`__mkroute_output` preserve actual namespace/interface checks, FIB/rules lookup,
multipath selection, source-address selection and error returns. Existing FIB
and exception-cache hits still use `dst_hold_safe`; they neither force a miss
nor transfer the original creator's charge to a later caller. On an actual
miss, the private `rt_dst_alloc` copy replaces only its SLUB allocation with a
typed child view inside the same original socket owner's prepaid extent.
Original `dst_init`, route initialization, cache publication, compare/exchange
loser cleanup, exception locks and uncached-list handling remain authoritative.
There is no ordinary allocator fallback after an owned refusal or exhaustion.

IPv4 does not use `dst_cow_metrics_generic` for this producer. Its actual
`ipv4_cow_metrics` is the maintained WARN/NULL implementation. Routes borrow the
real FIB metrics with `ip_dst_init_metrics`; their original refcounts and
`ip_dst_metrics_put` cleanup remain unchanged. The corresponding administrative
metrics producer and FIB final-return code are authenticated, unmodified inputs.
Holding a reference to existing administrative state is not a new private
allocation or a proof of its complete shared-infrastructure accounting.

`rt_dst_clone` derives a new private view from an actual original ROUTE birth,
preserving the maintained field-copy algorithm. Ordinary route objects retain
their exact original allocator. No later pointer claim can adopt such an object.
An owned route with an unsupported LWT state is refused rather than copied into
an unclosed producer. The selected baseline already has LWTUNNEL and allocating
netdevice reference tracking disabled; this derivation does not change either
configuration. A private producer refuses an allocating tracker configuration
before lookup or view allocation. Mandatory security and XFRM stay enabled.

## Explicit policy boundary

Normal sockets retain the complete original `xfrm_lookup_route` call. The
private prefix currently supports only the original no-policy fast-path subset.
Socket policy is tested first, including when the route has a real operator
`DST_NOXFRM` flag. If socket policy exists, or a network policy lookup is needed,
the prefix returns `EOPNOTSUPP` before mandatory LSM matching, dummy destination,
SA resolution, key-manager, bundle or secondary-route allocation. Even a policy
which might match no packet or allow without transformation is outside this
subset. The flag is never forced and XFRM is never disabled.

The original independent default BLOCK decision and its loopback exception
remain. A zero policy count alone does not grant permission. The same observed
socket-policy, route-flag and policy-count conditions as the maintained fast
path establish this subset; no claimed policy snapshot, caller certificate or
later address registration expands it. Completing the actual policy/LSM and
transformed-route allocation graph remains required before a broader profile.

## Original reference and final-return owners

Actual socket, SKB, FIB and exception-cache references remain in the original
`rcuref`. A nonfinal put neither queues a continuation nor returns a view. Only
after the original final `rcuref_put` does the private hook record one bounded
continuation, immediately before the original `call_rcu_hurry`. The actual
`dst_destroy_rcu` callback still calls the original destruction algorithm.
Operations cleanup, metrics, netdevice reference and LWT release precede the
private view return. Any XFRM child pointer is copied before that return; the
original child-release operation remains after it. The immediate final-put path
keeps its original synchronous algorithm and needs no invented RCU continuation.

Unknown in-extent pointers, duplicate returns, stale generations, poisoned
owners and failed queue transitions remain charged and never reach SLUB.
Normal pointers retain their original allocator return. Root close, an empty
descriptor table, cache replacement intent or a grace-period guess cannot
release a route or the backing. Returned views do not recycle cursor space
inside a live context generation. The TCP96KiB/DNS64KiB reservations, 256 original
records, four contexts and full backing ownership remain unchanged.

## Controls and remaining closure

The supplemental freestanding programme executes exact selected maintained
`dst_init`, `rt_dst_alloc`, `rt_dst_clone`, release/destruction and factory
bodies with explicitly serialized type/FIB/refcount/RCU doubles. The original
general-cache allocation remains RED. Thirty-four current lifetime/refusal
controls pass. They are not actual Linux layouts, route lookups, XFRM policies,
cache concurrency, packet I/O or RCU execution. The focused Python controls bind
whole-source identity, normal-body projection, original metrics, final-return
order and the explicit policy boundary. No kernel build was performed for this
source packet.

Private routes can remain held by the original shared FIB/exception caches
after a connection closes. This prefix retains the original owner for that
whole lifetime. It does not claim a bounded cache drain or final-free producer
for those cache parents. A future drain must hold actual FIB/nexthop lifetime,
revalidate exception membership beneath the original RCU/lock regime and win
the original cache-reference removal before releasing it. A stored cache-cell
address alone is insufficient; FIB/exception deletion and address reuse can
otherwise make that pointer stale.

Remaining required work includes that trusted cache-parent retirement,
policy/LSM/XFRM acquire and bundle paths, ICMP-created exception state, RX/SKB/
NAPI/page and neighbor producers before socket lookup, complete shared kernel
infrastructure and compiled layout bounds, DNS and protocol deferred owners,
trusted factory installation, a sealed running kernel/BTF final-free producer
and actual bounded conformance. The selected complete factory consumer remains
NULL, all physical accounting/installation qualification flags remain false,
and normal provider installation remains Unsupported.
