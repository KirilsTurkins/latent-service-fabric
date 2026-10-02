# Optimistic state sessions

`latent_state::session::StateSession` implements host-internal point reads,
puts, deletes, original stale-edit preconditions and paged bytewise prefix
scans. It borrows one actual `ReadView` on fixed storage workers. The runtime
retains the affine protected physical-view owner across guest calls and queues
its retirement on those workers. A session checks the original view identity,
namespace incarnation/schema, current operation authorization, lifetime and
limits; it never silently acquires a newer snapshot.

One host-derived tenant/namespace and optional entity key space is selected at
acquisition. Namespace generation covers every entity conservatively. Every
eligible command plan compares the exact original namespace row inside the
actual atomic writer and advances its generation once. This detects lost
updates, write skew, absence creation, blind writes, delete/recreate and prefix
phantoms, including empty scans and changes beyond returned pages. It may also
conflict with unrelated changes in the namespace. Generation exhaustion rejects
instead of wrapping; conflict never repeats guest execution.

Staged values and deletes overlay the captured snapshot. Pages merge the
overlay and native bytewise order. Cursors bind session, physical view, query
prefix and overlay generation; they are finite, consumed once, and invalidated
by staging or close. They do not survive invocation, restart or view retirement.
A byte ceiling can return fewer entries than requested with continuation; an
oversized first entry rejects. Version tokens bind namespace/incarnation/entity
and key. Original stale-edit preconditions remain distinct from activation OCC.

## Finite profile

| Resource | Default and hard bound |
| --- | --- |
| Guest key/value | 1024 bytes / 1 MiB; canonical metadata profile also applies |
| Aggregate attempted reads/copies | 4 MiB default; 16 MiB maximum |
| Distinct observed keys | 1024 |
| Staged keys/attempted bytes | 128 / 8 MiB |
| Host calls | 256 default; 4096 maximum |
| Page entries/encoded bytes | 128 / 1 MiB |
| Open cursors/pages | 16 / 32 |
| Logical age | 30 seconds |
| Internal engine key/record | Explicit production profile: 4096 bytes / 2 MiB |

Attempted copies and overwritten staging remain charged monotonically. Native
snapshots remain physically charged after logical expiry/close until actual
view retirement. Namespace state quota accounting shares one atomic usage row
across entity key spaces. State cells, retained tombstones and usage records
have closed versioned binary formats; their decoders check lengths/counts
before allocating application buffers. A malformed row is a storage failure,
and storage failures are exposed separately for the physical owner's gate.

Sealing consumes the session and returns a private validated `StatePlan`.
Only the complete host command/result/intent/inbox coordinator appends it to an
atomic envelope and applies the final authority/cancellation fence. There is
no guest or session commit method. The original prototype independent
`StateBackend::commit` is deprecated because it cannot establish this boundary.
Query mode rejects staging and sealing and creates no durable command, result,
inbox or outbox records, or state generation changes.

## Evidence and integration boundary

On 2026-09-30, all 35 state-library tests passed on Windows and actual Linux
with the pinned Rust 1.97.1 Bookworm image. Strict Linux all-target Clippy passed.
Sixteen new engine-backed schedules cover the isolation, page/cursor, quota,
malformed-record, maximum-size, overflow and physical-view accounting cases.
The concurrent history uses an explicit barrier: both writers read the same
version before competing, exactly one commits and the other conflicts.

This evidence covers the state read/staging and engine OCC layer. The protected
physical-view owner, sealed namespace policy adapter and complete envelope are
integrated by their respective Phase 4 owners. It does not claim a guest runtime,
six-language node execution, complete query ticket delivery, or power-loss
qualification. Existing signed qualification receipts are unchanged.
