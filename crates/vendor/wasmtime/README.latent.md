# Pinned value, table and Store allocation admission

This is the complete crates.io Wasmtime 48.0.7 package, licensed under
Apache-2.0 WITH LLVM-exception (see the unmodified LICENSE). The original
archive checksum and all 250 original file identities are recorded in
UPSTREAM.latent.json. `latent-dynamic-memory.patch` applies to that exact
original package; it contains twenty-eight changed upstream files and six added
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
`wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-memory-v6`. Runtime engine configuration identity
includes this cohort, so old prepared/AOT identity cannot certify this host.
The immutable v1/7b programme passed 61 controls; v2/de0 passed81,
v3/48a passed85, v4/3e417 passed92 and v5/94f passed97. This v6 linear-memory
notification extension adds three planned controls, preserving all97 prior
selectors. The same native programme also adds three exact native-thread audit
codec controls; this descriptive codec recognition leaves the default host ABI,
provider selection, independent authority and grants unchanged. Neither an
earlier binary nor copied-helper tests qualify this new source.

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

Accounted Store registries use sorted, paid vectors for all three ordered
indices and the secondary module-index array. Empty registries stay lazy;
geometric spare capacity and old/new overlap stay charged. Every replacement
is staged before publishing any registry edge; later refusal preserves all
prior keys and owners. Duplicate modules reuse registry backing, sparse indices
retain None holes, and foreign-Engine rejection precedes all admission. The
legacy embedding retains the upstream B-tree and fallible registration path.

Selected Store FuncRefs admit an exact stable VMFuncRef Box and geometric
arena, hole and root directory backing before allocation. All replacements and
stable boxes are staged before a root/hole is published; refused candidates
leave prior pointers and roots intact. Physical buffers and boxes die before
refund; removing a filled hole keeps retained directory capacity charged.
Shared InstancePre definitions and prepatched references enter as an atomic
pair of paid root slots. Legacy embeddings keep the original bump arena.
Fallible Core function/Linker insertion preserves original typed admission
errors, including defined default-function lookup without fallback masking.

Selected per-instance resource substitutions preadmit the exact finite total
of imported and defined resource slots. The fixed-capacity map detaches its
native factory before its shared handle can escape the Store through type or
InstancePre metadata. Its affine backing owner still follows every actual
resource allocation. Private strong handles expose no Arc or Weak escape, and
every clone destroys through pinned Arc::into_inner. This frees the shared Arc
allocation before dropping the resource payload and its original owners, even
for concurrent last drops. The Arc layout is reserved before allocation;
confirmation unwind follows the installed shared-handle cleanup path. Legacy
preparation/embedding maps keep the original fallible Arc/map behavior.

Successful initial dynamic/static linear-memory allocation and subsequent
successful growth now notify the limiter at the actual allocator boundary,
before later instance initialization can allocate competing native buffers.
Failed initial admission/allocation discards only pending unallocated memory
and preserves the original error; failed growth keeps the prior confirmed peak.
Sync and async limiter callbacks default to no-op for other embeddings. These
notifications establish the original ledger high-water mark when the actual
accessible pages coexist with setup storage, rather than waiting for a later
table callback or terminal accounting. The original tight-budget invocation
regression and its caps remain unchanged.

This extension does not pay direct Core HostFunc state/context constructors,
shared preparation closure/import backing, concurrent task/queue/resource and hostcall frames,
request-context transitive buffers, or controller/legacy transport allocations.
Existing finite caps are not original memory admission. Whole SDK cost acceptance
remains open; the source package and planned controls are not execution evidence.
