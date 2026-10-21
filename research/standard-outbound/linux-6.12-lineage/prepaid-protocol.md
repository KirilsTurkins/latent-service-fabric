# Maintained private protocol and composite LSM lifetimes

This is uninstalled source for the existing protected create-only factory. The
selected consumer remains `NULL`, normal provider installation remains
Unsupported, and every complete allocation, kernel, BTF, final-free and
production qualification gate remains false. No kernel, host or native engine
was built for this slice.

The [deriver](../../../tools/host_stream_kernel_protocol.py) authenticates six
whole files (597,298 bytes) and 21 exact definitions at maintained Linux
6.12.113, commit `7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e`. It emits private
constructor clones alongside original public functions. The original
`adc218676eef25575469234709c2d87185ca223a` source and evidence are unchanged.
The 17 prior outer-function preimages match where reused; their old whole-file
identities are never relabelled current.

## Actual constructor path

The private `__sock_create` clone calls the real security create hook, uses the
same-context prepaid outer inode/socket, and requires the actual static IPv4
family before its real module get. Its private `inet_create` clone requires the
actual TCP protocol and stream operations, performs the original initialization
and error cleanup, and uses the private `sk_alloc`/`sk_prot_alloc` clones. Unknown
protocol/family/module selection refuses without an autoload or normal allocator
fallback. Public constructors retain their original allocation and initialization.

Private protocol storage receives its context and ticket at allocation, before
security or publication. New fields lie inside `sock_common`'s explicitly
noncopied region; normal `sk_prot_alloc` clears them. A later clone or TIMEWAIT
consumer must establish its own birth, not inherit a copied parent origin.

The maintained passive-netns references, memcg/cgroup ownership, `sk_owner`
initialization and release, security hooks, module ownership and failure labels
remain present. In particular the real module owner is copied before protocol
storage returns. Private arena sockets select the actual `SOCK_RCU_FREE` flag
before publication: a bump arena cannot inherit SLUB's typesafe-by-RCU reuse
contract. The unchanged original wmem/reference/destructor/RCU chain still
determines when protocol storage may return. This is not a measured RCU bound.

## Composite security blobs

The private inode initializer preserves the original full initializer and its
`GFP_NOFS` security allocation priority. Both private security allocators retain
the original LSM hook loops and original error cleanup. Only the composite
inode/socket blob allocation uses the existing prepaid context. Actual compiled
`blob_sizes` must fit its remaining original allowance before allocation; there
is no cache, kmalloc, retry or enlarged allowance fallback.

The same original 256-record table marks inode or socket blob kind at birth,
under the pool lock before an address is published. All records still inherit
the complete owner scope and generations. No new registration table, public
pointer binder, userspace certificate or release operation exists. The static
factory-size assertion must still fit the original 1 MiB bootstrap ceiling.

An inode's composite LSM blob has its own original RCU callback and can outlive
the inode. Its callback cannot consult a freed inode. Return routing compares
the address to the already-owned fixed backing, then requires its exact live
birth record, type and owner generation. It never reads before an arbitrary
normal cache pointer. An outside-backing pointer uses the original normal free;
an inconsistent inside-backing pointer poisons and retains instead of reaching
SLUB. This is return routing, not retrospective admission.

Before the original `call_rcu`, exactly one continuation is attached to that
live inode-blob record. Generic object return cannot refund a typed blob. The
actual blob callback copies its private ownership before calling the original
LSM `inode_free_security_rcu` hook; only after that hook may the blob view and
continuation retire together under the pool lock. Normal socket LSM free hooks
likewise precede their view return and original `sk_security = NULL`. Unknown,
duplicate, wrong-kind or stale-generation returns refuse. Returning a view
does not free backing pages, refund their charge, or reuse space within a live
generation. Future context recycle still requires all real objects and deferred
callbacks to retire; an unaccountable callback poisons rather than infers that.

## Evidence and remaining real consumers

Twelve source controls and all 24 original factory/outer source controls pass.
The tiny freestanding Wasm reference executes the exact selected LSM
allocation, error and callback bodies with explicit serialized cache, type, LSM
and RCU doubles. The unchanged general composite allocator is RED (exit 2);
twelve current controls pass (exit 0), including independent inode-blob RCU,
hook failure, cleanup ordering, duplicate/wrong-kind/stale refusal, original
96 KiB admission and retained backing. The first attempt's two signed-comparison
compiler warnings are retained; the guarded casts were corrected before the
passing run. All twenty earlier prepaid arithmetic/lifetime controls also pass
against the changed header, with their original source and oracles unchanged.
This is supplemental C mechanism evidence only: actual LSM
implementations, Linux RCU/locks, compiler object geometry and physical free
have not executed.

The active-hook preflight remains closed. This slice routes the composite blobs
but does not pretend their nested producers are closed: actual SELinux/Netlabel
secattr, category, CIPSO/CALIPSO and cache ownership, other active LSM hooks,
namespace debug trackers and dynamic congestion-control state still need an
authenticated prepaid path. No SELinux/Netlabel configuration is disabled or
hook skipped to obtain success. The fixed kernel source seed remains intact.

The actual protocol descendants (TX/SKB head/clone/page, request/TIMEWAIT),
route/neighbour caches, DNS, RX-before-socket-lookup/NAPI/virtio ownership and
shared infrastructure must also close within TCP96KiB/DNS64KiB, fixed slots
and the original backing. A trusted source-selected bootstrap, resolved
configuration, compiled layout/image/BTF and sealed real final-free producer
remain required before selecting or installing any complete factory consumer.
