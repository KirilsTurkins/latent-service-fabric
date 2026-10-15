# User-space state pager

Investigate Linux `userfaultfd` for page-on-demand state materialization and
dirty-page delta capture. **Explicit capability calls remain the portable state
model.** Arbitrary language heaps are out of scope unless their representation
is stable and explicitly designed for persistence.

**Status: source/literature review and experiment design only.** There is no LSF
userfault pager, mapped-state guest profile, kernel qualification or measured
pager benefit. No kernel API, fault handler, Wasmtime memory integration or
performance experiment was executed for this review.
[ADR-0016](../../adr/0016-keep-paging-continuation-eviction-and-fusion-optional.md)
keeps promotion optional and requires later decisions and conformance evidence.

Read the [kernel, engine and research review](upstream-review.md),
[proposed mapping/transaction model](mapping-model.md) and
[evaluation plan](evaluation-plan.md). The website's
[pager guide](../../docs/runtime/userfault-pager-research.md) explains current
availability and the distinction from continuation eviction.

[Draft RFC-0009](../../rfcs/0009-optional-mapped-state-and-fault-ownership.md)
proposes read-only image grants and fault/mapping ownership for review. It
introduces no mapped-state API or kernel qualification.

## Reviewed LSF source

Reviewed on 2026-10-15 against documentation-stack parent
[`7894916f76b2a41d94d45eb7e8f6a708496b068a`](https://github.com/KirilsTurkins/latent-service-fabric/tree/7894916f76b2a41d94d45eb7e8f6a708496b068a).
The embedded store, state WIT and engine composition also match the supplied
development snapshot
[`90cf1f4c87ca24e9a64b077dc2eb501dcef22441`](https://github.com/KirilsTurkins/latent-service-fabric/tree/90cf1f4c87ca24e9a64b077dc2eb501dcef22441).
This stack selects Wasmtime 48.0.6; that snapshot selects 48.0.5. Pooling layout
values agree, with version-scoped identity differences. Engine qualification
does not transfer between those versions by inference.

The original charter's stateless Phase 1 reference is historical. Current
development implements configured transactional state and bounded queries; that
does not establish completion of every Phase 4 acceptance or platform gate.

| Baseline | Source and implication |
| --- | --- |
| Selective state access | [State WIT](../../wit/platform/state/package.wit) uses explicit async reads, scans and staged writes. Values contain owned `list<u8>` bytes; the `page` resource is a bounded query-result page, not a host memory page. There is no mapped-state region API. |
| Bounded retained views | [Embedded store](../../crates/latent-state/src/embedded.rs) uses redb read transactions, age/size/scan limits and selected-value copies. It does not load every service's complete state image per invocation. Expired views fail rather than silently refreshing. |
| Host-owned commitment | The embedded writer checks expectations/mutations and a final acceptance fence with immediate durability; uncertain commit quarantines the store. The [state/effect architecture](../../docs/architecture/state-and-effects.md) owns namespace conflict checks, state/outbox/outcome publication and recovery. Dirty pages cannot replace these owners. |
| Existing memory optimizations | [Engine composition](../../crates/latent-wasmtime/src/config/engine.rs) applies the selected copy-on-write image setting. [Pooling layout](../../crates/latent-wasmtime/src/config/layout.rs) reserves maximum guest memory with zero additional growth reservation and zero configured guard bytes; on-demand differs. These are not measured RSS values or persistent guest heaps. |
| No pager integration | The research directory previously held only its charter. The reviewed runtime selects ordinary engine allocation and capability access, with no userfault registration, fault-service owner or mapped-state interface. |

## Opportunity and actual baselines

The plausible candidate is a large, explicitly formatted immutable/versioned
image with sparse or recurring access. A pager supplies missing contents and may
track writes for a later private delta. Host page size, Wasm memory pages and
state query pages are distinct units; no fixed 4 KiB host-page assumption is valid
for every selected mapping.

Compare against current selective record reads, explicit bounded chunk reads,
ordinary kernel-managed file mappings and eager loading. Add selective prefetch
as a separate policy. A comparison only against copying a whole image would not
establish value over LSF's actual state path.

An eager byte-list return can materialize every source page during the copy,
erasing lazy loading's benefit. Keep a host-internal backing optimization separate
from a guest-visible mapped-state profile, which needs new interface, failure,
authorization and accounting semantics. Neither is enabled here.

## Fault progress is the first gate

A handled missing-page access blocks an OS thread until resolution; a nonblocking
descriptor does not make the faulting instruction an async host call.
[Linux interface](https://man7.org/linux/man-pages/man2/userfaultfd.2.html).
A worker unable to execute cannot reach its next fuel/epoch check. A pager using
only the blocked worker pool, its locks or its own faulting buffers can lose
progress. This is an integration inference, not an observed LSF failure.

Prove bounded fault-service capacity, failure delivery and cancellation before
optimizing latency. Unavailable or unauthorized state must not become invented
zero bytes. Poisoning/signals, closing a descriptor, unregistering a range and a
watchdog timeout are not affirmative activation cleanup. Faults during host copies
and kernel-originated accesses need separate qualification.

## Dirty memory is not a transaction

All materialized pages must belong to one authorized immutable generation or
retained view. Private writes remain staging until a validated host commit. Dirty
tracking neither records every logical read nor supplies serializability: cached
reads do not necessarily fault, and disjoint dirty pages can still have conflicting
dependencies. Preserve current conservative namespace validation initially.

Tracking must cover page installation, subsequent writes, discard/refault and the
capture boundary. Stop all writers before taking final bytes; do not confuse an
atomic page install or bitmap scan with a consistent application snapshot. A
stable persistent format must map validated page changes into accepted logical
updates or an explicitly designed image-publication contract, not mutate redb
database pages as application state.

## Authority, ownership and portability

Bind mappings to the original activation, mapping generation, exact authorized
view/image and bounded offset. Neither an address nor content hash grants access.
Pages must not expose neighboring unauthorized records. Authenticate bytes before
installation using a suitable immutable backing trust model or bounded chunk
proofs rooted in authenticated metadata. Hashing the whole image on every first
access can erase I/O savings.

Faults are not a per-read authorization or budget boundary: resident accesses can
bypass them. A new mapped profile needs a declared grant/view lifetime and
revocation behavior; a transparent optimization must preserve existing operation
checks and meters. Keep logical memory grants separate from resident pages,
source caches, dirty copies, fault queues, I/O and staging charges.

A delayed response for mapping A must never populate mapping B at a reused
address. Preserve the original owner through the actual resolution operation,
synchronize layout changes and drain/fence jobs before reuse. A generation check
followed by an unprotected ioctl is insufficient. Uncertain retirement retains
charges and withholds cell reuse.

The [deployment review](upstream-review.md#deployment-and-engine-constraints)
separates kernel features, per-range ioctl support, device/syscall permissions,
container policy and engine ownership. This remains Linux-specific optional
research; missing support cannot silently weaken a selected profile or trigger
mid-execution replay. No host policy changes are part of this review.

[Continuation eviction](../continuation-eviction/README.md) releases a complete
guest and preserves unfinished computation. Paging changes data residency while
a Store exists; it does not release that Store or provide a durable resume point.
Their combination requires both tracks' evidence, not substitution of one claim
for the other.
