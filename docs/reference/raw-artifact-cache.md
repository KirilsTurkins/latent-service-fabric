# Bounded raw artifact cache

`latent-artifacts::RawArtifactCache` stores replaceable, digest-addressed bytes
under one shared filesystem owner. It supports package-manifest and blob keys.
The cache verifies exact lengths and SHA-256 identities; a hit grants no
publisher trust, catalog admission or execution permission.

The raw owner is a Rust host API; the OCI library can optionally share it. Configuring it does not
create a guest instance, service process, listener or service-specific worker.
Standalone node and operator CLI composition remain separate delivery work.

## Storage ownership

| Data | Owner and reclamation rule |
| --- | --- |
| Published component, original package/evidence and `COMPLETE` | Authoritative catalog content; raw-cache eviction never deletes it. |
| Lifecycle records and selected evidence revision | The [lifecycle store](release-lifecycle.md) retains and reclaims these through its own durable transactions. |
| Cached manifest/blob bytes | Replaceable cache entries; only unpinned entries can be reclaimed. |
| Incomplete cache writes | Reserved cache staging; cleanup recognizes only this cache's owned names and format. |
| Active file reads and fills | Their affine owners retain the root lock and reservations until work actually stops. |
| Returned verified buffers | A compact memory ledger charges their bytes until the buffers are dropped. |
| Selected deployments and rollback dependencies | Their authoritative release content remains retained, independently of cache residency. |
| Prepared code and active activations | Existing runtime ownership applies; reclaiming raw downloads does not refund compiled code or execution resources. |

Retiring a release changes its eligibility. It does not authorize removal of
authoritative release directories. Physical deletion of those directories is
outside the raw cache's ownership.

## Reservation and pressure behavior

The cache independently bounds disk bytes, entries, compact metadata, staging,
object size, pins, reads, retained read buffers, work slots and startup scanning.
Bounds are shared by the owner. A small configured cache may reject an otherwise
valid package object; its limits are never raised automatically to make it fit.

| Budget | Default | Hard maximum |
| --- | --- | --- |
| Resident plus reserved disk bytes | 256 MiB | 4 GiB |
| Entries / compact metadata | 1,024 / 2 MiB | 65,536 / 64 MiB |
| Staging entries / bytes | 2 / 128 MiB | 32 / 512 MiB |
| Single object | 64 MiB | 256 MiB |
| Reserved plus retained read bytes | 128 MiB | 512 MiB |
| Read owners / pins / work slots | 8 / 64 / 4 | 64 / 4,096 / 32 |
| Recovery inventory entries | 2,048 | 131,072 |

These ceilings describe admissible ownership rather than eager allocations.
`RawArtifactCacheLimits` values must be positive and fit all applicable ceilings;
metadata must also cover fixed owner and configured handle bookkeeping. Pending
fills consume entry capacity, and retained `RawArtifactBytes` continue to consume
read-owner capacity. Recovery charges aggregate encountered payload bytes against
the disk limit, including corrupt objects and staging before cleanup. Reopening
with tighter limits can therefore fail instead of silently deleting valid content
until it fits. Zero-length objects remain valid and consume entry/pin capacity.

Acquire a write reservation before accepting its payload work. Acquire a read
reservation from a file pin before scheduling a read or allocating a cache-owned
result. These admission methods perform short bookkeeping without filesystem
I/O. They fail promptly under contention or exhausted capacity.

Reclamation has its own reserved work object. Execute it on a blocking thread;
it first reconciles abandoned owned staging, then selects unpinned entries by deterministic least-recent use, with an exact key
tie-break. Restart seeds recency from key order, so a cache hit does not require
a persistent write. A fully pinned cache applies pressure rather than taking a
reader's backing file away. Concurrent fills of one key do not accumulate a
queue of waiters.

Synchronous file operations must run in an explicitly bounded blocking context.
Move the reservation and any caller-owned buffer permits into that work. Dropping
the requesting future must not release capacity while a worker still owns its
files or buffers. Dropping an unused reservation performs no file I/O.
An async deadline cannot force a running kernel filesystem operation to stop:
its reservations remain held, and a result consumed after the deadline is rejected.

`RawArtifactRead::read_verified` returns `RawArtifactBytes`, which exposes borrowed
bytes and retains their memory charge. `read_into` instead verifies into an
exact-sized caller-owned buffer; the caller must keep that buffer's own budget
alive through the actual work and discard it on failure. Neither path produces
an execution capability.

## Publication, recovery and corruption

Publication verifies the borrowed bytes, writes and synchronizes owned staging,
then atomically publishes a complete object. Index adoption follows successful
durability. Readers receive exact-object pins and independently verify the bytes
read. They cannot observe a partial object as a successful hit.

An invalid object loses eligibility for new pins. Existing owners remain
accounted until they stop; a replacement cannot reuse their invalid incarnation.
Missing or corrupt cached data can be reclaimed and downloaded again. This
recovery does not repair or bypass corruption in an authoritative catalog.

Unlink or synchronization failures retain conservative disk and metadata charges
until reconciliation. Recovery has a finite inventory limit and recognizes the
cache's own format and paths. Unknown operator files and links are preserved;
their presence can reject opening or reclamation, and they never become recursive
cleanup targets. Opening the same root concurrently
is rejected while a cache or its file-backed work still owns it.

Durable cache storage follows the standalone catalog's supported Unix filesystem
boundary. Unsupported platforms reject opening before mutating the root. The
uncached OCI adapter remains available independently.

## OCI integration and authorization

Use `HttpOciRegistry::new_with_cache(config, cache)` for complete package
pulls. Every pull fetches the manifest from the configured registry. A tag is
resolved once and its exact checked descriptors select all subsequent blobs.
No mutable tag-to-package authority is persisted.
This integration populates only blob keys; manifest keys remain available through
the independent raw owner API.

A cached blob still requires current authorization for that registry path.
The adapter requires a successful remote `HEAD` before using its local payload,
an exact `Content-Length`, and a matching digest header when supplied. A registry
returning `405` or `501` receives an ordinary authenticated, integrity-checked
`GET` instead. Other failures remain errors. An authentication failure cannot
be converted into an offline cache hit. The complete package's configuration,
layer associations and format checks apply equally to hits and downloads.

Only reclaimable entry/disk/metadata pressure triggers an automatic cleanup pass:
at most 16 examined entries, further capped by the recovery inventory limit, then
one write-reservation retry. Oversized objects, active fills, work contention and
other non-reclaimable limits do not trigger eviction. Remaining pressure is an
error; the adapter does not silently switch to uncached operation. Construct the
uncached client explicitly when that is the intended policy.

The adapter retains its transfer and output-buffer permits on both paths. Cache
work and OCI output ownership use separate bounds. Existing low-level OCI reads
and referrer discovery retain their documented behavior; the optional cache
does not add an unauthenticated digest-read endpoint.

Raw cache eviction never restores revoked, retired, policy-disallowed or
incompatible releases. Preparation and activation still require the exact
catalog owner, lifecycle generation, runtime profile and, in enforced mode,
current admission authority and proof. Only an activation already accepted at
the lifecycle cutover may finish.

## Observation

The cache snapshot reports aggregate resident/reserved/pinned disk bytes,
metadata, read-buffer ownership, work and staging usage, deletion-pending bytes
and fixed hit/miss/eviction/corruption/pressure counters. These are storage and
ownership measurements, not process RSS. Pinned and deletion-pending values are
subsets of charged data, not extra physical copies.

The OCI cache usage accessor reports the configured owner's actual snapshot.
Neither observation enumerates every release or creates per-digest metric labels.
Hit/miss counters describe key-pin lookups, not completed downloads or admission
decisions. Counters belong to the current owner; reopening starts a new observation
period, including any corruption discovered during that recovery.
