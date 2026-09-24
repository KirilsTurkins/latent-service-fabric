# Standalone Go capsule qualification

This is developer evidence for #547, separate from the beginner
[Go authoring guide](../component-development/go-authoring.md). Completion
requires the complete real-node and printed-guide gate at the final PR head.
No partial observation below authorizes a release or replaces human newcomer
review #345.

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
cleanup jobs. Shared compiler and cleanup workers were joined. Integration
adds a direct four-parked-application-goroutine assertion to the existing blob
cancellation/fresh-state fixture; that newer assertion and the integrated
source require a new complete exact-head qualification before merge.

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
binary identities and rejects any difference. The local-service fixture also
publishes a current synthetic load sample before each new request because it
has no node monitor; production freshness limits are unchanged.

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
