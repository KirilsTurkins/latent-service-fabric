# Maintained SID cache and audit context strings

This uninstalled source slice follows Linux 6.12.113's actual SID-to-string
cache and context conversion. It does not enable the selected consumer or
qualify the complete outbound provider. AVC decisions, the audit formatter,
queued audit SKBs and the remaining protocol allocations still need their
original physical ownership paths.

`tools/host_stream_kernel_sidcache.py` authenticates sixteen complete source
files (1,088,758 bytes) against the maintained official archive and six exact
function preimages. It composes the existing Netport/NetLabel derivation and
preserves their already derived services additions. The result contains 33
derived files. The extra SID-table member is archive authenticated; it is not
represented as independently Git corroborated.

The private context conversion retains the original policy lookup, initial
SID translation, forced/invalid lookup, symbol/MLS formatting and cache/LRU
behavior. Audit strings are children of the actual socket's original live
birth. Cache hits copy strings into the caller's own child allocation without
adopting the cached node. A cache miss reserves its original parent's child
before copying or publishing the node. Failure returns a closed error with
no normal-heap fallback.

The original fixed 256-record table carries each cache node's kind, owner,
generation and table anchor before publication. The original cache lock
remains authoritative. Both normal and private producers queue private
victims under that lock before unlinking, then request the real RCU callback
after unlock. Normal eviction continues to remove stale entries even when
private ownership validation fails; unknown arena storage remains charged
and never enters the normal heap. A callback copies the original birth and
returns only its queued view, without following a possibly dead parent.

Closing takes one bounded record scan. A copied anchor is compared with the
current policy's SID table under original policy RCU; it is not dereferenced
as an ownership certificate. The table lock then protects exact generation
and publication revalidation before deriving any cache address. The original
policy destroy path returns private published cache births before that table
can be freed or its address reused. Queued victims remain owned by their
actual callbacks. Failed or uncertain ownership poisons and retains storage.
The scan does not wait for RCU, walk global cache lists or certify final free.
Genuine late descendants remain charged.

The supplemental freestanding C reference executes actual selected factory
and maintained cache bodies with explicit serialized types, policy, list,
lock and RCU doubles. The original general-cache allocation is RED (exit 2).
Fourteen new cache/string lifetime controls and all nineteen prior Netport
controls pass. They cover private publication, caller-owned cache-hit copies,
LRU eviction, deferred callbacks, normal/private allocator mixing, old policy
destruction, stale generation/anchor refusal, a destroy-between-snapshot-and-
lock race, the original 96 KiB limit, unknown arena storage and unchanged
record/bootstrap ceilings. Undefined-behavior checks in this reference compile
to traps without a runtime library. It is not actual Linux concurrency,
geometry, policy or RCU execution.

The five reserved SID/audit allocation kinds do not authorize unfinished
formatter or SKB producers. Only SID-cache nodes and audit strings are added
to the typed child allocation/return operations here. Backing remains the
original 512 KiB extent, with the same 64 owners and less than 1 MiB combined
bootstrap ceiling. No backing refund, reuse, physical final-free certificate,
kernel installation, TLS qualification or production enablement follows from
these source controls.
