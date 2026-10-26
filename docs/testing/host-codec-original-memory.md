# Ordinary host codec original-memory ownership

Admitted ordinary component invocations charge raw input backing capacity, decoded values,
actual Wasmtime dynamic result allocations and encoded output to the supplied
original activation budget. Raw input's existing allocation is charged at the
invocation ownership boundary. New decoded, lifted and encoded buffers reserve
before allocation; growth pays for old and replacement buffers while both exist.
The activation owner combines the backend's own guest-memory report with the
original ledger, whose peak includes native owners and result encoding.

The pinned Wasmtime 48.0.7 extension reserves actual strings, containers, names,
flags and boxed values before allocation. Parameter copies have an independent
refundable scope. It preserves the original host-call fuel calculation for UTF-8,
UTF-16 and Latin-1 decoding. Tiny dynamic values keep the original memory and fuel
ceilings; no signature-wide maximum is reserved for each small return.

Immutable result bytes retain their original capacity and reservation through
clones and RPC handoff. Actual values are destroyed before their scope refunds.
Cancelling a call at a legal Core post-return fuel yield unwinds its native result;
the caller's shared scope remains until its last owner drops. A bounded journal
copy belongs to its existing controller admission, allowing a physically finished
child to settle after the last actual source-result owner disappears.

## Retained native execution

[The public evidence](evidence/host-codec-original-memory-native-2026-10-22.json)
binds [run 39685022895](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39685022895)
at `7b6365ee39dea9770591a931b96711965f8a1aaf`. Its **61 controls passed** with
exact discovery and successful names, no ignored controls, 31 command records and
62 verified log streams. The complete 71-member archive and all five ordinary
native products were independently checked against GitHub run/job/artifact
metadata, the exact source and all 148 recipe/auxiliary materials.

The controls include payload growth/refusal and parent accounting, original raw
spare capacity, wire compatibility and retained capacity, tiny dynamic values,
typed original-budget errors, partial lifting, fuel-preserving encodings,
cancellation followed by same-budget Store reuse, journal child settlement,
selected C public-async/synchronous-Core admission, and one real ordinary backend
invocation whose result outlives Store cleanup.

The subsequent twelve-path limits/documentation merge preserves the full native
identity (3,593 files) and every material. The immutable successful receipt keeps
its original source revision. This evidence is source-bound CI qualification;
`signedQualification` remains false. No guest source or JavaScript engine was
compiled by this native programme. The source record explicitly leaves implicit
compiler inputs unattested and declares `hermetic: false`.

## Actual table and selected Store ownership

[The separate v2 evidence](evidence/host-codec-table-store-native-2026-10-22.json)
binds [run 39702795582](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39702795582)
at `de0aed36f0b135d6d88fb536484e60aee978f218`. **All 81 controls passed**:
the original 61, nine table controls, ten Store controls and one existing closed
trap-classification control. Independent whole-archive checks cover all 83
members, 37 command records, 74 log streams, five products, 3,603 native source
files and 148 recipe/auxiliary materials.

Table owners cover actual dynamic backing, replacement overlap and pooled
reset/decommit lifetime. Affine owners also cover the Store Box, selected Core
and Component instance layouts and selected instance/segment buffers. They stay
charged through user-data destruction. Successful cleanup and `into_data` refund
after deallocation; destructor unwind retains still-owned backing. Cancellation
cannot credit another live Store. The tiny component executes under its
unchanged 1 MiB memory and one-billion fuel grant; the codec controls retain
64 MiB/one-billion limits.

The evidence preserves three failed attempts separately: compilation before any
control, a count-limit fixture failure (69 passed/1 failed/11 unreached), and
binary-loader fixture failures (75 passed/5 failed/1 unreached). Their repaired
sources receive no retroactive passing credit. The original v1 receipt remains
unchanged. V2 is also unsigned and native-only, with implicit compiler inputs
unattested; no guest or JavaScript-engine build ran.

## Store-local registry ownership

[The separate v3 evidence](evidence/host-codec-registry-native-2026-10-22.json)
binds [run 39705847409](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39705847409)
at `48a6532d8e1f23e7abd8e47d2e75a4dcaf5216f9`. **All 85 native controls passed**,
including four registry controls. Independent checks cover all 87 archive members,
39 commands, 78 log streams, five products, 3,611 source files and 148 materials.

The three Store-local registry indices and sparse secondary module maps now pay
for actual backing, spare capacity and old/new replacement overlap. Registration
admits every replacement before publishing edges; refusal preserves previous
entries. Duplicate and foreign-Engine cases, sparse lookup, actual guest calls
and closed backtrace lookup are covered. Physical buffers are freed before their
owners refund. Shared Engine code metadata remains outside this Store-local slice.

Shared CI separately exposed a backend report that included native memory already
owned by the original ledger, causing finalization to charge it twice. That
integration failure remains distinct from this successful native tuple. The report
boundary correction keeps backend reports guest-only and final consumption
aggregate; a later composed source does not inherit this archive's execution claim.
V3 remains unsigned and native-only; previous receipts are unchanged.

## Store-local function reference ownership

[The separate v4 evidence](evidence/host-codec-funcrefs-native-2026-10-22.json)
binds [run 39711228748](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39711228748)
at `3e4178271b4b7fe75a69c8f0665dbe275b41d7c3`. **All 92 native controls passed**:
the previous 85 selectors, five actual function-reference controls and two
canonical C Ready handoff controls. Independent verification covers all 95
archive members, 43 commands, 86 log streams, five products, 3,615 source files
and 148 materials.

Selected function-reference boxes, arena capacity and root directories now retain
their original activation owners. All staged capacities and boxes are admitted
before publishing a root or pointer; refusal preserves earlier roots and guest
calls. InstancePre pairs admit both root slots together. Default-function lookup
preserves a defined function's original admission error. Legacy embeddings retain
their original arena behavior.

The same native run passed the strengthened backend/core reporting controls:
backend reports contain own guest memory, while the original ledger retains the
aggregate native peak. The later generic integration fixture correction at
`99be2b4275c72ee10a8f88d58d93f761cebb8d0e` equalizes request identity lengths;
the frozen v4 run did not execute that later fixture. V4 remains unsigned and
native-only; it did not compile or execute a C or TypeScript guest.

## Resource-substitution metadata ownership

[The separate v5 evidence](evidence/host-codec-resource-types-native-2026-10-22.json)
binds [run 39714929391](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39714929391)
at `94f2976f2fdba0b5f1a730d9fc668e9e61571443`. **All 97 native controls passed**,
including the previous 92 selectors and five resource-substitution cases.
Independent verification checked all 99 archive members, 45 commands, 90 log
streams, five products, 3,619 source files and 148 materials.

Imported and defined resource maps preadmit their finite capacity. Escaping
type and InstancePre metadata retain the original owners after Store and factory
destruction. Private shared handles free the actual map and Arc storage before
refunding their owners, including concurrent final drops. Actual engine controls
cover both admission refusals with prior-instance preservation and retry,
independent Store budgets, concurrent metadata release and unchanged tiny-call
memory and fuel limits.

The generic tight-memory node regression is outside those selected 97 controls.
It still failed before guest entry after the request fixture correction. Source
investigation found that initial linear memory could already exist while its
ledger observation remained pending through later native initialization. The
subsequent allocator notification repair is separate work; v5 does not qualify
it. This remains unsigned native evidence, with prior receipts unchanged.

## Canonical pending continuation backing

[The focused v12 evidence](evidence/canonical-pending-future-native-2026-10-26.json)
binds [run 40252236378](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40252236378)
at `5d72ee7886bfd4ed737d02d49e7f85a60c00f0cd`: all four new private controls and
the actual fourth-admission/refusal/fresh-42 control passed with no ignored cases.
All 25 archive members, 22 raw command channels and 8,906 Git source bindings were
checked. The exact continuation-output layout is reserved before the first poll;
Ready releases unused capacity, while Pending retains the same owner until its
Box is destroyed. These two host-libtest builds did not replay the v11 five or
the Java twelve. This is unsigned native qualification of that Box only, not an
allocator/RSS ceiling or completion of #736; completion WorkerFunction boxes,
queue/node backing and other opaque/transitive allocations remain separate gaps.

## Scope retained outside this slice

Initial linear-memory success/failure notifications, direct Core HostFunc construction, shared
preparation closures, concurrent tasks, hostcall backing and
request-context transitive allocations still need their remaining ownership
work. Serialized controller/transport frames and legacy Phase0 framing retain
their existing boundaries. These common runtime prerequisites are a partial
delivery for [#736](https://github.com/KirilsTurkins/latent-service-fabric/issues/736)
and [#745](https://github.com/KirilsTurkins/latent-service-fabric/issues/745); the
whole tickets and the full TypeScript cost criterion require their remaining
implementation and qualification.
