# RFC-0009: Optional mapped state and fault ownership

- **Status:** Draft
- **Authors:** LSF project contributors
- **Created:** 2026-10-15
- **Target milestone:** Phase 7 user-space pager research

## Summary

Propose an explicit opt-in contract for read-only access to a bounded immutable
state image, with a finite mapping grant and owned fault lifecycle. A host-internal
pager must preserve existing capability operations; a guest-visible mapping needs
its own reviewed interface and permission semantics. Neither may be enabled as
a transparent replacement for current state reads without that evidence.

The decision requested is the scope, grant/view lifetime and retirement contract
below. This draft installs no pager or guest API. The
[pager research](../research/userfault-pager/README.md) remains the investigation
and experiment basis; unresolved fault recovery is a promotion blocker.

## Motivation

Current state access already retrieves selected bounded records and returns
owned byte lists. Fault-driven memory can block shared workers and lacks the
ordinary typed error channel of an async state call. Resident accesses do not
necessarily fault, so fault-time authorization cannot implement per-operation
checks silently. A separate mapped contract makes those differences reviewable.

## Detailed contract

### Immutable images and explicit grants

Start with one versioned read-only data format containing bounded offsets/lengths,
defined byte order and explicit tail/padding semantics. Arbitrary language heaps,
native pointers and Store-local resources are outside scope. Host pages must not
expose neighboring records outside the granted extent.

The host binds a mapping to its activation/generation, exact authorized view/image,
allowed extent, immutable content identity, maximum lifetime and physical owner.
The mapping grant authorizes that extent for its declared finite lifetime; it is
not a hidden expansion of a key-read grant. Bound it by the original activation
deadline and selected view/grant expiry, without renewal on a later fault.

Revocation denies new mapping admission and unauthorized page resolution, and
requests stop of accepted mapped execution within the profile's declared bound.
Enforce mapping expiry for resident accesses too. This permits only the declared
bounded stop window; page faults supply no immediate per-load broker check and
revocation cannot erase copied data. The exact stop mechanism must be qualified
before this contract is exposed. Final grant/ABI encoding remains under review.

Resolve every page from the same retained view or immutable generation. Expiry
or backing failure never refreshes to latest state mid-execution. Authenticate
bytes before installation using protected immutable backing or bounded verified
chunks rooted in admitted metadata binding image, offset, length and contents.
A content hash is not permission; an open read-only fd alone does not freeze a file.

### Owned fault service

The mapping, descriptor object, view, queues, buffers, verification work, I/O and
blocked accessors retain original physical owners. Bound fault-service capacity
independently of blocked guest workers and their locks/allocators. A finite
userspace queue alone does not bound all kernel waiters or guarantee progress.

Negotiate the actual kernel/memory-type features and per-range operations under
the selected confinement policy before admission. A nonblocking descriptor does
not make a blocked instruction async. Engine memory ownership, growth, guards and
reset remain enforced; the on-demand custom-memory hook is not a pooled-instance
pager interface.

Preserve original mapping identity through the actual resolution ioctl, synchronized
with layout change and reuse. An A-generation check followed by a later copy into
reused address B is insufficient. Do not replace the original descriptor owner
with the current meaning of a reused fd number. Validate partial operations and
duplicate faults under bounded bookkeeping.

### Failure and retirement

An unavailable, corrupt, expired or denied page produces the declared activation
failure; it cannot become invented zeros or an indefinite hidden wait. Qualify
guest, host-copy and kernel-originated access separately. Signals, poisoning,
epoch increments and a supervisor timeout are not sufficient recovery evidence.

Before reuse, prevent further access, stop new jobs, retire/fence original
resolution work and blocked accessors, and unregister/unmap through the reviewed
engine lifecycle. Closing/unregistering alone can change interception rather
than establish termination. Unknown cleanup retains charges and withholds reuse.

## Compatibility and migration

Existing explicit state calls and their typed errors/meters remain the portable
contract. A host-internal optimization must show that copying a whole byte-list
value does not erase its savings. A guest-visible mapping is a separately reviewed
ABI/profile with its own grant lifetime, failure and compiler/runtime qualification.
No current manifest selector acquires that meaning from this RFC.

Read-only materialization is the initial scope. Private mutable overlays, dirty
capture and resident-page eviction require a later extension and transaction
review. A dirty set cannot replace logical read dependencies, namespace conflict
validation or host-owned state/outbox/outcome commitment. Paging supplies no
continuation program counter or complete-Store eviction.

## Resource-allocation impact

Keep logical state budgets and guest-memory grants independent of fault counts
and residency. Charge source cache, destination/private pages, page tables,
view pins, buffers, I/O and peak overlap to bounded owners. Bound observations,
prefetch amplification and shared fault service; no per-service handler/task.
Cache hits retain the declared logical authorization/accounting contract.

## Security and trust-boundary impact

The kernel, engine, handler, range bindings and integrity checker remain trusted.
Guests receive no raw fault-resolution or host range-selection authority. Keep
private state and traces tenant-scoped; initial cross-tenant deduplication is
excluded. Missing kernel/device/permission/seccomp prerequisites reject this
selected profile rather than expanding privilege or weakening host policy.

## Failure semantics

An equivalent ordinary path may be selected before execution with the same
authorized view and guarantees. Mid-execution failure cannot trigger whole-operation
replay, switch to a fresh snapshot or refund live owners. If bounded in-process
unresolved-fault recovery cannot be demonstrated, defer integration or review a
different containment boundary; do not advertise the profile as supported.

## Alternatives

Use current selective records or explicit chunks, eager materialization, ordinary
kernel-managed private file mappings or bounded prefetch. These may deliver the
needed benefit with simpler failures. A pager beneath current APIs is a narrower
alternative to a new guest mapping; demand paging is not inherently preferable.

## Validation plan

Use the [mapping model](../research/userfault-pager/mapping-model.md) and
[failure/benchmark matrix](../research/userfault-pager/evaluation-plan.md). Compare
actual record/chunk reads, kernel mappings, eager loading and demand/prefetch with
matched cache/integrity/capability conditions. Require handler-stall progress,
unresolved-fault failure, host-copy tests, generation/fd-reuse races, view expiry,
corrupt backing, resource exhaustion and healthy unrelated work after teardown.
No kernel preflight, paging experiment or measured benefit accompanies this RFC.

## Open questions

1. Which concrete workload benefits over selective records and kernel mappings?
2. Is a host-internal representation sufficient, or what exact guest ABI and
   finite mapping-grant semantics justify exposing a region?
3. Which supported kernel/memory/engine strategy supplies bounded fault failure,
   expiry and physical retirement inside the shared node?
4. Which immutable format, storage trust/proof scheme and view owner can support
   sparse reads without an unmeasured eager verification pass?
5. What separate transaction/interface decision would be required before writes,
   dirty deltas or resident-page eviction could be promoted?
