# Native admission and recovery capacity

The trusted node composition installs one `latent_core::native_capacity::NativeCapacityOwner`
and shares its original counters across transactions, queries, management workers
and response/frame owners. It uses the node's original `ActivationClock` and
absolute deadline. A caller, restored record, diagnostic epoch or finalized
activation ledger cannot mint or refresh capacity. The owner adds no request
timers, threads, engines or background scans.

## Finite admission and actual buffer ownership

`reserve(class, NativeReservationRequest { request_bytes, work_bytes,
response_bytes }, original_deadline)` atomically prepays one finite slot and all
three native-buffer capacities, plus 2048 bytes for bounded reservation/owner
metadata. Overflow, excessive size/lifetime or any exhausted partition rejects
before allocation. The non-clone `NativeReservation` exposes the exact three
capacities separately and `reserved_bytes()` includes their sum and metadata.
The default ordinary partition is 128 slots/256 MiB with 64 MiB per admission;
the separate recovery partition is eight slots/32 MiB with 32 MiB per admission.
The maximum original lifetime is three minutes; explicit finite configuration
can select smaller limits within hard node ceilings.

Reservations can be wrapped in Arc by their original accepted worker and wire
response owners. Dropping a request waiter, freezing the original activation
ledger, reaching the deadline or closing admission does not refund their live
physical capacity. The global slot and all prepaid bytes remain charged until
the final reservation/buffer/frame owner actually drops. A clone of the node
owner shares those same counters; `is_same_owner` compares sealed identity.

`reserve_buffer(Request/Work/Response, bytes)` supplies an affine subreservation
before allocation. Each part cannot borrow another part's capacity, and every
admission has at most sixteen buffer guards, including zero-byte shells. Attach
the actual owned native value with `permit.attach(value)`: its destructor runs
before the quota guard drops. `allocate_bytes` reserves then allocates a bounded
fixed-size byte buffer; its mutable-slice API cannot grow the allocation.
`into_parts` moves the value and its original guard together into existing
worker/frame owners. Trusted native encoders must declare and retain all actual
allocation capacities, including serialization copies, rather than only the
encoded payload length.

`with_live` checks the original monotonic deadline, node close and quarantine
under a short metadata fence. Its callback performs no I/O/await or recursive
capacity acquisition. When composing native acceptance, this fence is outside
the command role, policy, namespace and effect fences. Capacity remains a
resource gate; current caller/namespace/provider authorization is still required.

## Usable engine recovery and shutdown

`close_ordinary` stops ordinary admission while retaining recovery admission.
Full close/quarantine rejects both, preserving any accepted physical owners.
Recovery capacity cannot be loaned to ordinary work. The same protected store's
`RecoveryRead`/`RecoveryWrite` classes have a separately preallocated queue,
accepted-owner/byte partition and reserved fixed worker. Its production job cap
is 8 MiB plus 8 KiB metadata within a 16 MiB aggregate reserve. An 8 MiB work
operation remains accounted honestly; two such operations cannot both fit once
real job metadata is included. Small status/receipt jobs use remaining capacity.
Recovery writes cannot steal a live physical single-writer permit. Store/device
failure remains an explicit finite error, not an unlimited availability promise.

Native capacity has one bounded asynchronous node drain waiter, borrowing the
existing timer future. It wakes from actual last-owner destruction. Its earliest
original cutoff remains sticky across waiter detachment or later drain calls.
Deadline expiry/quarantine never constitutes physical retirement, and late
retirement cannot produce a clean report. Metadata poisoning rejects further
admission and leaves shutdown conservative while real buffers retire.

## Evidence and integration boundary

Pinned Rust 1.97.1 Windows: all 102 core library cases and strict all-target,
all-feature core Clippy passed, including ten native-capacity cases. They exercise separate
ordinary/recovery quotas, actual response allocation, finite buffer shells,
concurrent aliases, original deadlines, finalized activation ledgers, an actual
paused buffer destructor, wait detachment, sticky drain and poisoned acceptance.
Three test-only string/binding changes preserve existing core regression
semantics while allowing the complete strict core check to pass.

The real protected Linux saturation case and application integration checks
remain pending shared Docker filesystem recovery. The node coordinator and
#400 authenticated management adapters consume this port and must retain guards
through actual worker and frame cleanup. This focused resource port does not
complete #397's durable quota accounting, linked retention, compaction, physical
disk pressure or audited terminalization acceptance criteria.
