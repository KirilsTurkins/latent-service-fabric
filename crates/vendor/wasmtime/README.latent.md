# Pinned value, table and Store allocation admission

This is the complete crates.io Wasmtime 48.0.7 package, licensed under
Apache-2.0 WITH LLVM-exception (see the unmodified LICENSE). The original
archive checksum and all 250 original file identities are recorded in
UPSTREAM.latent.json. `latent-dynamic-memory.patch` applies to that exact
original package; it contains thirty-two changed upstream files and six added
implementation files. Other Wasmtime packages remain at the original locked
registry versions. The standalone development lock selects Tokio 1.51.6 for
RUSTSEC-2026-0386; the immutable upstream inventory retains its original lock
identity. This dependency-only lock correction changes no Wasmtime runtime source.

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
`wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-join-state-call-future-pending-continuation-worker-function-memory-v13`. Runtime engine configuration identity
includes this cohort, so old prepared/AOT identity cannot certify this host.
The immutable v1/7b programme passed 61 controls; v2/de0 passed81,
v3/48a passed85, v4/3e417 passed92, v5/94f passed97, v7/f535 passed114,
and v8/4ed0 passed121. The intervening v6 attempts remain failed (15 and100
controls passed before distinct test compilation failures). This v9 extension
adds five planned closed context reply controls and two exact CLI native-thread
audit projection controls while preserving all121 prior selectors. Historical
products and copied-helper controls do not qualify this new source. Exact native
thread audit recognition and projection leave the default ABI, provider selection
and independent authority/grants unchanged.

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

Retained Phase3/Phase4 activation context strings and maps now reserve the
a conservative envelope derived from the existing string/map bounds in the original memory ledger before their
selected transformation. The affine guard is attached before confirmation and
remains the last field until the actual context fields are destroyed. Empty
maps release any hidden upstream B-tree root; surplus buffers are compacted
under the existing finite policy. Publication clones remain conservatively
covered while that context is alive. Phase1 is unchanged. Incoming surplus,
discarded request scaffolding and other typed-hostcall copies remain excluded.

Selected concurrent typed and dynamic host calls now preadmit the exact
concrete callback Future Box Layout before allocation and trait-object erasure.
The Box and affine original owner travel together through sync-lowered blocking
and async-lowered queues. The actual Box is destroyed before its owner; both
fields are installed before confirmation so confirmation unwind is also safe.
Zero-sized futures and unaccounted legacy embeddings remain lazy. This pays
only that engine-created per-invocation Box, not captured/transitive values,
the callback-provided opaque Box, dynamic accessor Box, or scheduler wrappers.

The optional typed HostOutput<R> reply path retains R as its first private
field and its affine original allocation owner last. Actual typed lowering
borrows R, so original String/Vec/record backing stays owned through guest
realloc, cancellation, error and queue cleanup until actual R destruction.
Only the six closed LSF context reply builders use the new path: their original
capability and logical-size preflights run before a checked payload-scaled
reservation and before any reply clones. Selected pairs allocate exactly their
finite filtered count; empty heap replies remain lazy. The two scalar context
operations and Phase1 retain their original behavior. The public optional API
requires caller proof for custom Lower implementations, shared/interior data,
and any newly copied backing owned by an escaping error; it does not establish
a generic transitive value guarantee. Callback-provided opaque boxes, blocking
or scheduler frames and typed input escape remain outside this slice.

This extension does not pay direct Core HostFunc state/context constructors,
shared preparation closure/import backing, concurrent task/queue/resource and hostcall frames,
request ingress/discarded scaffolding, other hostcall copies, or controller/legacy transport allocations.
Existing finite caps are not original memory admission. Whole SDK cost acceptance
remains open; the source package and planned controls are not execution evidence.


The v10 source extension pre-admits the complete allocation of a selected
canonical-async JoinState cell before publishing either of its two private
strong owners. This includes the Arc header, payload and alignment from the
pinned Rust 1.97.1 source (compiler commit 8bab26f4f, alloc/src/sync.rs SHA256
768776d4a37cfeb28c71a0c6d8b2ad33332d11ceaef7e47cb01463bd71b9048a).
Every strong wrapper uses Arc::into_inner: the last winner receives the payload
only after its implicit weak header is deallocated. It destroys state and wakers
before refunding the original allocation owner. A state-destructor unwind keeps
the charge conservatively retained. The cell does not retain its NativeMemory
factory; a real owned binding lifetime control covers that separation.

NativeMemory=None retains the original Arc<TryMutex<JoinState>> allocation and
operation semantics. The private handle enum can enlarge inline handles/futures;
existing concrete future-box admission charges their actual Layout. This is a
source-only implementation until its five private implementation controls and
separate actual canonical first_poll/original-budget control execute. It does
not account all concurrent scheduler, opaque host future, engine GC or cache
allocations, and does not complete a full JavaScript cost-model qualification.


The v11 source extension additionally pre-admits the exact concrete abortable
future Box in Instance::first_poll, after the separately paid JoinState cell but
before the running handle is published or the future is polled. Its private
wrapper keeps the original allocation owner outside the pinned Box; normal
completion retains backing until actual Box destruction. A destructor unwind
keeps that same original charge conservatively retained. Confirmation unwind
also destroys the installed Box before refund. No factory or new ledger is held.
NativeMemory=None preserves the original Box<F> allocation and poll semantics;
the inline wrapper can enlarge the separate enclosing scheduler future.
Layout<F> covers this backing, not allocator overhead or an RSS upper bound.
Other scheduler/opaque future boxes, FuturesUnordered nodes, queue/waitable
backing and transitive captures remain outside this slice. At that historical
source stage the four private controls and actual third-admission/refusal/fresh-
Store control were prepared but unexecuted. They subsequently all passed at
source e225fc670b97f4511c2acac21cfd3b7b8f47d9af, run 40245918267. That v11
qualification covers only those four private cases and request-3/fresh-42 native
control; it does not qualify this v12 continuation extension or the full runtime.


The v12 source extension prepares the selected pending continuation before the
initial host poll or CalleeRunning publication. A private noncapturing factory
and its typed (inner future, lower, StoreToken, task) tuple determine the exact
factory-output Future Layout without invoking the factory. Ready releases the
unused unconfirmed reservation before direct lowering. Pending creates one Box
of that SAME output type with the SAME owner, outside its erased pinned pointer.
Completion keeps the charge until actual destruction/deallocation; confirmation
unwind destroys the installed Box before refund, while destructor unwind retains
the original charge conservatively. There is no new admission after user I/O.
Other existing scheduler boxed paths retain their infallible Legacy adapter;
NativeMemory=None retains the original allocation/poll semantics. The scheduler
enum can enlarge separate queue/node backing, which this slice does not pay.
Layout<Output> is payload backing, not allocator overhead or an RSS upper bound.
The v11 inner CallFuture source is unchanged. Completion WorkerFunction boxes,
FuturesUnordered nodes, queue backing and other transitive/opaque allocations
remain separate gaps at that historical source stage. The four private controls
and actual fourth-admission/refusal/fresh-Store control subsequently passed at
source 5d72ee7886bfd4ed737d02d49e7f85a60c00f0cd, run 40252236378. That v12
receipt is limited to those five controls and does not qualify later extensions.
The v11 cases and Java twelve were not replayed by that v12 programme.


The v13 source extension pre-admits the exact completion WorkerFunction closure
Box using a noncapturing typed-context/result factory. Creating the prepared
holder does not allocate or reserve. The enclosing pending-output reservation
remains admission four; admission five then reserves Layout<Function> through
the prepared tuple before Running publication or the first poll. Ready refunds
both unused reservations before direct lowering. Pending transfers the SAME
worker reservation into one erased closure Box without post-I/O admission.
Its outside affine owner travels through the queue and one-shot invocation.
Normal return/error and unrun queue drop destroy/deallocate the Box before
refund; confirmation unwind has installed cleanup, while call/destructor unwind
conservatively retains the SAME original charge. None keeps the legacy Box call.
Pinned Rust 1.97.1 boxed.rs (8bab26f4f, SHA256
31fe2ec856527253e2a78279f44b7dec14b73d9f1114a75584b031dcd6f64418)
binds its consuming FnOnce call and target/deallocation behavior. This charges
only closure payload backing, not allocator/RSS, transitive captures, escaping
error backing, queue storage or FuturesUnordered nodes. The v11 inner and v12
pending helper source files remain unchanged, although the exact concrete
pending output now includes the prepared worker holder. Four NEW private
controls and actual fifth-admission/refusal/fresh-Store control are prepared,
UNCOMPILED and UNEXECUTED here; only those five are selected by the focused owner.
