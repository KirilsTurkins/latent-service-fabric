# Existing provider boundary and new ACPI execution costs

This is a source decision note for the unselected constructor prototype. It
corrects an overly broad inference in earlier source plans; it changes no
historical receipt, acceptance criterion, configuration, allocation limit or
consumer selection. No kernel build, boot, actual queue execution, native
bootstrap or final-free qualification is claimed.

## Contract scope

The accepted ADR-0061, section Authority and ownership, requires the sealed
broker, original activation/descendant budget, IoRuntime/IoCall/IoTransfer and
existing cleanup/quarantine owners. Its implementation gates require actual
kernel/native measurements. It does not require an activation or its provider
bank to adopt the operating system that already hosts it.

The exact #738 fourth criterion requires reservation of handle records, queues,
buffers, native/TLS/kernel-related costs and maximum live transfer capacity
before allocation/dispatch, using the existing ledger. The #739 startup
criterion requires shared host infrastructure to stay bounded. ADR-0028 states
the resource invariant explicitly:

```
resident resources = fixed node runtime + active activations + bounded shared caches and provider pools
```

The current outbound profile also says to reuse the original shared bounded
provider admission queue, with no new queue/executor. A kernel cleanup worker
is an internal physical implementation obligation, not permission to add a
second application executor or duplicate provider admission ledger.

Earlier agent-authored kernel notes describe original kthreadd, IRQ/RCU/TLB and
per-CPU objects as requiring original NodeFixed/bootstrap funding. Those words
must not be read as a new requirement to move all Linux boot allocations into
the selected provider's one-MiB reservation. The accepted design has a named
existing OS/provider boundary. Existing objects remain original references;
they are neither paid for retrospectively nor adopted/refunded by our Root.
Their configured capacity, availability and lifetime remain supported-platform
prerequisites. Any NEW allocation our implementation requires still needs a
real owner and finite physical bound.

## Existing authoritative APIs and their actual extent

* `ProviderPools::reserve_stream_kernel_backing`, in
  `crates/latent-capabilities/src/broker/pools/protocol.rs`, acquires exactly
  one MiB through existing `reserve_protocol_metadata` and retains the original
  pool. `limits.rs` implements that actual `Kind::Metadata` quota and `Charge`.
  No size is supplied by a guest. This is userspace provider admission, not a
  Linux boot allocator or an already executed protected factory installation.
* `StreamKernelOwnership` retains the original host memory reservation, stream
  scope, accepted request and IoLease. Its `confirm` records actual allocation;
  its checkpoint cannot create another owner or change the charge. This is an
  operation owner, not a constructor for an arbitrary existing OS object.
* `lsf_prepaid_initialize` in `prepaid.h` owns record zero for the original
  512-KiB backing and the same 256-record/64-owner storage. `device-prepaid.h`
  creates the private shared domain in slot 63 only after that backing exists;
  its views use the original 192-KiB tail. This is the actual selected private
  allocation mechanism, not another independent registrar.
* The actual `lsf_factory_open` allocates backing and obtains its opening
  mm/TGID/credential/network references. The selected consumer still returns
  NULL. Neither this path nor the Rust reservation has a kernel-boot attachment
  API. That absence matters for a proposed *new* boot allocator, but no such
  allocator is needed merely to reference existing kthreadd or the ACPI queue.
* `NativeCapacityOwner`/`NativeReservation` under
  `crates/latent-core/src/native_capacity` are bounded original native service
  request/work/response owners. They are not Linux NodeFixed boot accounts.
  `ResourceOwnership::NodeFixed` in node inventory is a classification, not
  an allocation/admission API. The node-worker-stacks profile similarly
  describes configured Tokio worker mappings, not this kernel pool.

No new counter, new ledger, cap increase or conversion from inventory labels
is proposed. Logical views and returning records cannot refund physical pages,
slab/cache carriers, shared OS references or their original provider owners.

## Named existing Linux providers

Authenticated Linux 6.12.113 commit
`7fdb7c1824a1f9979d648d7ae28ac446bcee9c6e` has these real births:

| Existing provider | Actual birth and lifetime boundary |
| --- | --- |
| kthreadd | `init/main.c:rest_init` calls original `kernel_thread(kthreadd, ...)`, before userspace. The private constructor uses its real request list and references; it does not replace kthreadd's Task or stack. |
| system workqueues/pools | `workqueue_init_early` constructs original metadata before `rest_init`; `kernel_init_freeable` invokes `workqueue_init` before initcalls, and later SMP/topology initialization. |
| PWQ retirement executor | `wq_cpu_intensive_thresh_init` creates the original `pool_workqueue_release` kthread worker. It is not the private Root worker and cannot be returned with its Request. |
| ACPI queues | `acpi_os_initialize1` creates `kacpid`, `kacpi_notify`, and the original ordered `kacpi_hotplug` queue; `acpi_os_terminate` destroys those queues. Root close does not terminate ACPI or refund these original objects. |

These facts establish ordering and non-adoption. They do not prove every byte
of the host OS belongs inside the private provider ceiling. For example, the
selected config permits 64 CPUs and gives 16-KiB x86 kernel stacks; two original
normal/high-priority per-CPU worker Tasks per online CPU alone would cost
`32 KiB * online_cpus`. At 64 CPUs that is two MiB before Task metadata. This
conditional calculation illustrates why interpreting the one-MiB private
bootstrap as the entire Linux OS is wrong. It is not an observation of the
running CPU count, an allocation charge, an upper bound or a fit failure of
the correctly scoped provider.

## The actual supported ACPI work route

Current composed `net/factory-device-firmware.c` owns one prepaid firmware
descriptor containing its original `struct work_struct`. After original PCI,
core and registration retirement fences, it marks that same record QUEUED and
calls `lsf_prepaid_acpi_queue_reference_put` outside the pool lock. The adapter
calls original `acpi_queue_hotplug_work`, which calls
`queue_work(kacpi_hotplug_wq, work)`. Its real callback clears only the expected
firmware association, performs the actual `acpi_dev_put`, revalidates original
owner/PCI generations and returns the descriptor before resuming PCI return.
Unknown queue state retains both reference and parent; no retry or synthetic
completion exists.

Keep this original ordered queue. The original `acpi_hotplug_schedule` explains
why hotplug cannot execute on kacpid/kacpi_notify: driver remove may flush those
queues. Replacing our work with a private `kthread_work` would additionally lose
ordering relative to the other hotplug producers. A private-worker handoff that
holds the original ACPI callback until completion would still need the original
ACPI executor and its costs. The current private cleanup worker has no firmware
producer; merely starting/stopping it does not close this real route.

## NEW allocation and retirement inventory

| New activity caused by our implementation | Admission and real physical tail |
| --- | --- |
| Private Request/Task/stack/name/worker and constructor descendants | Same original bank records before writes/publication; runtime Task size plus real VM/page tables, PID/IDR, credentials/LSM, signal, audit, NUMA, I/O and other selected children. Actual destructors, RCU/IRQ and unmap/TLB precede final view return. These are the current prototype's real obligations. |
| Firmware descriptor/work item | Original descriptor birth before initialization and queue publication. No fresh per-submit work allocation. Its actual callback/PCI parent return must finish all our own accesses. Original `process_one_work` explicitly permits callback-side work free: it only traces the address after the callback, then updates its own worker/PWQ state. Do not invent a later descriptor dereference or require adoption of that existing provider state. |
| Extra shared-pool worker | `worker_thread` can run `manage_workers` before processing; `maybe_create_worker` calls `create_worker`, which allocates IDA state, `struct worker`, and a full real kthread. Existing queue-ready or pre-warmed worker observations do not prepay this growth. |
| New/changed unbound provider pool or PWQ, if an isolation implementation needs it | `get_unbound_pool` may borrow an existing matching pool or allocate a new pool/attributes/ID/worker. `alloc_unbound_pwq` allocates a real slab PWQ. The original shared reference must never become a Root-owned allocation by lookup. |
| Pool/PWQ retirement after real last references | `pwq_release_workfn` runs on the original release executor, removes original links, drops pool references and schedules actual RCU frees. Pool retirement stops/puts real workers, synchronizes timers/work and uses `rcu_free_pool`; WQ metadata uses `rcu_free_wq`. Callback return or a private stop is insufficient. |

The exact allocation expressions are available without guessed layout:
`sizeof(struct worker)`, real kthread Task/stack children,
`sizeof(struct worker_pool)`, `sizeof(struct workqueue_attrs)`, actual configured
cpumask representation, `sizeof(struct pool_workqueue)`, and
`struct_size(wq, node_nr_active, nr_node_ids + 1)`. Unbound WQ creation also
allocates one `wq_node_nr_active` per actual node plus fallback, a per-CPU PWQ
pointer extent, and temporary
`struct_size(ctx, pwq_tbl, nr_cpu_ids)`/attributes. Those temporary allocations
and their failure-time PWQ-release work belong in any new isolation bootstrap
peak. A size getter alone is not physical funding or a slab/page bound.

The original ordered queue has one PWQ and max_active one. Its underlying pool
is still selected by shared attribute lookup; `get_unbound_pool` increments a
matching pool reference. Neither max_active one nor WQ_MAX_ACTIVE 512 bounds
all workers in that shared pool. A finite spare-worker count for an actually
exclusive ordered pool must be proved against original manager/idle/cull and
post-callback scheduling before selecting a preallocation number.

## Concrete closure path

1. Keep the named original kthreadd, global ACPI queue, IRQ/RCU and system-worker
   providers outside Root's allocation graph. State their actual supported
   configuration/lifetime boundary rather than inventing retrospective births.
   Continue closing the new private constructor and descriptor physical tails.
2. Before wiring our ACPI producer, establish a real finite executor capacity
   boundary. First check the actual configured shared provider capacity and its
   original owner: an implemented finite bound that includes additional workers
   and deferred costs can satisfy this without moving the queue or exclusively
   owning a pool. Queue-ready/idle-worker observations alone cannot. Where that
   provider bound cannot be established, source-only alternatives are: require
   and pin an actually exclusive existing ordered provider pool, refusing
   selection when sharing, construction or retirement cannot be excluded; or
   implement a dedicated provider pool using original ordered-WQ/PWQ migration
   and plugging semantics while keeping the same ACPI queue and external
   ordering. The latter must prepay every NEW pool/PWQ/worker/temporary
   allocation under the unchanged bootstrap ceiling. These alternatives are
   not implemented or selected by this note.
3. Prove actual exclusive-pool manager/idle/cull geometry, reserve that finite
   capacity before publication, and make any excess-growth path refuse at its
   real allocation boundary. Such refusal must not strand already accepted work
   that requires another worker for progress. Preserve original ordinary callers
   and actual error/unwind semantics; no global no-growth toggle is implied.
4. Close our producer quiescence and last actual callback/PCI accesses, any NEW
   owned PWQ-release/RCU tails, and failed-open native owner retention. Existing
   global worker epilogues are not automatically new Root children; no complete
   global-queue drain is inferred merely from a traced work address. Bind real compiled geometry
   and complete peak against the original one-MiB/512-KiB/192-KiB and slot bounds.
   Only then can consumer wiring, kernel qualification and runtime tests begin.

This removes the inferred whole-OS architecture blocker. It does not remove the
actual incremental allocation/queue or final-free requirements, and it does not
establish that the current full prototype fits or that a usable exclusive
provider pool is already present.
