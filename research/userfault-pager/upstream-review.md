# Userfault pager: kernel, engine and research evidence

Reviewed on 2026-10-15. Sources were inspected, not built or executed. Kernel
development headers and published examples are not a qualified LSF kernel,
container policy or memory allocator.

## Pinned source snapshots

| Source | Reviewed scope |
| --- | --- |
| [Linux `0fcb05b72344f40806cbe810de8872f1698bf053`](https://github.com/torvalds/linux/tree/0fcb05b72344f40806cbe810de8872f1698bf053) | [Userfault documentation](https://github.com/torvalds/linux/blob/0fcb05b72344f40806cbe810de8872f1698bf053/Documentation/admin-guide/mm/userfaultfd.rst), [pagemap documentation](https://github.com/torvalds/linux/blob/0fcb05b72344f40806cbe810de8872f1698bf053/Documentation/admin-guide/mm/pagemap.rst) and [UAPI header](https://github.com/torvalds/linux/blob/0fcb05b72344f40806cbe810de8872f1698bf053/include/uapi/linux/userfaultfd.h), snapshot dated 2026-10-14. Development-source feature presence does not establish support in a deployed kernel. |
| [Firecracker `8ea68a2bedee0e1f5d5af537e4e78b200d88ce64`](https://github.com/firecracker-microvm/firecracker/tree/8ea68a2bedee0e1f5d5af537e4e78b200d88ce64) | [Snapshot alternatives](https://github.com/firecracker-microvm/firecracker/blob/8ea68a2bedee0e1f5d5af537e4e78b200d88ce64/docs/snapshotting/snapshot-support.md) and [userspace fault-handler design/caveats](https://github.com/firecracker-microvm/firecracker/blob/8ea68a2bedee0e1f5d5af537e4e78b200d88ce64/docs/snapshotting/handling-page-faults-on-snapshot-resume.md), snapshot dated 2026-10-15. These restore VM snapshots, not LSF state transactions. |
| [Wasmtime 48.0.6, `72bc45bd197c46718df0c02b8d4cbc1cb610ab2d`](https://github.com/bytecodealliance/wasmtime/tree/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d) | [Configuration](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/src/config.rs) and [custom-memory contract](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/src/runtime/memory.rs). The selected engine's interfaces matter more than rolling development API pages. |

## Fault modes and tracking limits

| Mechanism | Evidence and qualification |
| --- | --- |
| Missing-page handling | [`userfaultfd(2)`](https://man7.org/linux/man-pages/man2/userfaultfd.2.html) stops the faulting thread pending resolution. [`UFFDIO_COPY`](https://man7.org/linux/man-pages/man2/UFFDIO_COPY.2const.html) installs bytes; its WP mode can install them protected when missing and WP registration are both enabled. Check returned byte counts and errors, including partial operations. |
| Synchronous write protection | [`UFFDIO_WRITEPROTECT`](https://man7.org/linux/man-pages/man2/UFFDIO_WRITEPROTECT.2const.html) lets a handler record a write before releasing it. This observes writes, not application commit or a complete read set. |
| Minor faults | The [Linux UAPI](https://github.com/torvalds/linux/blob/0fcb05b72344f40806cbe810de8872f1698bf053/include/uapi/linux/userfaultfd.h) distinguishes installation of an existing backing page with `UFFDIO_CONTINUE`. Missing/minor/WP combinations and memory types require separate negotiation. |
| Async write tracking | The [kernel guide](https://docs.kernel.org/admin-guide/mm/userfaultfd.html) describes `UFFD_FEATURE_WP_ASYNC`: writes clear protection without per-write userfault messages. It does not turn a missing-page load into an async guest call. Anonymous unpopulated PTE handling needs its own supported feature or preparation. |
| Written-page scans | [Pagemap scan](https://docs.kernel.org/admin-guide/mm/pagemap.html) can combine written-page reporting and reprotection. `walk_end` may stop before the requested end when bounded output fills. Huge-page tracking may report extra dirty pages. This is not a global snapshot of concurrently changing application bytes. |
| Read/write access tracking | The pinned Linux guide/header also describe `RWP` modes for resident-page access/working-set tracking. These are outside the initial missing/WP scope; older userfault support does not establish their availability. They do not define logical state-read or transaction semantics. |

For async tracking, define epochs and scan/reprotect completion explicitly.
Discarding memory can itself affect tracked dirty state; kernel guidance describes
`MADV_DONTNEED`/`MADV_REMOVE` behavior. Do not equate a bitmap with successful
business writes, or stop scanning after the first bounded result buffer.
[Kernel tracking semantics](https://docs.kernel.org/admin-guide/mm/userfaultfd.html),
[scan interface](https://docs.kernel.org/admin-guide/mm/pagemap.html).

[`UFFDIO_POISON`](https://man7.org/linux/man-pages/man2/UFFDIO_POISON.2const.html)
causes later accesses to raise `SIGBUS`. It is a failure mechanism, not evidence
that Wasmtime can recover that signal as an isolated guest error, particularly
during host code access. The manual also documents partial updates and concurrent
layout-change errors; handlers must retain ownership through resolution.

## Deployment and engine constraints

The [kernel creation interface](https://docs.kernel.org/admin-guide/mm/userfaultfd.html)
separates userspace-only syscall creation, broader syscall policy/privileges and
permission-controlled `/dev/userfaultfd` creation. Negotiate required features
with `UFFDIO_API` and inspect the operations returned for each registered range;
a header or kernel version string alone is insufficient.

[`UFFD_USER_MODE_ONLY`](https://man7.org/linux/man-pages/man2/userfaultfd.2.html)
includes host userspace, not just guest code; kernel-originated faults on its
registered ranges produce `SIGBUS`. Closing the final descriptor unregisters
ranges and flushes unread events. Neither fact supplies LSF cancellation or a
safe reuse proof. [Docker's default seccomp documentation](https://docs.docker.com/engine/security/seccomp/)
lists `userfaultfd` among blocked syscalls. Device access, container/LSM policy,
syscall permission and exact feature behavior need independent preflight.

Wasmtime's pinned `with_host_memory` contract applies to host memories and
on-demand instance allocation, not a drop-in replacement for pooled instance
linear memory. `MemoryCreator`/`LinearMemory` are unsafe contracts with ownership,
alignment, reservation, guard and growth requirements. Custom external mutation
is not permitted merely because a raw base address exists. Its selected
copy-on-write initialization concerns immutable module data, not persistent
mutable application state.
[Pinned configuration and interruption limits](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/src/config.rs),
[memory safety contract](https://github.com/bytecodealliance/wasmtime/blob/72bc45bd197c46718df0c02b8d4cbc1cb610ab2d/crates/wasmtime/src/runtime/memory.rs).

The same engine documentation limits fuel/epochs to running Wasm rather than
blocked host work. **LSF inference:** a blocked faulting instruction cannot reach
the next interruption check. Qualify unresolved-fault recovery, host-copy faults,
growth/reset and actual allocation strategy before embedding a pager.

## Systems research and useful baselines

| Primary source | Contribution and limit for LSF |
| --- | --- |
| [Firecracker snapshot loading](https://github.com/firecracker-microvm/firecracker/blob/8ea68a2bedee0e1f5d5af537e4e78b200d88ce64/docs/snapshotting/handling-page-faults-on-snapshot-resume.md) | Separates kernel-managed loading from an external userspace handler receiving descriptor/layout information. It explicitly warns that handler failure can leave a fault hung indefinitely. The linked example fills an entire region on a fault; it must not be labeled a one-page demand policy without inspection. VM recycling is not activation-only recovery inside LSF's shared node. |
| [REAP, ASPLOS 2021](https://arxiv.org/pdf/2101.09355) | Records recurring snapshot working sets and prefetches them, with on-demand fallback. The paper reports average 3.7x cold-start improvement over its evaluated Firecracker snapshot baseline. Recording costs and monitor resources matter; neither the speedup nor a per-function monitor design transfers to LSF. |
| [Faasm, USENIX ATC 2020](https://www.usenix.org/system/files/atc20-shillaker.pdf) | Structured shared state and smaller independently replicated chunks illustrate partial materialization and explicit consistency/synchronization choices. This is a data-layout comparison, not proof of a userfault pager or LSF serializability. |
| [SnapShare v1, 9 October 2026](https://arxiv.org/html/2610.13318v1) | Preprint separates approved shared infrastructure from private snapshot content. Its implementation describes equal MD5 digests as the page-content match criterion; that is not a cryptographic admission or privacy proof for LSF. Keep private state tenant-scoped and exclude cross-tenant deduplication from the initial experiment. |

These sources motivate comparison with kernel mapping, explicit chunks and
bounded prefetch before custom fault handling. Access traces, cache sharing,
backing lifetimes and handler costs belong to the design. Published snapshot
results establish neither LSF performance nor unchanged six-SDK compatibility.
