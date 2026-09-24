# Standalone Go capsule qualification

This is developer evidence for #547, separate from the beginner
[Go authoring guide](../component-development/go-authoring.md). Completion
requires the complete real-node and printed-guide gate at the final PR head.
No partial observation below authorizes a release or replaces human newcomer
review #345.

## Current integration gate and retained contention failures

The candidate `7376f20696e67982505e21b4356622260afbf4c9` is **not qualified
for merge**. Its [Go run 35987802416](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35987802416)
passed all ten actual SDK cases in 75.45 seconds, including warm service calls
that kept two owned fetch attempts and two completed compiler jobs while cache
hits increased from zero to two and four. The enforced node subsequently failed
the second word-count invocation with known, non-retryable `guest-trap` and the
closed `admission.currentness` reason `admission-authority-busy`. Consumption was
2,264 fuel, 2,424,832 peak guest-memory bytes, 1,808 receipt microseconds and no
child calls. Four greeting calls and the first word-count call had completed.

The [failed artifact 10803765513](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35987802416/artifacts/10803765513)
matches 2,353 pre-execution Git inputs. Its captured component imports and host
error path identify one of the monotonic or wall-clock scalar admissions;
random-provider errors do not use this host-trap path. The exact clock import,
bind/dispatch checkpoint and concurrent authority-fence holder were not
observed. This is an active host failure, not the older queued-readiness failure.
It has no completed node/guide or after-execution integrity result. The separate
[source archive](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35987802416/artifacts/10802971929)
matches 4,119 selected Git files and modes (40,181,202 bytes), SHA-256
`045be106204c1568edc4e9f6af449f43ac1ead620ccc1ba269ef631e6bc19520`.
CI merge `a702ffa587cf757052ca79dcdd7d8c86e740cd59` and the candidate share tree
`c4dea742013870481039be6cb10b4476284df706`.

A separate [development run 35987381210](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35987381210)
at actual squash `8f08f7a95dbd68aebc525120645a27dc5ab85e14` failed in the SDK
service case before reaching node qualification. This is the same tree as the
previously passing shared-runtime head `67763cdc`; the later failure is retained,
not replaced by that earlier success. Its [artifact 10803795740](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35987381210/artifacts/10803795740)
matches 2,352 pre-execution inputs. Nine SDK cases passed and one failed in
129.57 seconds. The first permitted child ended `DependencyFailed / Unavailable`
at `Queued`, with zero fuel and memory, 656 receipt microseconds and the closed
`AdmissionAuthorityBusy` diagnostic. Two cold jobs started: one completed and
one failed before the child's metadata fingerprint. No worker or readiness
gauges remained outstanding. Owned fetch-attempt counters increment before
dispatch and do not prove a physical disk read occurred.

The latter failure is confined to the original worker eligibility check or a
source-fetch currentness checkpoint before metadata fingerprinting. It does not
identify the exact checkpoint or competing holder. Neither attempt was rerun.
The previously added caller-side readiness wait deliberately left worker checks
and active host imports immediately fail-closed; these failures establish two
additional boundaries that need separate corrections and fresh qualification.
Changing the authority mutex, renewing proofs, replaying compilation or retrying
an entire capability call would not establish a safe fix. In particular, bind
and call setup can already own audit records, IDs and budget reservations.

The unchanged TypeScript candidate's [Go cross-check 35987595339](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35987595339)
passed all ten SDK cases (148.34 seconds), 27 node outcomes, 24 resource samples
and six guide steps (18.06 seconds), with clean/reaped owners and unchanged
source/tool identities. Its [artifact 10803063191](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35987595339/artifacts/10803063191)
matches 2,353 captured inputs; that workflow does not retain a separate full
source archive. This positive comparison does not qualify the failed Go head
or remove the shared-runtime review hold on the two remaining PRs.

## Bounded worker and clock correction

The follow-up changes only two demonstrated pre-effect boundaries. Opt-in
sealed-source compiler jobs retain one real-monotonic five-second window from
job creation, including queue and compilation time. Only pure currentness
checks wait; disk verification, hashing, compilation, linking and cache adoption
are not replayed. The selected original grant cannot be upgraded by catalog
renewal. The last waiter or pool shutdown signals the existing worker to stop
waiting while real source/document owners remain retained until task retirement.
Generic/native preparation and web inner fetches keep their existing behavior.

Clock admission uses an explicitly supplied node timer and one deadline-capped
window across binding and work admission. A bounded pending owner retains the
same row, IDs, audit owner and refundable 100-fuel charge. An entered callback
is never repeated, including when an authority returns Busy after invoking it.
No clock sample, monotonic guest observation or provider effect is retried.
Both APIs retain their legacy immediate paths when no timer is supplied.
The detailed ownership and scope contract is in
[package admission](../reference/package-admission.md#clock-leases-retries-and-fresh-admission).

Worker source `6491ab56bca6a0f0a1e844fee3680d998a03274d`, tree
`329eebbe9f9bf404c9de3ea0595ccd7936d672e4`, passed 55 focused Linux cases,
including seventeen new regressions and 38 prior readiness, authority and
compiler-ownership cases, with zero failures or ignored cases. The same actual
signed-fence test failed when only worker opt-in was disabled, and passed with
the correction. The successful path verified one physical component read/hash,
one compilation/link and one completed job. Tests also cover queue-expired
windows, cancellation/coalescing, original-grant expiry/revocation, foreign
catalog grants, malformed errors and actual owner reclamation. The final green
source archive SHA-256 is
`70e4f26034c259450b39c77091b8faafc1b2d6519bef99f03750ca6076c0e7df`;
its execution log is
`ac4dd37f662b9946d78d6f5ae6af56085ee19ff1f4883c6acee18b47952e9daa`.
This bounded run used the retained Linux image with two CPUs, 8 GiB memory,
two Cargo jobs, no network and no image pull. The initial missing test-trait
import and the deterministic negative run are retained separately.

These are focused regression results, not SDK or final-head qualification.
Clock Linux tests, integrated validation and fresh complete CI remain required
before either pending ticket PR is merged. Runtime release HOLD and human
newcomer review #345 are unchanged.

## Verified execution and measurements

[Run 35935390363](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35935390363)
passed the complete qualification at
`e3d001d54906a8d83b78b7e62197d9a289efebc1`. This is evidence for that exact
source, not an automatic approval of later integration changes. The retained
[execution artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35935390363/artifacts/10782284979),
[source archive](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35935390363/artifacts/10782259682)
and [pinned tools](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35935390363/artifacts/10783211184)
separate compiler reproduction, source identity and executed behavior.

Independent read-only verification matched all 4,040 archived files against
Git and all 2,323 captured runtime, SDK, WIT, schema, helper and guide inputs
against that revision. The source archive SHA-256 is
`74992de813ff7e94e8616529944827a7ee0ee5eb068aa9de951aa33fe8252a24`;
`qualification.json` is
`sha256:836d5d8fa6abfdbd870c9051630772505f53df26bccd35197c3d4defa3d6bd62`.
Before/after source and executable identities were identical. The capture is
explicit-input evidence, not an attestation of every implicit compiler input.

All fourteen components built and all ten real SDK/provider tests passed in
153.94 seconds. These cover every capability family, stale and foreign
handles, independent chunks, explicit secret zeroization, uncertain effects
without replay, child service outcomes, pending-import cancellation and fresh
reuse. The runtime ABI diagnostic retained full-width integers, UTF-8/NUL,
record/list/result values and fresh-state recovery. The separate recovery
diagnostic observed actual `OutOfFuel` with ten monotonic-clock and four entropy
imports, then returned `1` in a fresh Store; it does not replace admission.

The enforced node recorded 27 known invocation outcomes and 24 resource samples.
All twelve tutorial outcomes, HTTP allow/deny, trap, memory/fuel exhaustion,
deadline, explicit cancellation, client disconnect and successful subsequent
invocations passed. Missing runtime grants and an unsigned package were denied.
All six printed Bash blocks passed in 18.715 seconds, including deployment
deletion and clean process exit. No release publication was performed.

Measurements below are one Linux CI observation, not portable performance
guarantees. Node readiness took 67.142 ms. The startup/control path had already
warmed the greeting image, so its first tutorial call is not a cold compile.
Each invocation still uses fresh guest state.

| Project | Component bytes | Build/package seconds | First tutorial CLI milliseconds | Warm CLI milliseconds |
| --- | ---: | ---: | ---: | ---: |
| Greeting | 2,521,283 | 6.200 | 29.211, prewarmed | 25.244 |
| Word-count | 2,519,641 | 6.226 | 6,943.591 | 25.235 |
| Shipping | 2,509,162 | 6.080 | 6,932.484 | 25.097 |
| HTTP status | 2,553,028 | 6.229 | 7,087.767 | 30.337 |
| Recovery | 2,509,474 | 6.109 | 6,953.292 | 25.246 |

Component compilation alone took 3.546–3.629 seconds per standalone project;
the build/package column includes generation, validation and package inspection.
The nine SDK components ranged from 2,509,958 to 2,619,526 bytes. Ordinary
tutorial invocations peaked at 3,014,656 guest-memory bytes. The actual memory
exhaustion reached 66,584,576 bytes within the 67,108,864-byte ceiling; the
four-worker fuel fixture consumed exactly 1,000,000,000 fuel and returned
`resource-exhausted` after 1,091,747 receipt microseconds. Every subsequent
recovery call returned `1`.

| Node phase | Samples | RSS bytes | OS threads | Compiled cache entries |
| --- | ---: | ---: | ---: | ---: |
| Empty | 1 | 56,524,800 | 8 | 0 |
| Five dormant deployments | 3 | 67,936,256 | 7 | 0 |
| Nine dormant deployments | 3 | 67,940,352 | 7 | 0 |
| Seventeen dormant deployments | 3 | 67,944,448 | 7 | 0 |
| Held cancellation call | 1 | 138,645,504 | 8 | 2 |
| After cancellation | 1 | 136,720,384 | 8 | 2 |
| After deleting every deployment | 1 | 137,551,872 | 7 | 2 |

Every sample contained exactly one node process, one TCP listener and no UDP
socket. Dormant and idle samples had no occupied cell, activation quota or
activation-scoped owner; service-resident ownership stayed zero. The active
samples had one occupied cell. No extra process, thread, listener or guest heap
was owned by a dormant deployment. The node's bounded shared cache retained at
most two entries: 13,217,872 compiled-image bytes and 5,062,502 source bytes,
with 24 hits, five misses and three evictions at the final sample. Its retained
cache and allocator high-water state explain why deleting deployments does not
return RSS to the empty-node value; RSS is not a count of live guest Stores.

All three held HTTP peers physically closed, with eight authorized requests,
zero unexpected requests and a reaped peer process. The reaped node's final
record reported zero live Stores, host states, instances, temporary buffers,
cancellation probes, provider sessions/handles/calls/results and compiler or
cleanup jobs. Shared compiler and cleanup workers were joined. That snapshot
preceded the direct four-parked-application-goroutine assertion in the blob
cancellation/fresh-state fixture; the following integrated run executes it.

## Integrated source and cross-language gate

[Run 35939625196](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35939625196)
passed complete Go qualification at
`2ba471f64fa6596fd9ed8a008908c70a00345821`, including the shared Java/.NET
profiles, latest TypeScript authoring implementation and four parked Go workers
before pending blob creation. All fourteen components built, all ten actual
SDK cases passed in 152.96 seconds, and the enforced node completed all 27
outcomes, 24 resource samples, dormant populations 5/9/17, six printed Bash
steps and physical cleanup. The fuel fixture consumed exactly 1 billion fuel;
subsequent invocations returned fresh state. All three held HTTP peers closed,
with eight authorized requests and no unexpected request. Source and executable
identities were unchanged through final integrity.

Independent verification matched all 2,330 captured execution inputs and
4,092 archived files to that exact Git head. Its CI merge
`2df1ce44c38d22d6ceb17fe20e39f113eb7939f0` has the same tree as the candidate,
`bdfdc2db2c41f912dafc6589c7d80252c4fdb146`. The retained
[execution artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35939625196/artifacts/10785296375),
[source archive](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35939625196/artifacts/10784675263)
and [pinned tools](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35939625196/artifacts/10784452142)
remain separate. `qualification.json` SHA-256 is
`a456d64bec00b94d5c016a169c4aa97c8f8f6b0258331207b80b213a371d813c`;
the source archive is
`3e62a5d6dc2fb20df8700b51beaf737743ef97d8f9f601a9b2e0d578fdbdd0b7`.
This does not attest uncaptured implicit compiler inputs.

[Broad CI 35939625226](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35939625226)
also passed every required job. Its
[runtime discovery and execution artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35939625226/artifacts/10785733372)
retains the actual clock-fuel, ordinary typed-function-reference and finite
binding-lease regressions, in addition to the SDK/node qualification above.

The same head is not an all-CI pass: its
[cross-TypeScript run 35939625050](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35939625050)
passed all ten SDK cases in 888.32 seconds, then the first node deployment apply
failed after 5.940224427 seconds with `admission-clock-lease-uncovered` and an
unknown public outcome. Durable audit attempt 7, bounded read-only diagnostics
and the complete failed attempt are
[retained](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35939625050/artifacts/10785326735).
It was not retried. One full package inspection can itself exceed the existing
five-second control lease. The integrated correction renews explicit control
authority after that inspection, before the next plan/currentness check, while
retaining finite lease/deadline bounds, revocation checks, one package read and
no publication on failure. Startup, historical replay and invocation do not
receive this control-only renewal.

A separate [cross-TypeScript run 35938546318](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35938546318)
at .NET integration head `0c08d3f175f8cb58546208abe7f797cd27d6b61b` reached
child admission after a 67.452-second cold parent start. The child's retained
outcome is `Unavailable` at `Resolved`, with zero consumption. The fixture had
no monitor and refreshed synthetic load only before the top-level request,
while the unchanged freshness policy allows 60 seconds. Stale child load is a
strong source/timing inference, not a captured private error reason. The fixture
now samples the same fixed healthy profile at each admission, including nested
children; production load observation, freshness limits, quotas, budgets and
retry behavior are unchanged. Deterministic actual-component regressions inject
a stale child sample without sleeping and require zero-use rejection, then
require one successful parent/child execution with fresh samples.

At shared integration head `9f51c60cdd686eb23aab5408f5dde75b4e7f7d09`,
[broad Linux CI 35942901770](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35942901770)
passed all seventeen local-service cases, including the actual stale/fresh
parent-child regressions, and all three slow-package-preparation lease cases.
Its [execution artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35942901770/artifacts/10786806256)
also retains the 32 KiB audit-queue drain regression and both wire/CLI ownership
counter projections. These are executed Linux tests, not only discovery or
native compilation evidence.

That head's [TypeScript qualification 35942901312](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35942901312)
passed all ten SDK cases, all 5/9/17 dormant samples, twelve tutorial calls and
seven fault/fresh-state calls. Its first allowed HTTP call instead returned the
declared `connection-failed` result; the [failed artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35942901312/artifacts/10786577160)
remains a failure, without complete node, shutdown or guide evidence. The
sequential controls and prior invocations took at least 726.851 seconds after
the fixture peer started, but that peer had an independent 300-second lifetime.
Expiry is supported by source and timing, not a captured private socket error.
No operation was retried.

The integrated fixture correction uses an absolute monotonic peer expiry
bounded by its qualification owner, including startup and socket waits.
Ordinary peers still default to 300 seconds; their 32-request, two-second I/O
and three-second physical-close ceilings are unchanged. Failed attempts retain
bounded peer exit/reaping facts and closed diagnostic tokens. Measured
TypeScript preparation costs also project about 153 seconds for deletion,
beyond the old owner's remaining time; this is an estimate, not an observed
TypeScript cleanup. Only that language's isolated qualification owner now
allows 1,200 seconds. Go retains 900 seconds, and all production activation,
compile, control-lease, proof, quota and cleanup bounds remain unchanged. The
following run supplies full execution evidence for that finite profile.

[TypeScript cross-qualification 35963178639](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35963178639)
passed at `a880cfd731f82194c36265886a65a1374d0313fb`; its
[execution artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35963178639/artifacts/10794941119)
contains all ten SDK cases passing in 883.43 seconds, all 27 node invocations,
24 resource samples and dormant populations 5/9/17. All seventeen single-attempt
deployment deletions succeeded in a measured total of 150.48 seconds,
corroborating the earlier approximately 153-second estimate. The measured span
from the first empty-node OS sample to the final after-delete sample was
921.20 seconds, already longer than the old 900-second owner. This is a bounded
sample-to-sample measurement, not an invented whole-workflow duration. The
isolated 1,200-second TypeScript owner completed without changing production,
per-activation, compilation, control, proof, quota or cleanup limits.

All six printed guide blocks passed in 80.12 seconds, including successful
deletion and clean shutdown. The node and peer were reaped; all three held
HTTP requests physically closed, with eight authorized requests and none
unexpected. Independent verification matched 2,339 captured input files to
that exact Git head and found identical source and tool-binary identities
before and after execution. The qualification receipt SHA-256 is
`d65d968b0cc3b8284ca61dfc6fcc21544dc0c05cf75a2e2a2aae8a0f1b06a9ef`.
Explicit source capture remains non-hermetic. This TypeScript success neither
resolves the separate Go failure below nor qualifies later reconciled PR heads.

The [combined-head Go run 35963178643](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35963178643)
at `a880cfd731f82194c36265886a65a1374d0313fb` failed the SDK service case:
nine of ten SDK tests passed in 130.53 seconds, and the enforced node and printed
guide were not reached. The [failed execution artifact](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35963178643/artifacts/10793745523)
retains all fourteen component builds and the original failure. Independent
verification matched 2,331 captured input files to that Git head; its CI merge
`6f8a00cea1b00540c67f7aed53585308818518a6` has the same
`a5c2f893805d286d9726d2a27d64172872ed9c7d` tree. The failed-stage receipt
SHA-256 is `23dd8c0a68137749cd153f7a7a80796ea692cd35c9a36fe8395899aa60ab2c91`.
This is explicit-input evidence for a failed attempt, not a source-archive or
complete qualification claim.

The first permitted child's terminal observation was `DependencyFailed` /
`Unavailable` at `Queued`, with zero guest fuel, memory and effects and 438
receipt microseconds. The parent then trapped with `stack-overflow` after
7.095 seconds. The child had already passed resolution/admission; this is not
the earlier stale-load rejection at `Resolved`. This direct SDK fixture also
uses a fixed signing clock, so elapsed wall time alone cannot establish a
five-second signing-lease expiry. Its private child failure reason was not
captured, and no root cause is asserted.

The test-only diagnostic follow-up retains at most 32 closed stage/code/reason
records before guest lowering, with explicit incomplete/unclassified states.
It does not retain private error text or payloads, retry work, or alter limits,
outcomes, consumption or owner lifetimes. Seven native fake-invoker regressions
passed, including original allocation identity, full/contended/poisoned
recording and dropped pending futures. Actual Linux SDK execution of this
observation-only change still requires new CI evidence; it is not a claimed
fix for the captured failure.

These integration corrections and subsequent squash-ancestry reconciliation
require a new full qualification. The earlier `7e670e06` attempt retained ten
passing SDK cases and a verified 4,090-file source archive, but was superseded
before final node/guide evidence; it is not another complete pass. The final PR
and issue receipt must identify the successfully qualified head and actual
merge tree. No earlier success automatically qualifies later source changes.

## Compiler and implementation decisions

The selected profile pins componentize-go 0.4.3 at
`148dba505f8c6c64ad84db777cfde5e34e25098b`, its bindings generator at
`4f9a02d74cec9257c14ba9b160fa787a3523fd0b`, Go 1.27.1 with the `wasiOnIdle`
async scheduler patch, and wasm-tools 1.254.0. The Linux compiler archive is
verified against `4b4fcbbab5b5b0a45433112aa51c64a54007b24f1efd05b67018ca2cf8633e2c`.
The exact reviewed Go module is included in every editable project; generated
imports and exports come from the authoritative staged WIT, twice, with exact
binding-drift rejection. Ordinary stock Go and TinyGo are not this profile.

The retained upstream probe compiles the current host ABI, including async
imports and exports. Its ordinary adapter imports ambient WASI; that result is
not deployable in LSF. The selected source overlay checks the exact runtime
preimages, keeps the maintained scheduler, and forwards clocks and entropy to
explicit LSF imports. The composed component is rejected if ambient WASI
imports remain. No GOROOT or shared module cache is edited. The compiler probe
checks UTF-8, embedded NUL, full-width signed/unsigned integers, records, lists,
results, traps and fresh state. It is not signed admission evidence.

The SDK exposes eight typed capability families with explicit affine owners.
Aliases share consumed/borrowed state; pending owners cannot be reused, and
terminal calls invalidate them even on failure. No finalizer, retry worker or
background drain substitutes for explicit release. The fixed four-goroutine
recovery example exercises scheduler/channel reclamation under whole-Store
fuel, wall-time, memory and cancellation bounds. Dormant deployments retain no
guest heap or Go process. Read the SDK's
[supported-language boundary](../../sdk/go-guest/README.md#ownership-concurrency-and-cancellation)
before choosing dependencies or host APIs.
The pinned upstream resource constructors install Go cleanup callbacks. The
SDK build removes those exact generated blocks, retains explicit `Drop`, and
rejects unknown shapes. Pure regression tests and the real resource ownership
suite must both pass for this adaptation; upstream GC-driven drops are not a
substitute for the documented activation cleanup contract.

## Retained implementation validation

[Run 35921398035](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35921398035),
PR head `7753d224080d5ff87cac89dc27ebb5744a4e77f0`, built all five standalone
projects and nine actual Go capability components. All ten admitted
provider/ownership cases passed in 153.52 seconds: buffered/streaming HTTP,
blobs, secrets, events, local services, randomness, metrics, signature checks
and cancellation cleanup. Its source-input receipt is
`sha256:b5d59fa0879afc90ca4157e483f411acae41897e714dd27fedfac4334cea014f`.
These successful stages are not complete ticket qualification.

That run reached enforced admission, rejected the unsigned package, published
the signed packages and deployed four of the initial five. Preparing the fifth
deployment exceeded the finite admission clock lease while checking several
distinct packages. The retained control result is explicitly uncertain;
read-only receipt lookup remained unknown and complete audit pages were
retained. No mutation was retried or treated as successful. Authenticated
managed preparation now renews the same finite durable lease before each
distinct package read. Each read still occurs once, failures publish nothing,
and all grant/currentness checks remain at commit. Invocation, recovery,
historical replay and cache reads do not receive this control-only renewal.
A deterministic regression covers renewal failure before the second read,
unchanged durable bytes, no retry and cancellation of the private preparation.

Earlier failed runs remain evidence: [35918139823](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35918139823)
passed nine SDK cases but the child service lacked its own exact-principal
clock grants. The fixture now scopes those grants to the child publication and
service identity, without changing production authorization. Other retained
attempts identified runtime entropy input charges, secret-owner pending counts,
and cold child compilation exceeding an explicitly short test budget. Correct
ownership accounting and finite profile budgets replaced those assumptions.

The new node/guide run and measured startup, active memory, cache, dormancy and
cleanup results remain required. Only `qualification.json` with `status:
passed`, complete node/guide receipts and successful exact-head CI may approve
merge. `BUILD-COMPLETE.json` and `SDK-BUILD.json` alone cannot do so.

[Run 35924210302](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35924210302),
head `d4582fe3681574fb05daca945c79094cf90c8a45`, passed the expanded full-width
ABI probe and rebuilt every component, but passed only nine SDK cases. Its
second local-service call trapped while a half-budget child reservation was
outstanding. The retained snapshot is not evidence of eight calls or 5 billion
executed guest instructions; reserved child capacity is included in it. The
next gate includes synchronized clock/native fuel accounting and bounded
caller/child start and terminal diagnostics. This failed attempt cannot qualify
the later source changes.

[Run 35926554561](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35926554561),
head `64fac09c3306f307416c3d59ce412c83c9917739`, passed the expanded ABI probe
and all ten real SDK tests, including explicit resource cleanup and the warm
declared-error child call after synchronized clock charging. Its fifth node
deployment still failed closed with `admission-clock-lease-uncovered`: the
binding inheritance pass rereads full packages after metadata compilation,
and had not received the control-only renewal authority. The next correction
covers that pass, explicit binding reloads and local-provider reads, without
changing the finite lease, the compilation deadline or the commit fences.
Three real-package regressions cover failure at every renewal, unchanged
durable state, per-compilation package deduplication, cancelled preparation,
historical replay and policy revocation. Restored bindings do not renew trust.
This retained failure still does not qualify the complete node or guide path.

Qualification now passes its captured packaging and contract binaries into
the SDK builder as a required pair; standalone SDK builds retain their normal
build command. Rebuilding those tools with a different Cargo feature set
during qualification changes their bytes, even from the same sources, and is
not permitted. The final integrity stage retains before/after source and
binary identities and rejects any difference. An initial local-service fixture
correction published synthetic load before each new top-level request. The
later integrated correction above covers nested admission after a cold parent
as well; production freshness limits remain unchanged.

[Run 35929606980](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35929606980),
head `54772d797e6d47732deb170a031b9ddf1f07dc91`, passed the expanded ABI probe,
built all fourteen components and passed all ten real SDK cases in 151.39
seconds. The finite binding-lease correction passed the former fifth-deploy
boundary. The node then retained three samples each at five and nine dormant
deployments, with one process, seven threads, one TCP listener, no UDP listener
and zero active or service-resident owners. These observations do not establish
the required seventeen-deployment population, invocation or guide results.

The next dormant deployment failed closed with `signature-stale-proof`, a
known unsuccessful outcome recorded in the durable audit. The isolated demo
policy allowed only 60 seconds of proof freshness, contradicting the guide's
existing 30-minute experiment and 1800-second signatures. Both demo proof ages
now use the same finite 1800-second window; production defaults, revocation,
currentness, five-second control leases and signature expiry are unchanged.
Two registered cryptographic tests retain success after 60 seconds, rejection
at exact signature expiry and independent publisher/builder proof-age limits.
No operation retry or automatic proof refresh hides this retained failure.
The separate source artifact for the failed run was independently matched to
all 4,039 archived Git blobs at that head; it cannot qualify the later fix.

[Run 35932372496](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35932372496),
head `7c13b9a7e19794b6d46d2a71f74871a08ea1b86c`, passed all ten SDK cases in
151.63 seconds, all three dormant populations, all twelve tutorial calls,
explicit trap and memory-exhaustion classification, and fresh-state recovery.
The next four-goroutine scheduling loop returned `guest-trap` at 717,764,529
fuel rather than exhausting its 1-billion-fuel budget. Its retained receipt
does not expose the private host or Wasm failure cause; eighteen node results
and sixteen resource samples are partial evidence, not completed qualification.

A separate diagnostic ran that exact recovery component in fresh Wasmtime
Stores: it returned `1`, consumed its full native fuel, then returned `1` in a
new Store. The spinning channel loop made about 30,432 monotonic-clock imports.
That shows the fixture mixed fuel exhaustion with repeated authorized host
operations; it does not prove which private condition caused the node failure.
The corrected fixture completes one rendezvous with each of four real workers,
leaves their channels and stacks blocked, and exhausts fuel in the main
goroutine. The real-node budget, grants, `resource-exhausted` expectation and
subsequent fresh-state checks are unchanged. An early compiler diagnostic now
requires genuine `OutOfFuel`, fresh state and at most 4,096 calls per runtime
capability for this bounded fixture. It explicitly does not claim admission.
Complete node, guide and final-integrity evidence remains required.

## Reproduction and delivery boundary

Install the exact Linux tools from the beginner guide, then use a fresh output
directory outside the checkout:

```sh
python3 tools/qualify_go_capsules.py --output /tmp/my-fresh-go-qualification
```

The gate retains source inventories, actual build observations, generated
bindings, package inspection, all owner tests, signed enforced-node receipts,
27 completed node cases, active/idle resource samples, 5/9/17 dormant
populations and the six unchanged printed Bash steps. Failed attempts retain
`QUALIFICATION-FAILED.json` and bounded logs. CI also archives its exact source
and command-contract input. Final PR and issue comments bind the successful
receipt to the exact Git source and merged revision.

This is finite single-node experimental qualification, not 100k-scale sizing,
throughput, transactional state, clustering, a complete transitive SBOM or a
hermetic/reproducible build claim. Source repository labels are operator
assertions. All six authoring tickets, the Phase 3 gate and human newcomer
review remain separate; runtime release publication stays on hold pending
explicit maintainer approval.
