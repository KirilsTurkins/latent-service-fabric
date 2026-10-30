# Java collection across parked continuations

Prepared source for a finite part of #741. No new component or collection has
been qualified yet. The original [six-case dependency/monitor programme](java-dependency-checkpoints.md)
and its failed histories and successful evidence remain unchanged.

The new fixture uses the same captured Commons Lang 3.14.0 initializer. A child
retains primitive/reference arrays, an object, a caught exception and independent
ThreadLocal state while waiting on an ordinary monitor. Root reacquires that
monitor after the wait releases ownership and requests one collection. A newly
allocated orphan must have disappeared through its WeakReference. Child resumes,
then requests a second collection while root is parked in the unchanged dependency
call. Both callers check retained identities, contents, exceptions and ThreadLocal
state after resumption. An independent activation-local static array strongly
roots only ten weak observers, with its actual generated static-root registration
required. Each collector reads the parked victim through that registry only
after collection. The two ThreadLocal values have no duplicate strong caller
locals; weak observers and `local.get()` check their identities and values. There are no manual weak clears, collection retries,
allocation-pressure loops, custom executors or larger heap grants.

`System.gc()` alone cannot satisfy this programme. Both weak-clear witnesses must
pass, and the standard collector/getter bodies and both continuation bodies are
retained through a separate byte-exact public-fixture selector: twenty-six fixed
C/header/runtime files, including `Capsule@d1` for the anonymous initializer and
the allocator/heap-tracer sources changed by the alignment repair. Limits remain
one MiB per file and eight MiB total. Passive real pinned compiler/classlib controls
check the full collector call chain, actual weak-reference lowering and original/
unrelated negatives; those controls remain separate from runtime evidence.

The JVM-only reference explicitly selects SerialGC with explicit GC enabled,
requires its actual collector identities and at least two observed collections,
and has fixed process deadlines. This selected reference configuration does not
turn the Java specification's best-effort `System.gc()` into a universal guarantee.

The focused owning programme requires four signed calls (GC and fresh state in
each of two tenants), two zero-work grant denials and the maintained per-call
physical idle/provider-zero checks and clean node/zero-contact peer shutdown.
The original producer compiled one unsigned compiler warm-up and one fresh target
component using the existing five native193 products without rebuilding them. The original target
64 MiB linear memory, one-billion fuel, 4 MiB Java heap and activation limits are
unchanged. Only activation and the two clock contracts are granted.

Whole scheduler, memory accounting, timer/executor and socket qualification remain
open. No #741 acceptance criterion is marked complete from this source proposal.


The first GC producer (`a5c4385`, run `39960502389`) completed the reference and
real compiler controls, component and all twenty-four original C captures. Its reader then
rejected TeaVM's actual `TEAVM_FIELD(..., TeaVM_Reference, object) = NULL` spelling;
no signed runtime case ran. That failure stays retained. The corrected reader
continues to require reachable mark/sweep and weak-field clearing.

The retained-only continuation authenticates the original whole 106-member archive,
302 original Git preimages, unchanged compiled inputs and separate current
controller identities. It restores only five missing package files against the
original package-input digests: three WIT files generated from the unchanged
source template, and two resource files extracted from the same pinned Commons
JAR. It runs the unchanged four signed cases and two denials, with zero guest or
native compilations. The retained selection keeps its exact compiled-input/source bridge and refuses
changed inputs; it cannot relabel this historical component as a newer build. Reference/control results retain their original failed-job origin;
only new signed results can establish the component's collection witnesses.


The retained-only attempt (`6b72fccc`, run `39966347038`) passed authentication,
package recovery and both grant denials, then its first GC call trapped after
about five seconds. No signed GC case passed. A failed root check could leave the
accepted child waiting; a child initializer exception could leave Commons'
factory claimed before its result was published, masking the original error.
The next fresh fixture records finite collector/victim/own-root phases and
completes only these failure paths: abort/notify/join for a failed root, or a
recorded child failure followed by normal null publication and child settlement.
The existing child-failure guard rejects that null before any result use or
success. Collection flags, weak-clear witnesses, success strings and budgets
remain unchanged. This is diagnostic error completion, with no underlying GC
runtime fix claimed. The push-owned programme now selects the fresh compiler
job (one maintained unsigned warm-up plus one target; zero native builds).

The bounded diagnostic run
[`41067407392`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41067407392)
at `8943e074e5e098161dcfbbcffd60850b9e473c1d` passed native authentication,
reference/compiler controls, construction and both grant denials, then reproduced
the first signed `gc` call's memory-out-of-bounds trap. Its eight numeric frames
resolve through the exact component name section from `ArrayDeque.ensureCapacity`
and `addLast` back through `Object.monitorEnterWait`, `Fiber.suspend`, monitor
entry and `Capsule.checked`. Artifact `12985366080` is 1,263,076 compressed bytes
with SHA-256 `1ad9719ce4829db1f09bc0a50faa69e02f795eba199a8d6e8a5f34f67b4a124e`;
the component SHA-256 is `63e5cbe6f2ed086bc784b15b1e78d1e824cf7da14eddf705f220f81393aecbe7`.
No signed GC case passed.

The retained C shows that the contended monitor deque and callback are registered
as live shadow roots before the allocating call. The corruption instead matches
the pinned TeaVM 0.15 C backend's 32-bit heap-layout defect fixed upstream by
[`konsoletyper/teavm#1281`](https://github.com/konsoletyper/teavm/pull/1281), commit
`c197880e951b8ecb6c6ee5bffa7c16563be790f3`: object and array sizes were rounded
to the four-byte pointer size even though long/double arraycopy uses a fixed
eight-byte data offset. A misaligned arraycopy can therefore overwrite a later
object, with the observed invalid `ArrayDeque` receiver being the downstream
fault rather than a missing root store.

The repair backports only upstream's generated class-size initializers,
allocator/collector array-size expressions and heap-tracer expression after the
exact compiler emits C. It fails closed on
unknown function or class-initializer shapes and records original/adapted hashes
for every changed C file. The application, Commons library, continuation/monitor
transforms, grants, four MiB Java heap, 64 MiB linear memory, one-billion fuel,
weak witnesses and success assertions are unchanged. Focused source checks do
not qualify runtime collection; the draft still requires new signed `gc` and
fresh-state outcomes.

Exact-head run
[`41075609429`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41075609429)
at `cb1ab83f4a6e7de78cf7318d58684f51828eaf2f` removed the original
memory-out-of-bounds fault but did not pass. The first signed `gc` call remained
parked until the unchanged five-second capability wall boundary, then its
uncaught wait failure entered TeaVM's unavailable print stub and trapped as
`unreachable-code`. It consumed 5,366,604 fuel with a 9,791,504-byte peak; no
effect or external byte was recorded. The exact component is
`sha256:77c34e8e7d5b893310d0afbe5517fcfbe2ef55730f5fa1c0bdad7348a3f0de22`.
No signed GC case passed.

The retained generated collector exposed a concrete first hypothesis. TeaVM stores an
inflated `Object.Monitor` only as a tagged pointer in the object's header hash.
`GC.markObjectData` follows class-layout fields but not that header pointer, and
`GC.updatePointers` likewise never rewrites it after compaction. A collection
while the child is parked can therefore collect or move the monitor that owns
its notify listener and continuation. Root's later `notifyAll()` then cannot
deliver that wake. This is the same still-open TeaVM C-backend defect reported
as [`konsoletyper/teavm#1330`](https://github.com/konsoletyper/teavm/issues/1330).

The second candidate repair changes only those two generated collector boundaries. It
marks the unpacked monitor together with every live object or array, preserves
the young-generation result, and repacks the pointer returned by the existing
relocation table before ordinary field/array pointer updates. Exact generated
function shapes and input/output hashes are required. No monitor queue, Java
application/library code, assertion, capability, ownership limit, memory/fuel
limit or retirement rule changes.

Exact-head run
[`41083065844`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41083065844)
at `6a3958d8401f5163ef32984b0da4f8ccdd3b3cf1` showed that this repair is not yet
sufficient. Construction and both grant denials passed, but the first signed
`gc` call still trapped with memory out of bounds after 47,864,606 fuel and a
10,211,360-byte peak; it recorded no effect. The exact numeric frames enter
`GC.markObjectData` from its mark queue and fail while reading the queued
candidate's class. No signed GC case passed.

Profile `teavm-0.15-c-packed-monitor-gc-root-v2` therefore added only bounded,
fail-closed validity traps before a packed monitor candidate is enqueued. Six
distinct no-output trap sites distinguish below-heap, past-heap, truncated,
misaligned, free-chunk and unknown-class candidates. They do not discard a bad
edge, manufacture a wake, change collection, raise a limit or qualify runtime
success.

Exact-head diagnostic run
[`41091472466`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41091472466)
at `6afd60eb3b0bb6d8654b51af45272730c91a710e` disproved that hypothesis. The
packed-monitor candidate passed all six checks; none of their distinct trap
frames fired. The eventual memory-out-of-bounds frame is still
`GC.markObjectData`, but its exact offset is the ordinary class lookup after
monitor validation. The caller offset is the static-root phase of `GC.mark`, so
an invalid object reference has already entered the mark queue. Construction
and both grant denials still passed; the first signed `gc` case trapped after
28,147,480 fuel at a 9,791,504-byte peak with zero effects. No signed case
passed.

Profile `teavm-0.15-c-packed-monitor-gc-root-v3` adds the same six bounded,
fail-closed checks at `GC.enqueueMark`. A bad reference now traps before queue
insertion, preserving the exact caller frame that supplied it. This is
diagnostic only: it does not discard the reference, change the application,
alter collection order, raise a limit or claim runtime qualification.

Exact-head run
[`41098690060`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41098690060)
at `82fcf9871e042665b7b46d8b2d99c12d5db6469f` reached that guard. Function 514
is the retained `teavm_enqueued_root_trap_unknown_class`; its caller is
`GC.markFields` inlined into `GC.markObject`, so the invalid value came from a
live object's compiler-described reference field. Both grant denials passed,
but the first signed case trapped and no collection or signed success was
observed. This excludes both the packed monitor and a direct static-root value.

The matching compiler defect is TeaVM 0.15.0's nested-handler volatile-definition
analysis. A definition made inside a nested protected body is backed up for that
inner handler, but not on entry to each live outer handler. After a parked
continuation resumes, C exception lowering can therefore publish an undefined
reference temporary into an otherwise live heap object. TeaVM repaired this in
commit `ae0630dd286cf57bcb4ec175696ae8010e42588c`. The private compiler derivation
now applies those exact four lines to the hash-pinned 0.15.0 source and replaces
both compiler outputs for that source,
`VolatileDefinitionFinder.class` and its anonymous visitor
`VolatileDefinitionFinder$1.class`, in addition to the eleven already bound
compiler classes. Run `41105074552` failed closed before compiler or guest
execution because the replacement closure originally named only the outer
class even though the repaired assignment visitor compiles into `$1`. The
13-class closure now requires both exact outputs and rejects every missing or
unexpected companion. Application/library paths, GC order, capabilities and
limits remain unchanged. Successful signed execution is still required.

Exact-head run
[`41109634746`](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41109634746)
at `87f79d417903b1794a99e4e5397fc266209a3555` proved that structural repair is
present but did not qualify execution. Its only artifact is `13004985825`, with
archive digest
`sha256:9db4440ef81ea0e5dbea0f385ec3d0384e29400318657616bd186b9e996bfc0c`.
Construction and both grant-denial controls passed. The first signed `gc` call
then trapped with zero effects after 5,117,411 fuel at a 10,211,360-byte peak;
no signed GC case and no collection passed. The component identity is
`sha256:53f9238a43e73ca46892f0f70f16f43a0cf818452b055a832f934fb0e64436d5`.
Its exact frames map to `teavm_enqueued_root_trap_unknown_class`,
`GC.enqueueMark`, `GC.markObject`, `GC.markObjectData`, `GC.mark`, and
`GC.doCollectGarbage`. The enqueue caller is still an inlined `GC.markFields`
edge: an aligned, in-heap, non-free reference stored in a live object's
compiler-described field has a header class outside TeaVM's known class table.
That excludes the packed-monitor repair and a direct static root again; it does
not show that the nested-handler patch repaired runtime execution.

Profile `teavm-0.15-c-packed-monitor-gc-root-v4` leaves all earlier fail-closed
checks in place and adds a bounded identity-only diagnostic at that exact field
edge. For an already valid unknown-class reference, noinline frame names encode
the parent class-table index in three hexadecimal digits and the field offset
in two, with strict maxima of 4095 and 255. Out-of-range values trap separately.
The candidate is still passed to the unchanged `GC.enqueueMark` path otherwise;
the diagnostic neither drops an edge nor changes GC order, heap size, fuel,
capabilities, assertions, ownership, retirement, or the application/library
path. A hosted rerun is required to identify the producer before any further
runtime/compiler repair is justified.
