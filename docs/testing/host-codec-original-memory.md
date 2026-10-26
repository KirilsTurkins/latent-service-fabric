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

## Canonical completion closure backing

[The focused v13 evidence](evidence/canonical-worker-function-native-2026-10-26.json)
binds [run 40259061940](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40259061940)
at `1f8eb3411c87454d19fd543339cd6e9b07342b20`: four new private controls and
the actual request-5/refusal/fresh-42 control passed, with no ignored cases.
All 25 archive members, 22 raw channels and 8,907 source bindings were checked.
The selected completion closure now reserves its exact layout after pending
admission 4 and before polling, keeping its original owner through queue/drop
and one-shot invocation. The initial `743cf2c4` attempt failed compilation with
E0308 and executed zero controls; wrapping its separate old stream callback in
the infallible Legacy adapter preserved that callback's body and allocation.
That Legacy stream Box, queue/node backing and other opaque/transitive backing
remain unpaid gaps. This unsigned native result does not close #736 or establish
an allocator/RSS ceiling, and does not replay the v11/v12 or Java qualifications.

## Canonical scheduler queue backing

[The focused v14 evidence](evidence/canonical-queue-nodes-native-2026-10-26.json)
binds [run 40270862197](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40270862197)
at `b5fc40c2703621c23c0107434c46933ef78846ec`: four new private queue controls
and seven affected/new actual canonical cases passed, each with zero failures
or ignored cases. The actual cases cover eight typed memory-refusal/fresh-42
scenarios, including both upstream nodes before guest fuel consumption. All 37
archive members, 34 raw channels, 17 zero-exit commands and 8,914 before/after
source bindings were checked; the declared `tools/intellij.cmd` checkout line
ending conversion is retained. The compiled queue entry is 120 bytes, aligned
to 8; this is a backing-layout witness, not a new memory grant or RSS ceiling.

Queue nodes are admitted before effects and the same physical node survives
pending calls, promotion, waits, cancellation and fiber/worker execution. Both
completion and initial PushFuture nodes precede the first host poll, with
independent unused refunds on Ready. The original host-local owner positions
2–5 remain identifiable at global requests 4–7 after the two new upstream
nodes; the new host nodes are local 6/7 at globals 8/9. Those four affected
actual controls were deliberately re-executed. The first `c4a1afeb` attempt
failed private compilation (E0576/E0502), executed zero controls, and remains
separately recorded. The corrected programme kept the original two locked
targets and all job, command, cleanup, activation and compile-job limits.

This unsigned native result covers the queue-entry owner and its bounded
integration cases. FuturesUnordered task/stub/ready-queue and weak backing,
other scheduler collections, the Legacy stream callback Box and transitive
allocations remain open. It does not close #736 or qualify a whole allocator,
runtime or signed-language path.

## Owned unordered futures backing

[The focused v15 evidence](evidence/canonical-unordered-backing-native-2026-10-26.json)
binds [run 40294127180](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40294127180)
at `a32624956270c6e18f3f108b831574e22368704b`: six new private ownership
controls, eight canonical cases and six affected ordinary host cases passed,
with zero failures or ignored cases. The canonical cases cover nine typed
refusal/fresh-42 scenarios. All 67 archive members, 64 raw channels, 32 zero-exit
commands and 8,932 before/after source rows were checked. The compiled Task,
ready-queue and scheduler-entry headers are 120, 80 and 120 bytes (alignment 8);
JoinState is 80 bytes. These exact layouts are witnesses, not new grants.

The private sized header keeps its original charge through the last weak
reference and refunds only after physical deallocation returns. Escaped wakers
retain both Task and weak ready-queue backing; destructor unwind intentionally
retains the same original charge. Lazy initialization and prepared task slots
precede effects at all six producers, and wake/publication adds no fallible
allocation. None keeps the original FuturesUnordered path. Callback-local
owners 2 through 7 now remain identifiable at globals 6 through 11 after two
queue entries and two shared headers; the new task owner is local 8/global 12.
The two initialization refusals occur before guest fuel consumption.

The cancellation cases observe each Store's actual six-owner sequence. After
Store destruction, an escaped Task waker retains 712 bytes: the observed Task
120 and ready-queue 80 plus two original 256-byte owner escrows. A real late wake
releases those same owners without admissions or changes to the foreign Store's
bytes/reservations. The lift-cancellation case warms the real two shared headers
without consuming guest fuel before taking its original Store baseline; every
original post-cancellation/foreign-Store subtraction and final-zero assertion
remains. Ordinary cases retain their original 1 MiB host-memory grant; canonical
cases retain 64 MiB, with the same fuel, wall and process limits.
The lift-cancellation case keeps its stricter pre-existing 1,000,000 installed
guest-fuel cap within the unchanged 1,000,000,000 grant.

The earlier `4eca00b9` focused run passed 18 controls. Its broader Rust CI then
reported 481 passed, two failed and 11 ignored: those two old cancellation
oracles omitted correctly retained backing. Their test-only correction and
inclusion produced the current 20-pass result, without production changes.
The first `ce233c98` attempt had failed private compilation with one E0599 and
executed zero tests; its missing is_empty adapter and failed receipt remain
separate history. No unrelated private or signed-language/Java campaign was
replayed. This unsigned native result leaves Legacy future/stream Boxes, other
collections and transitive backing open; it does not close #736 or establish
an allocator/RSS ceiling.

## Owned concurrent outer and sync-result backing

[The v16 evidence](evidence/canonical-outer-sync-result-native-2026-10-26.json)
keeps two source-bound results separate. The first attempt at `405c2e4`
([run 40305108367](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40305108367))
passed six new private controls and three actual host controls, then **failed**
the callback-error physical-peak oracle. Its final source-after checks were not
reached. Those nine raw passes remain historical; the failed run is preserved.

The separate completion at `8f7498b7a7c101a4ec992b5482ea1dd9b43bc067`
([run 40309368682](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40309368682))
passed only the four remaining actual cases: corrected callback error, ordinary
None embedding, Accessor spawn and typed result-refusal/fresh Store. It used one
locked root host target, ten zero-exit commands and four exact no-skip outcomes.
The two artifacts retain 41 and 23 members respectively. The initial source
snapshots each bind 8,933 rows; only the completion reached before/after source
equality. All 274 vendor rows and the source-reader/production/component pins
are identical across attempts. This is thirteen distinct passed control IDs
across two sources, **not** a newly executed thirteen-control programme.

Both outer Future Boxes are admitted through the original NativeMemory before
polling. The sync-lowered result has its own affine guard in CalleeFinished,
so outer completion or a set-event error cannot refund a still-live result Box.
Exact downcast, raw move and matching nonzero Global deallocation precede the
same original guard's refund. Wrong type retains its envelope; destructor unwind
retains the charge conservatively. ZST and ordinary None keep their original
physical routes. Inline HostTask/outer metadata may enlarge and is not all
claimed paid by this slice; transitive R buffers remain outside its Box charge.

The corrected test distinguishes reserved capacity from confirmed physical
usage. On input Err, result backing was never allocated, while its real boxed
owner's 256-byte escrow existed. The test asserts the actual `(u32,)` or
`Vec<Val>` layout before excluding **only that unallocated backing** from the
peak lower bound; all eight admissions, original error, Gate poll and final-zero
assertions remain. Pending and late-waker/foreign-Store controls passed in the
first attempt and were not replayed. Original 1 MiB/one-billion-fuel/five-second
host grants and job/command/cleanup bounds remain unchanged.

Subsequent current-main dependency/action/metadata composition does not retag
these outcomes or their executed lock/source identities. The earlier v15 result
also remains historical. This unsigned native slice leaves remaining stream
Boxes, collections, transitive/inline metadata, stack/GC/lowering and full
allocator/RSS/cost ownership open; it does not close #736 or #745.

## Finite stream outer source qualification

Source `fe9a04fd8e94894ecdd15c45d9e6c5d6ca547fd5` (PR1504, tree `ca48a751...`)
passed [the one focused programme](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40339377974):
six exact controls, no failed/ignored cases, seventeen zero-exit commands and
thirty-four raw channels. The [durable source-bound receipt](evidence/canonical-stream-outers-native-2026-10-26.json)
anchors the 1,423,943-byte artifact, all38 safe CRC/SHA members, and8,961
before/after source bindings. One fixed wasm-tools1.254 parse produced the
788-byte canonical component only in owning RunnerTemp. Captured source was
identical BEFORE and AFTER execution. Separately, the declared Git-to-checkout
launcher CRLF conversion explains its Git blob versus checkout identity; it
was not a change during the run.

The four private canonical controls use a bounded NativeMemory COUNTER owner,
64MiB payload ceiling,1B installed fuel and120-second ceiling. They are not
original ActivationBudget or signed-node evidence. The two public HostReady
controls use the ORIGINAL1MiB/1B-fuel/5-second ActivationBudget. The owning
job/process/list/cleanup bounds and2compile jobs stayed unchanged.

| Actual route | Local queue/Task/outer owners | Observed global requests | Refusal boundary |
| --- | --- | --- | --- |
| Private guest write |1/2/3|24/25/26|Before Busy and transmit mutation; polls0|
| Private guest read |1/2/3|23/24/25|Before Busy and transmit mutation; polls0|
| Private reverse host pipe |1/2/3|24/25/26|Existing Busy/GuestReady preserved; consumer polls0|
| Public HostReady loop |1/2/3|6/7/8|Original grant refusal before consumer effects; polls0|

These twelve refusal vectors retain their actual source/owner identities.
Private ready/pending/error and None variants passed in both directions and
the reverse caller. Read checks actual byte42 at offset512 in the SAME memory;
write consumes actual byte42. Fresh-Store answer42 is a separate reuse check.
Reverse await-error does not invent settled state or handle rollback: physical
Store destruction still must retire the genuine remaining owners.

Public ready/pending, producer/consumer original errors and pending teardown
passed. The original map cleanup destroys the consumer before Store destruction
on success/error. Genuine escaped waker ownership stays paid until real late
wake/drop, with no new admission or credit against the live foreign Store.
The pending-byte assertion is a lower bound for the measured scopes, not a
complete allocator census. None retains its original physical helper/loop order.

**This focused success does not clear Security.** PR head `fe9a04fd` was
evaluated through synthetic merge `384b3b6f` (parents `f8e78744`, `fe9a04fd`),
whose tree is the SAME `ca48a751...` tree as the qualified native head. That
merge failed [RustSec](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40339385076/job/121629777721)
on ten findings in the standalone vendor lock's old zstd-safe/zstd-sys closure.
Dependency/cache backport, strict source authentication and audit repair are
separate pending work. This receipt is not retagged to later dependencies or
used as proof that a repaired cache/source closure executed these cases.

Inner producer/consume/accept boxes, consumer Arc/pinned consumer, buffers,
tables, collections, transitive backing and full CPU/memory accounting remain
open. Exact outer Layout payloads are not allocator RSS quotas. This unsigned
native slice neither closes #736 nor claims a full vendor/runtime suite; no
prior v15/v16 or language programme was replayed.

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


### Standalone cache dependency repair

The separate cache-repair cohort at `757ae2285fdc1e0c3aef5d23a6b136b28fec2b86` passed its [five-command programme](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40356260339): locked parent checking with the existing compiler/cache features, cache-lib test building, target-library lookup, exact listing and the upstream `tests::test_write_read_cache` roundtrip. The one executed test passed with zero ignored; 21 other tests were filtered and unexecuted. Both Cargo streams identified the fixed zstd 0.14.3 / zstd-safe 8.2.0 / zstd-sys 2.1.2+zstd.1.5.7 graph and the local complete cache source. All 8,975 before/after source bindings matched, including the declared IntelliJ CRLF checkout conversion.

The [separate machine receipt](evidence/wasmtime-cache-security-repair-2026-10-26.json) preserves the original six stream-control passes at `fe9a04fd8e94894ecdd15c45d9e6c5d6ca547fd5`, the ten Security findings and seven stale source-reader assertions. The six controls were not replayed or retagged to the new dependency cohort. RustSec, source/workflow and secret scanning jobs passed for the repaired head; SDK advisories and fail-closed canaries failed. This receipt records those job outcomes without inferring their cause or claiming a whole Security pass.

This cache test uses no ActivationBudget and establishes no guest quota, RSS or complete-cost claim. Inner factories, consumer allocation, stream buffers, collections and transitive memory/CPU accounting remain open.


The SDK-advisory and canary failures were traced to the new Cargo inventory entry lacking the existing isolated-package marker and empty workspace declaration. The follow-up adds `[workspace]`, the exact whole-manifest inventory digest and the matching source-provenance bindings; it leaves the generic scanner policy, all cache/Wasmtime Rust and all three locks unchanged. Both locked offline workspace resolutions and the 15 affected pure Security controls passed. The five-command result remains bound to its original `757ae...` source; no cache or runtime programme was replayed for this manifest-only repair. A fresh hosted Security result is still pending.


Main CI run 40358355805 (job 121702592768) recorded 8,461 tests with two failures and 17 errors: 15 workspace-inventory errors and four missing-cache format/placeholder fixture failures. The follow-up adds one mandatory adjacent cache copy in each of the two existing fixtures; six affected pure controls passed in 65.687 seconds with no failures or ignored cases. These results do not claim a fresh whole-CI or hosted Security pass.


### Selected consumer backing: dated native qualification

The [2026-10-26 consumer-cell receipt](evidence/canonical-consumer-cell-native-2026-10-26.json)
records tested source `e4ce721088d51a718c837c9586afd187379df36f`, tree
`4cb809a8a11ec70fd1ec9bccddf3645868438372`, owning run40372424379/job121746381721.
All seven exact controls passed with zero ignored: five private finite ownership
controls and two public HostReady cases. The18 supervised commands exited0,
with36 raw channels and39 authenticated artifact members. All8,976 captured
source bindings were unchanged before/after;8,975 matched Git directly and the
remaining tools/intellij.cmd row used the declared Git-LF→checkout-CRLF conversion.
That checkout conversion was separate from the unchanged execution inputs.

The public controls use the original1MiB/1B fuel/5-second ActivationBudget.
Five actual refusal positions—local1..5/global6..10—kept producer/consumer polls0,
covering queue, Task, outer, pinned C and shared C cell admission. Five cleanup
modes preserved the foreign Store and ended at zero: ready and pending-complete
verified payload42; producer-error, consumer-error and pending-Store-drop do not
claim payload delivery. The refusal case verifies same-budget fresh42; pending
Store-drop uses the real release/late-wake path. Private controls use
ownership counters without an ActivationBudget, guest execution or a generic
memory-ceiling/allocator-free observation claim.

Both locked Cargo library targets were observed with the authenticated275-file
Wasmtime source and mandatory14-file isolated cache backport/fixed dependency
graph. Original45m/2400/900/60/30 bounds,5-second cleanup and2 compile jobs stayed
unchanged. No WAT assembly, old four canonical cases, six-control programme,
cache roundtrip or language campaign was selected for replay.

Merge8d9c6b176ebc99c296d32490517138e7cef5258a/tree3dee326e7c44418472fdc127c07f262f7e5bb5d3
also included bot PR1509: only the two equal-size renderer Playwright package
JSON inputs differ from the tested tree; all other8,974 bindings and native
Rust/Cargo/locks/cache/owner/workflow inputs remain exact. The selected archive
size stayed85,975,040B. This is a dated receipt, without retagging execution to
the merged revision or later producer source.

The qualified scope is the selected consumer pinned-value/shared-cell backing.
Producer state, inner factory/future/closure Boxes, buffers and transitive heaps,
tables/collections, allocator RSS and whole CPU/memory/retirement coverage remain
open. This unsigned native result does not close #736 or qualify a signed guest.

The related PR CI run `40372479026` passed all 24 jobs including its aggregate; selected Security checks in `40372478831` passed, with the SDK advisory scope skipped. Those PR checks scanned merge `c09eb1ace82fee3e7b2dccbc42238cfb1bea4737`, whose tree is exactly the native-executed `4cb809a8...` tree; the native execution revision remains `e4ce7210...`. The prior baseline standalone rustup bootstrap conflict occurred before tests; the current feature standalone job passed.


## Producer shared-cell and closed Future adapter result, 2026-10-26

The [dated producer result](evidence/canonical-producer-cell-native-2026-10-26.json)
records eleven passing native controls at source 5b9fa5e8, run 40387684318 /
job 121800213039. The authenticated artifact binds 55 members, 26 completed
commands and 52 raw channels, including six private implementation controls,
three new public creation/conversion cases and two affected public stream cases.
The initial 83329299 attempt failed compilation before any test; the explicit
private conversion-method correction is retained separately.

These cases cover shared-cell preadmission, only the private Future adapter's
known body custody, repeated failed conversions, owning escape, Pending payload 42
and physical guard cleanup. Public controls retain the original 1 MiB memory / 1 billion fuel / 5 s
budget declaration. Private 64 MiB instrumentation is not ActivationBudget,
a generic memory ceiling, installed fuel or signed-component qualification.
General StreamProducer bodies, Buffer heaps and factory/inner-future backing
remain unpaid at this execution source. Executable identities were reported by
the owning build; executable bytes are not retained in the public ZIP.

The separate full-CI publication attempt refused audit query 46 with
resource-exhausted and no retained public subtype. Its exact cause remains
unproven. A publication-local fixed-reason diagnostic preserved the fatal
decision and all limits; the retry publication job 121827412736 and all seven
Security jobs passed at 6d666762. No native eleven-case replay was needed for
that Python-only diagnostic. PR 1517 was squash-merged into development as 87eb5d1d,
with its 29 feature paths and the six incoming builder paths independently joined.
The native execution remains dated 5b9fa5e8, not retagged to the merged source.
The remaining requirements of #736 stay open.
