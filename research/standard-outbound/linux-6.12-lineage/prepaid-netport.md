# Maintained SELinux port-cache ownership prefix

This uninstalled prefix derives the real Linux 6.12.113 Netport cache and
SELinux connect call site. It closes the cache entry's allocator, publication,
eviction, policy flush and original RCU return paths. It does **not** close the
whole SELinux policy/AVC/audit chain or enable a provider.

`tools/host_stream_kernel_netport.py` authenticates fifteen whole source files
(1,074,083 bytes) and nine exact definitions against maintained commit
`7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e` and the frozen official archive.
The existing thirteen Netlabel preimages remain unchanged. The added
`hooks.c` identity was independently matched to its official Git blob; the
added `netport.c` is explicitly archive-authenticated without a second Git
corroboration. The recipe composes the existing Netlabel derivation and emits
29 source identities. Unknown, duplicate, changed or CRLF preimages refuse.

## Real cache miss and shared reads

The original connect helper first derives the existing socket birth using
`lsf_prepaid_netlabel_source`. Its original address/class checks, `sock_has_perm`,
`security_port_sid`, `avc_has_perm` and audit data remain. Only an authenticated
private socket selects the private Netport producer. Ordinary sockets retain
their original producer and allocator.

The private miss holds the original `sel_netport_lock`, rechecks the original
protocol/port cache key and obtains the original policy SID. Before writing an
entry it reserves a typed NETPORT child of the original live socket in the
same prepaid backing. An exhausted entry/byte budget returns `-ENOMEM`; there
is no generic heap fallback or success which hides a refused cache allocation.
The original global bucket limit of sixteen entries and original policy/error
results remain. The private branch records the actual bucket in its existing
birth record and marks it PUBLISHED **before** `list_add_rcu`.

Shared cache hits keep the same original owner. Another context neither
adopts the entry nor refunds its creator. The bucket field extends the same
fixed 256 birth records; no second cache-owner table, caller proof or pointer
registration is introduced. The complete factory metadata plus backing still
has its original compile-time one-MiB ceiling. TCP 96 KiB, DNS 64 KiB, fixed
backing and 64 owner slots remain unchanged.

## Eviction, flush and bounded drain

Original eviction and policy flush still unlink entries under the original
cache lock. A normal entry takes its original `kfree_rcu` path. A private entry
is identified only by an already-live typed birth in the protected extent,
changes PUBLISHED to QUEUED, and obtains one original continuation before its
real `call_rcu`. The actual selected callback copies the birth before returning
the view and never reads the object afterwards. Unknown interior, wrong-kind,
duplicate or unexpected-state returns poison and retain; they cannot fall
through to a normal allocator.

Root close seals original admission and runs one finite scan of the existing
255 usable birth records. Each candidate copies only ticket/generation/bucket
under the pool lock, releases that lock, acquires the original cache lock,
then revalidates under cache-to-pool lock order. It derives and dereferences
the node address only if the exact current record is still PUBLISHED. All
removers transition the record under this same cache lock, so an intervening
eviction/flush and even its completed callback invalidate the snapshot before
any dereference. Drain uses no global cache-list search, persistent cursor,
new pin table, fixed sleep, grace-period guess or extra allocation.

Unlinking does not refund physical occupancy. Callbacks keep the original
continuations, and the backing remains charged. A still-live genuine parent
can produce a late descendant after root close; that child stays charged and
may require later owned maintenance. One drain scan is not complete retirement,
and no cache statistic is used as physical-free evidence.

## Evidence and remaining chain

Eleven focused source controls and all fifty unchanged Netlabel/protocol/
factory/outer controls pass. The supplemental freestanding C reference executes
ten selected actual factory definitions plus the selected maintained hash,
find, insert, slow/fast SID lookup and flush bodies. The original generic cache
allocation is RED (exit 2); nineteen current controls pass, including bucket
eviction, policy error, original 96-KiB refusal, normal allocator preservation,
cross-context hit, stale generation, published-return refusal, late birth and
flush/callback between snapshot and lock acquisition. A first reference attempt
retains its unused-variable compile error; the corrected attempt is separate.

The reference uses explicit serialized type/list/policy/lock/RCU doubles. It
does not execute Linux policy, actual spinlocks or Linux RCU, and does not
establish real geometry, allocation bounds or physical final free. No hosted
kernel/object/host campaign has run for this new prefix yet.

The authenticated source also exposes remaining real allocation paths:

- `security_port_sid` can call `ocontext_to_sid` and lazily allocate SID table
  storage through `sidtab_context_to_sid`. No cache-warmness assumption closes it.
- `avc_has_perm` can allocate AVC nodes and extended-permission descendants,
  including replacement in permissive mode. Original mandatory audit remains.
- Audit can allocate its buffer, SKB expansion and SID-to-context strings.
- Protocol RX/SKB/page/NAPI/clone/route ownership, supported compiled layout,
  trusted bootstrap and sealed allocator-final-free proof remain incomplete.

The complete selected consumer remains NULL, active unclosed security hooks
still refuse, normal installation is Unsupported, and ACCOUNTING_QUALIFIED is
false. No security configuration, audit rule, lookup policy, capacity or
production gate is weakened. This is source and supplemental mechanism evidence,
not full #738/#739/#740 acceptance.
