# Proposed pager ownership and transaction model

This is a design for research, not an implemented mapping API or persistence
path. Begin with immutable read-only application data outside the node. The
[evaluation plan](evaluation-plan.md) defines the evidence required before
embedding or adding writes.

Initially trust the kernel, engine, handler, binding table and integrity checker;
consider guest accesses, stored-image bytes and timing/layout races hostile.
Guests receive no fault-resolution descriptor or host range-selection authority.
A compromised trusted handler could install incorrect pages; moving it to another
process alone does not prove its authority is confined.

## Representation and authority

Use one bounded versioned image with fixed-width fields, validated offsets and
lengths, explicit byte order and a checked index. Host pages may span several
records; a mapping must not expose an unauthorized neighbor because protection
works at page granularity. Define padding/tail bytes and sparse-zero regions
explicitly. No raw host pointers, Store handles, synchronization objects or
arbitrary six-language heap representation belongs in this initial format.

Bind each range to the original activation/mapping generation, exact authorized
namespace/view/image, allowed offsets/operations and physical owner. A fault
address selects only an offset within that checked binding, never an arbitrary
tenant, filesystem path or mutable latest object. An approved hash proves content
identity, not access permission.

A mapped-state grant may authorize a different extent than an existing key read.
That difference needs an explicit contract. Fault-only policy checks cannot
mediate resident accesses; specify the accepted view/grant lifetime and bounded
revocation/expiry behavior. An internal optimization under existing calls instead
preserves their current checks, typed failures and meters. Neither can turn a
cached physical page into renewed logical authority or erase already copied bytes.

All pages resolve against the same immutable generation or retained snapshot.
Never replace an expired view with a newer one halfway through an activation.
Retain the real backing/view owner under its existing age and capacity limits.
Read-only access through one file descriptor does not prevent another writer
from modifying or truncating the file; a pinned pathname/fd alone is not an
immutable-image guarantee.
[File mapping lifetime and fault semantics](https://man7.org/linux/man-pages/man2/mmap.2.html)
also require explicit treatment of file bounds and truncation.

Authenticate before installing bytes. Choose protected already-verified immutable
backing or checked chunks rooted in authenticated metadata binding image version,
offset, length and content. Bound proof/decompression work and decoded size.
Whole-image verification must be counted if required; do not hide an eager read
inside a claimed lazy startup. Integrity failures never become implicit zero pages.

## Fault service and progress

Reserve mappings, range metadata, fault-service slots, resident/destination pages,
source buffers, proof scratch and I/O before depending on them. Keep descriptor,
activation, view and pending job ownership affine through actual completion.
Account for page tables, pinned backing/cache and private overlays separately
from logical guest-memory limits; low residency does not enlarge a guest grant.

Fault service requires bounded capacity that cannot depend exclusively on blocked
execution workers. Its buffers, allocator, logging, storage jobs and locks must
not require the faulting guest to run or touch unresolved registered pages. A
bounded handler queue alone does not bound all kernel waiters; bound admitted
mappings, mutators and outstanding work and define saturation recovery.

Coalesce duplicate requests for one original image/page owner without creating
an unbounded waiter list or duplicate charges. Check partial resolution, interrupted
reads, layout changes and descriptor errors. Complete bookkeeping before waking
blocked accesses. A successful ioctl proves page installation, not transaction
completion, cancellation or cleanup.

Define a qualified failure route for unavailable/corrupt backing, denied authority,
expired views, exhausted budgets and handler failure. A faulting instruction has
no ordinary WIT `result` channel. A signal/poison operation needs activation-scoped
runtime recovery proof; host-copy and kernel-originated faults need separate
handling. Returning zeros to let execution continue would invent state.

An outer process supervisor can bound a disposable harness. That does not prove
safe recovery of one activation within the shared node. Do not promote an
in-process profile unless unresolved faults can be stopped and retired within
declared bounds without corrupting other work. Epoch increments and client
timeout responses do not establish that property.

## Mapping retirement and address reuse

The proposed ownership sequence is:

```text
admit exact view and range -> register and service original faults
  -> prevent further guest/host access and stop new fault jobs
  -> retire or fence every original resolution job and blocked accessor
  -> unregister/unmap through the selected engine-owned lifecycle
  -> release buffers, view and reservations -> affirmative cell reuse
```

Synchronize the final ownership check with the actual resolution ioctl and all
layout changes. A response that checked A's generation and later copies into a
reused address can still corrupt B. Keep the original descriptor object owned;
a reused integer fd is not that identity. Observe enabled remove/unmap/remap/fork
events as required by the selected design, or prohibit those transitions under
enforced ownership. Merely observing an event does not serialize an outstanding job.

Closing/unregistering is not a cancellation protocol: it changes interception
and can leave ordinary mapping behavior in place. Prevent further execution before
relying on it, and prove the selected kernel/engine behavior for blocked accessors.
Do not wake a failed access into fabricated contents. Unknown retirement retains
charges and withholds cell reuse under the existing quarantine contract.

If resident-page eviction is later added, dirty bytes must survive in an owned
overlay before discard. Refault must restore the newest private overlay, not
silently reload the immutable base and lose writes. Removal/reset of anonymous
memory can have legal zeroing semantics; that is different from missing durable
state. Test each transition instead of copying VM balloon behavior blindly.

## Private writes and authoritative publication

Add writes only after read-only failure recovery and reuse are demonstrated.
Use a private overlay; never expose authoritative shared state writable across
activations. Install a missing page with the selected write protection already
in place where supported, rather than waking a writer before tracking begins.
Cover anonymous holes, first writes, duplicates, huge pages and tracking epochs.

Synchronous WP and async written-page tracking are different cohorts. For the
latter, process every bounded scan continuation and its final range, with defined
scan/reprotect/reset ordering. A dirty bit may reflect discard or incidental
metadata; it is not proof of a committed business update. Stop all mutators or
use a demonstrated snapshot protocol before copying final bytes. Reprotecting
pages alone does not create a coherent multi-page application version.

Preserve LSF's conservative namespace generation validation initially. Page faults
are not a complete read log, and nonoverlapping dirty sets do not establish
serializability. Define how changed bytes become valid logical mutations or an
explicitly designed immutable-image publication; do not write arbitrary database
storage pages or create a second independent commit path.

The host validates output, authority, cancellation, conflict and all resource
limits before the existing state/outbox/outcome decision. Prepared chunks/deltas
remain staging until that decision durably references them. Commit uncertainty
uses original-identity recovery; it is not rollback proof or permission to rerun
the guest. Base images, overlays and staging payloads retain their owners until
their real recovery/retention references retire.

## Selection, accounting and integration scope

A host-internal backing experiment must show that byte-list copies do not erase
its savings. A guest-visible region requires its own capability/ABI, error,
format, memory/growth and six-SDK qualification. A successful native array access
or a custom on-demand memory creator does not qualify pooled Wasmtime instances.
Never remap engine-owned memory outside its safety contract.

Choose any equivalent non-pager path before execution under the same authorized
view and requested guarantees. A failed or unsupported preflight can reject the
profile. After work starts, fallback must not replay the operation or refresh its
snapshot silently. This study does not authorize sysctl, seccomp, privilege or
host mapping changes.

Preserve logical read/write budgets independently of cache hits, fault counts or
number of dirty pages. Meter physical fault work and prefetch separately, with
finite amplification, storage I/O, time and byte bounds. Keep observations bounded
and tenant-scoped; do not retain private page contents or credentials in traces.
Cross-tenant deduplication is outside the initial study.
