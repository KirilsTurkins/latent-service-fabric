# Userfault-pager evaluation and promotion gates

This specifies future experiments. No kernel preflight, native pager, Wasmtime
integration, write tracker or performance campaign was run for this review.
Use the [source review](upstream-review.md) and [mapping model](mapping-model.md),
with the research policy and a later promotion ADR.

## Bounded progression

1. Select one Linux kernel/build, architecture, host page/memory type, creation
   path and confinement policy. In a disposable supervised harness, probe the
   exact API/features, per-range operations and failure behavior. Do not infer
   support from headers, rootless operation or a successful descriptor creation.
2. Read one bounded immutable application image using a deterministic sparse
   workload. Compare selective records/chunks, eager loading, ordinary file
   mapping and userfault missing-page loading. Add bounded prefetch separately.
   No mutable heap or cross-tenant sharing is part of this first scope.
3. Demonstrate handler failure, unresolved-fault cancellation, concurrent progress
   and safe mapping retirement before embedding in LSF. Prove the selected
   engine/allocation strategy and host-copy behavior; a standalone harness does
   not qualify the shared runtime or six guest SDKs.
4. Add private overlays and synchronous write tracking, then an independent
   async-tracking cohort if supported. Preserve consistent views and host commit
   ownership. Resident eviction/refault and additional memory types are separately
   qualified extensions, not assumptions of the read-only result.

Use local nonsecret fixtures, bounded pages/jobs/output and explicit error/fault
injection. An outer timeout and process reap limit a broken experiment; they do
not count as activation-only recovery or positive cell cleanup. No package/OS
installation, privilege expansion, host-policy change or large load run is
authorized implicitly by this plan.

## Correctness and ownership matrix

Every row needs positive controls, deliberate failures and source-bound
observations of data, actual worker/mapping lifetime and resource owners. Passing
the successful read path or observing a watchdog is insufficient.

| Boundary | Required evidence |
| --- | --- |
| Preflight | Missing API/device, denied syscall/seccomp/LSM policy, unsupported registration/features/ioctls and incompatible memory type return the declared unsupported/failure result before execution. No broad-policy fallback. |
| Image bounds | Zero/sparse/tail pages, invalid offsets/lengths, overflow, wrong page alignment and neighboring unauthorized records cannot expose another image or broaden a grant. |
| Integrity and immutability | Missing/corrupt/truncated backing, wrong generation/hash/proof and another writer modifying a held file fail safely. No unverified page install or implicit zero substitution. |
| Consistent view | Concurrent commits between faults, expired snapshots and replaced images cannot produce mixed generations or silently refresh the original view. |
| Authority and meters | Cached/resident accesses, prefetched pages and repeated writes preserve the declared logical grant lifetime and read/write limits. Revocation, required audit failure and budget exhaustion follow the selected profile's contract. |
| Worker progress | Stall every admitted faulting lane while unrelated work and the handler need service. Observe bounded independent capacity, lock/buffer dependencies and overload behavior; a pending Rust timeout is not proof that the fault stopped. |
| Failure delivery | Handler crash, storage failure, poison/signals and unavailable pages produce the declared isolated result. Exercise guest instructions, host copies and kernel-originated access separately; do not assume all faults are Wasm traps. |
| Fault resolution | Concurrent duplicate faults, short/partial ioctls, interrupted event reads, bounded queue/metadata exhaustion and late completions settle the original owner exactly once. |
| Reuse race | Delay A's page response after generation validation, race unregister/unmap/reset and reuse the address/fd number for B. The old job cannot resolve B's page; prove the synchronization through the actual ioctl. |
| Layout lifecycle | Exercise or prohibit growth/relocation, remove/remap/unmap/fork events and engine decommit/reset. Last-fd close must not let failed work continue under unintended normal mapping behavior. |
| Tracking coverage | First write to a missing page, anonymous holes, write-before-protect races, huge-page granularity, repeated writes and discard/refault cannot lose private changes. |
| Tracking epochs | Fill pagemap scan output, follow `walk_end` to completion, race scan/reprotect/reset and write during capture. Final bytes must form the declared coherent snapshot, not just a plausible bitmap. |
| Transactions | A reads X and writes Y while another operation changes X. Disjoint dirty sets cannot bypass namespace validation; abort/error discards overlays, and uncertain commit retains original recovery identity. |
| Physical limits | Exhaust resident/private/staging pages, source cache, view pins, fault slots and I/O. Account for source-plus-destination overlap and actual cleanup; no false refunds or hidden per-service handler. |
| Fallback and retention | A pre-execution alternative preserves the original view/authority. Mid-execution failure cannot replay effects; backing/deltas stay retained until mappings and durable references actually retire. |

Existing state-view, transaction, async ownership and fresh-Store tests are useful
foundations, not proof of a future fault-driven path. Require an unrelated healthy
activation after teardown and repeated cross-activation address reuse, with
observable cells, native buffers, views and provider owners.

## Benchmark cohorts and workloads

Compare current bounded record access and explicit chunk reads with eager image
materialization, kernel-managed private file mapping, userfault demand loading and
demand plus prefetch. Keep data, consistency, integrity, capabilities, memory
limits and host commit rules equivalent; label any different API or safety claim.
Do not compare a warm pager with a cold eager baseline alone.

Vary image size, accessed fraction, locality, access order and recurring versus
changing working sets. Include small key-value operations, sparse records, full
scans, large byte-list returns and update-heavy images. The byte-list case checks
whether canonical copying faults in the entire source and erases the proposed gain.
Test first trace collection, warm traces and stale traces after code/image changes.
Prefetch must retain current authorization and finite I/O/byte amplification.

Separate raw artifact/prepared-code state, state-view/image availability, kernel
page-cache state, source buffers and destination residency. Include ordinary
kernel readahead. Define and observe the cache preparation method in the isolated
harness; never claim cold I/O because one userspace cache was empty. Do not clear
global host caches as an implicit benchmark setup.

Measure creation/register/preflight, fault queue delay, backing read, verification,
copy/install/wakeup, tracking, delta encoding, commit and complete retirement.
Report end-to-end latency distributions, request counts, warmups/repetitions and
uncertainty rather than summing phase p99s. Track CPU, blocked execution-worker time,
fault/duplicate counts, fetched/useful/prefetched bytes and dirty versus actually
changed pages. Include no-fault overhead and unrelated-tenant tail latency.

Report virtual reservations, logical guest memory, resident destination pages,
private dirty overlays, backing page cache, handler buffers, page tables and peak
load/capture overlap separately. A cached source plus anonymous destination can
retain two representations. Fewer loaded pages do not prove lower steady-state
RSS or permit a larger logical grant.

Record kernel commit/build/config, architecture/page sizes, memory backing,
negotiated features/per-range operations, creation permissions and container/LSM
policy. Pin engine/allocator/compiler/artifact, data format/image, storage/cache,
integrity method and all resource caps. Keep correctness runs separate from
larger concurrency/profiling/soak campaigns requiring separate scope.

## Promotion decision

Require an ADR defining the benefit over actual selective reads and kernel
mapping; supported host/memory types; immutable format and authority lifetime;
fault failure/cancellation; worker progress; engine ownership; physical/logical
accounting; layout/reuse fences; and exact commit/recovery integration for writes.
Publish negative results and retained evidence. If safe bounded unresolved-fault
recovery is unavailable, defer in-process integration rather than weakening the
existing activation contract.

Keep host-internal paging, guest-visible mappings, write tracking and resident
eviction as separately evidenced claims. Retain explicit capability calls as the
portable contract. Paging does not implement continuation capture, release a
waiting Store or establish durable workflow recovery.
