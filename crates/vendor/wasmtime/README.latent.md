# Pinned value, table and Store allocation admission

This is the complete crates.io Wasmtime 48.0.7 package, licensed under
Apache-2.0 WITH LLVM-exception (see the unmodified LICENSE). The original
archive checksum and all 250 original file identities are recorded in
UPSTREAM.latent.json. `latent-dynamic-memory.patch` applies to that exact
original package; it contains seventeen changed upstream files and three added
implementation files. Other Wasmtime packages remain at the original locked
registry versions.

The maintained extension is `component::DynamicValueMemory` and
`Func::call_async_with_memory`. It admits actual allocation capacity in the
selected ordinary dynamic-value surface before allocating. It does not replace
the global allocator. Existing dynamic entry points do not install this hook.
Unsupported resource/map/fixed-list/future/stream/error-context values are not
admitted by the extension. Existing canonical pointer/alignment/encoding checks
and hostcall fuel remain active; a string sizing prepass does not consume fuel
again.

Original allocation scopes follow actual values. The concurrent parameter copy
has a separate refundable scope; its Vec is destroyed before its scope. Queued
results retain their shared original scope through Store-owned work and caller
abandonment. After result values move into the caller's already prepaid slots,
the physically retired temporary Vec and Any-result Box are refunded. The
caller must retain its shared scope until its actual output values die.

Exact-capacity Vec construction uses the pinned Rust Global/RawVec allocator
layout, checks exposed capacity, and includes 64 bytes of finite allocation
bookkeeping. String destinations are allocated once after bounded UTF-8 byte
counting; UTF-16 and Latin-1 do not create an intermediate decoded String.
Flags growth admits replacement and original buffers simultaneously, then
refunds the old buffer only after physical destruction. Partial lift failure
retains confirmed actual allocations through native unwind, without confirming
a hypothetical signature maximum as observed peak.

The native cohort is
`wasmtime-48.0.7-latent-value-table-store-memory-v2`. Runtime engine configuration identity
includes this cohort, so old prepared/AOT identity cannot certify this host.
The earlier v1/7b native programme passed its original 61 controls and retains
its immutable source and receipts. The v2 table/Store extension and its nineteen planned
native controls have not yet received native qualification.

The optional `ResourceLimiter::table_allocating` hook returns an owned original
allocation guard. Actual table backing destroys before its guard; dropping Store
user data does not refund a still-live table. Accounted dynamic growth admits the
exact checked replacement Layout while retaining the old buffer and owner, moves
Option cells without cloning, then destroys old backing before refund. Explicit
None initialization avoids assuming a zero representation for continuation refs.
Ordinary embeddings without the hook keep the original unaccounted growth path.

Pooling reserves the complete page-aligned slot before committing its pages and
retains the guard in the real Table through its existing reset/decommit queue.
Engine-wide pool creation remains node-owned. Original finite element/count and
pool limits remain; a table callback confirms preceding completed linear growth
before native backing competes for the same activation ledger. This table slice
does not claim all Store metadata, controller/transport frames or legacy Phase0
memory is charged, and the source package is not execution evidence.


The optional NativeMemory factory is selected before Store construction. LSF
Phase3/4 transfers a paid NativeMemoryBinding: its only Arc is created from an
owned factory value after admission; no strong/Weak handle is exposed. The
finite Arc Layout follows pinned Rust1.97.1 alloc/src/sync.rs ArcInner
(repr(C,align(2)), two AtomicUsize counters, T, checked extend/pad_to_align).
The factory binding is destroyed after all private Store/container clones and
after actual inner Box destruction, and refunds only after its Arc backing is
freed. Generic externally supplied factory Arcs remain caller-owned.

StoreInner's exact Box Layout is reserved before allocation. Constructor failure
keeps T ordinarily owned until the Box is initialized, then a complete Store
wrapper handles dummy-instance refusal and exactly-once data destruction.
The Box guard and binding live outside that Box, including into_data. Context
references still point to the stable StoreInner address. Destruction uncertainty
retains admission conservatively rather than refunding leaked backing.

Both Core and Component raw instance/VMContext Layouts hold their affine owner
in the actual trailing OwnedVMContext header; the pointer-sized OwnedInstance
handle is unchanged. The owner is extracted before actual instance destruction,
then released after exact raw deallocation. Context inverse pointers use the
complete instance size, with a real-constructor debug roundtrip assertion.

Private NativeMap/NativeVec wrappers preadmit exact checked capacities for the
Store/Core/Component instance-owner vectors, Core memory/table descriptors,
Component state/runtime-instance maps and passive segment arrays. Actual old/new
replacement overlap is admitted; source-owning iterators retain original guards
until buffers die. Entry/slice mutation cannot expose an allocating container.
Original unaccounted embedding paths retain the existing fallible containers.

This extension does not pay the remaining per-Store module-registry trees,
FuncRefs bump/vector backing, concurrent task/queue/resource and hostcall frames,
request-context transitive buffers, or controller/legacy transport allocations.
Existing finite caps are not original memory admission. Whole SDK cost acceptance
remains open; the source package and planned controls are not execution evidence.
