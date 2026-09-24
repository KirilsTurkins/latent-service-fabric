# C# capsule qualification

This is developer execution evidence for #549, separate from the beginner
[C# authoring guide](../component-development/dotnet-authoring.md). It does not
authorize a release or replace human newcomer review #345. The complete finite
qualification and its clean-source repeat passed at the sources recorded below.
PR #557 was squash/admin merged into `development` after all eight exact-head
workflows and 24 PR check rows passed. Ticket #549 is closed with all thirteen
criteria satisfied. Later shared-runtime regression failures remain separate
retained evidence and do not authorize merging an unqualified follow-up.

## Delivered source and evidence

The final reviewed head `67763cdc122f270733d75639a6aa4eb9e4aaaa13` and actual
development squash `8f08f7a95dbd68aebc525120645a27dc5ab85e14` have identical
tree `9a63049d798845f70eeb1344b7a39ad0e131bb36`. The complete
[.NET qualification 35981797862](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35981797862)
and [broad CI 35981798865](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35981798865)
passed together with all language and security cross-checks before the
[PR #557 merge](https://github.com/KirilsTurkins/latent-service-fabric/pull/557).
Source/execution evidence and the final gate audit were posted before closing
[#549](https://github.com/KirilsTurkins/latent-service-fabric/issues/549).

[Execution artifact 10800703843](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35981797862/artifacts/10800703843)
matches 2,367 Git inputs, including exactly 45 SDK sources and no generated SDK
files; before/after source and all five host-binary identities match. All fifteen
builds, both NativeAOT probes, seven owner tests, ten actual SDK cases (96.06
seconds), five secret assertions, 27 node outcomes, 24 resource samples and six
printed Bash steps (29.01 seconds) passed. Seventeen node deployments and the
guide deployment were each deleted once. Node, compiler, cleanup and HTTP-peer
owners were cleanly reclaimed and joined. Qualification SHA-256 is
`517332dd681f340e535018c7257625f24ab8de6a7028706c3bece267b9dc276f`.

The separate [source archive 10799987822](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35981797862/artifacts/10799987822)
matches 4,129 selected Git files and modes (40,127,766 bytes), SHA-256
`5a1057186817fa6b10a3c2bb062c74abae38e34d1f5ede528093d07a16fa424d`.
Broad CI's [discovery/execution artifact 10801848873](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35981798865/artifacts/10801848873)
lists 175 registered targets and 2,812 active cases; those are discovery counts,
not a claim that discovery itself executes tests. Its actual execution log
separately confirms all twenty added readiness/timer/ownership regressions,
17 local-service cases and seven closed-diagnostic integration cases.

The later development Go run and final Go candidate exposed two additional
currentness-contention boundaries despite the earlier green shared head. Their
[retained failure analysis](go-capsule-qualification.md#current-integration-gate-and-retained-contention-failures)
keeps the compiler-worker and active clock failures distinct. Neither is a
reclassification of the older .NET shipping trap, whose private cause was not
captured. Human newcomer review #345 and runtime release HOLD remain separate.

## Supported experiment

The compiler host is Linux x86-64 with .NET SDK 10.0.100, Componentize.NET SDK
and WitBindgen 0.8.0-preview00011, NativeAOT LLVM 10.0.0-rc.1.26306.1,
WASI SDK 29.0, wit-bindgen 0.62.0 and wasm-tools 1.254.0. The maintained project
enables trimming, invariant globalization, single-threaded execution and no
application dependencies or MSBuild overrides. The six NuGet packages are
locked by exact version and verified content hash. Signed NuGet content is
verified with the pinned SDK's package reader, not a raw signed-ZIP digest.

The independent source capture includes handwritten C#, authoritative WIT,
vendored SDK, generator and runtime inputs. Compiler, runtime, reference-pack,
NuGet and WASI input inventories are compared before and after each build.
Generated bindings are regenerated independently and compared with the actual
NativeAOT compiler's bindings. Build observations deliberately remain
operator-asserted, non-hermetic, dependency-incomplete and not reproducibility
claims. Production package validation compares the compiled contract with WIT.

The closed runtime retains only the explicitly declared monotonic-clock import
needed by GC. It grants no ambient files, sockets, wall time or entropy. Each
activation owns its managed heap and task objects; dormant deployments have no
CLR process, OS thread, listener, event loop, execution cell or guest heap.
The supported guest ceiling is 128 MiB, one billion fuel and 120 seconds for a
cold invocation. Deliberately multi-operation SDK tests use ten billion fuel.
These are finite experiment bounds, not throughput or production sizing claims.

## Qualification history and current gate

The readiness correction delivered with PR #557 uses an explicitly supplied activation-owned
timer for sealed, read-only currentness observations. Only the exact closed
`admission-authority-busy` result can wait, within one shared five-second window
and the unchanged original activation deadline and cancellation. Original grants
are rechecked before the single pool acquisition; no compilation, fetch, mutation
or invocation is replayed. Legacy callers remain executor-neutral and immediately
fail closed. That delivered correction left compiler-worker, materialization and
execution-start checks unchanged. The later worker/clock correction is recorded
separately in the [Go qualification report](go-capsule-qualification.md#current-integration-gate-and-retained-contention-failures)
and [package-admission contract](../reference/package-admission.md); its new
source requires separate exact-head qualification.

An actual signed-catalog fence reproduces a deterministic failing warm-readiness
case without the opt-in wait and passes with it. Twelve new Linux regressions and
five existing admission tests passed; all eight executor and 76 node unit tests
also passed, including eight new forwarding, cancellation, deadline, transport
and timer-ownership cases. These are local regression results, not final-head
SDK qualification, and do not recover the uncaptured causes of older failures.

Integrated diagnostic head `41a07273209d06a8ac96fd33291f30527cbdc30e` passed
the complete [.NET run 35975059698](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35975059698).
Artifact `10798651998` matches all 2,356 captured Git inputs, including exactly
45 SDK sources and no generated SDK files. Before/after source and host-binary
identities match. Both NativeAOT probes, seven ownership cases, ten actual SDK
cases (96.00 seconds), five project builds, 27 node invocations, 24 resource
samples and all six printed guide blocks (28.58 seconds) passed. The node and
HTTP peer shut down cleanly; the formerly failing shipping-warm case passed.
Qualification SHA-256 is
`1b2ec8b49550c47ed205f3b2677cd47c0477e98f522fcae6034855dcf50395e0`.
The runtime identity covers 2,195 files and 13,789,339 bytes, digest
`206658948c2af4b70ada916e2ef9ae08dca48bc4ed8804b84a74a9b05393b8cc`.
Source artifact `10798195278` separately matches 4,118 selected Git files and
modes (40,063,650 bytes), archive SHA-256
`b884c8861d14ddd2e96250b5047d6211bbdc3694b8204602d3a26183fdf7de09`.
CI merge `93697116495399656c5208a77f61f912028c903d` and the reviewed head
share tree `881d28ef6866fd7f26b55b33c562782884c8d65d`.

That head is **not qualified for merge**: its
[Go cross-check 35975059660](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35975059660)
failed after nine passing SDK cases. Artifact `10797374406` matches 2,341 Git
inputs and the same runtime identity. The first answer and declared-error child
cases passed; the next answer failed during queued preparation, before
materialization. The closed diagnostic identifies
`ChildFailure / Unavailable / AdmissionAuthorityBusy`, with zero child fuel and
guest memory. The parent subsequently entered its panic path on the unexpected
child result. Neither the exact readiness checkpoint nor competing fence owner
is captured; `Queued` alone does not exclude synchronous compiler-worker checks.
No node or guide qualification was reached. This is distinct from the older
generic parent trap below, whose private cause remains unknown. No invocation
was retried to clear this gate.

The same head's [TypeScript cross-check 35975059688](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35975059688)
passed completely. Artifact `10798549332` matches 2,349 Git inputs and unchanged
before/after source and tool identities: ten SDK cases (894.98 seconds), 27 node
invocations, 24 resource samples and six guide blocks (81.35 seconds), with
clean/reaped owners. The 17 deletions each succeeded once; first-to-final OS
sampling spanned 936.55 seconds within the existing 1,200-second owner.
Qualification SHA-256 is
`c0a47122bd01852460ebcd15769bd84f3e914395c1b54dea90382a992a45bff6`.
This cross-check does not substitute for the final TypeScript PR's exact-head CI
or clear the separate Go failure.

The [broad run 35975060016](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35975060016)
also passed every selected job. Discovery artifact `10799870975` records 175
registered targets and 2,792 active cases; discovery is not an execution count.
Its SHA-256 is
`6e36d6dbaa472d48ddd45d570cb646a43593944083551d428c4f3a6f4c04b22d`.
The execution log separately confirms all 17 local-service and seven diagnostic
integration cases, plus the ten new closed-currentness cases. Java, C, Rust and
security cross-checks passed too. Seven successful workflows do not clear the
failed Go workflow or authorize merging this head.

The diagnostic commits repair a gap: host-import traps now preserve
only a validated reason from the existing `admission.currentness` vocabulary.
The original constructor must have exactly one recognized detail and field,
with the matching platform code and retryability. The node independently checks
the runtime-trap/code/reason combination before forwarding that existing detail.
Unknown shapes, raw messages, arbitrary metadata and backtraces are not copied.
The outer `GuestTrap`, non-retryability, consumption, stop/memory precedence and
public CLI vocabulary remain unchanged. This adds no logging, locks, retries,
authority or budget allowance. Twenty-eight focused host/node/CLI Rust cases and
24 CI inventory/lane/coverage Python cases passed; exact-head Linux qualification
is still required. This observation repair does not establish or fix the private
causes of the retained failures below.

The preceding diagnostic head `65e7390d074f58e914ae7155375eed343c2838cd`
did not repeat the complete pass: [.NET run 35968038565](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35968038565)
failed in the enforced-node workflow. Artifact `10795870530` retains all ten
passing SDK cases (94.44 seconds), then twelve node invocation receipts, ten
resource samples and dormant populations 5/9/17. The final
`authoring-shipping-warm` invocation returned known/dispatched `guest-trap` in
25.06 milliseconds, reporting 50,780,412 fuel and 53,018,624 peak guest-memory
bytes. The public receipt does not retain its private trap reason. The peer was
alive before failure cleanup and was closed/reaped; complete node cleanup and
the printed guide are not qualified. No invocation was retried.

All 2,350 captured pre-execution Git inputs match that head, with no generated
SDK files. Final after-execution identities were not captured. Failed marker
SHA-256 is `1221f97efe9f84df778f06ad814d3c58c68dd5c8f826dffc197e055ce8862ff5`;
the node failure receipt is
`a462ba6da9737639c236755e88fe4ba64d5e3349e4b82962097b7571670bb6a9`.
Source artifact `10795176008` separately matches all 4,112 selected Git blobs
and modes (40,022,327 bytes), archive SHA-256
`be6fcd52b956c4f71e6d15fc118df8165c862a87b41016a67b9f1a64ac5c8363`.
CI merge `e88dd260c9c52b711773f653da3295b0c827fba1` and the reviewed head
share tree `6b383152e5d3b93fc0af177c38a11997e9fa1e2b`.

The same head's [Go cross-check 35968038588](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35968038588)
also failed. Artifact `10795094294` retains nine passing SDK cases and one failed
service case (135.65 seconds). Unlike the preceding a880 failure, the first
permitted nested answer succeeded in 13.8306 seconds. The next declared-error
case trapped in the parent with `guest-runtime-error` after 4.8635 milliseconds
while one child remained outstanding. The closed child diagnostic has no records
and is not incomplete; it does not identify a parent-side host/runtime failure.
Aggregate consumption includes the outstanding half-budget child reservation:
eight child calls, about five billion fuel and 35,061,760 memory bytes do not
establish eight dispatches. Only one new child start was observed. The private
parent cause remains unknown, and node/guide execution was not reached. These
failed gates prevent delivery despite the earlier complete qualifications below.

The same head's [TypeScript cross-check 35968038564](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35968038564)
passed completely. Artifact `10796213887` matches all 2,343 captured Git inputs,
with unchanged before/after source and tool identities: ten SDK cases, 27 node
invocations, 24 resource samples and all six printed guide blocks passed, with
clean node/peer shutdown. All 17 deletions succeeded once; the measured
first-to-final OS sample span was 931.85 seconds within the bounded 1,200-second
owner. Qualification SHA-256 is
`ec617f6e622b7ab3f8fcbebeeb83ec1035b88038425c7522efd6228d86d18d1b`.
[Broad CI 35968038765](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35968038765)
also passed. Discovery artifact `10796891041` retains 2,775 active cases; the
actual Linux log confirms all 17 local-service and seven new closed-diagnostic
regressions passed. Neither passing workflow clears the Go or .NET failures.

A bounded local Linux Go experiment retained one passing unchanged-source
attempt and four passing diagnostic processes, with no closed error events.
It did not reproduce the CI failure or establish its private cause. The
observation-only experimental source is identified separately from this Git
head; these local attempts do not qualify the PR or justify a production policy
or budget change.

A separate, single local Linux .NET workflow using the same observation-only
source completed all 27 node invocations, 24 samples and 123 control attempts in
96.3 seconds. It retained unchanged source, component and binary identities and
clean/reaped node and peer owners. The diagnostic captured no host-import error;
six uncorrelated runtime markers accompanied the workflow's deliberate fault and
cancellation cases. This experiment does not identify the original shipping-warm
trap, qualify the later Git head or replace its complete CI execution above.

The integrated head `a880cfd731f82194c36265886a65a1374d0313fb` passed the
complete [.NET run 35963178615](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35963178615).
Artifact `10793826456` independently matches 2,346 captured Git inputs and zero
generated SDK inputs. Five standalone builds, all ten SDK cases (97.38 seconds),
27 signed-node invocations, 24 resource observations and dormant populations
5/9/17 passed. The HTTP peer saw eight authorized requests, zero unexpected
requests and all three held operations physically closed. Node/peer shutdown
was clean. All six printed guide blocks passed in 27.85 seconds. A single
15 ms audit-idle observation had all required counters zero; the one deletion
received durable acknowledgment 10, and the retained catalog contains zero
deployments, object generations and publication pins.

Before/after source and execution-tool inventories match. Runtime identity is
`sha256:ce7ae39f77472a059e8a76139a070bafcfa20aa4edd452e04dc447300e64c005`
(2,185 files, 13,727,494 bytes); qualification marker identity is
`sha256:f02064a0a69c3f27a007f1c094bcd530f276c65cd46009686b39aaed47d77f3e`.
Source artifact `10793237246` matches all 4,108 selected Git blobs and executable
modes (39,985,713 bytes), archive SHA-256
`ff92d1ceb52391c89a81735cf3900c802edbbaa93c1ab6392718819925b0f13a`.
CI merge `6f8a00cea1b00540c67f7aed53585308818518a6` and the reviewed head share
tree `a5c2f893805d286d9726d2a27d64172872ed9c7d`; the merge parents are the
development documentation squash `417ed363` and the reviewed `a880cfd7`.

The same head passed the complete
[TypeScript cross-check 35963178639](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35963178639).
Artifact `10794941119` matches all 2,339 captured Git inputs, with unchanged
before/after source and execution-tool inventories. All ten SDK cases passed
in 883.43 seconds, followed by 27 node invocations, 24 resource observations,
the 5/9/17 dormant populations and all six printed guide blocks (80.12 seconds).
The HTTP peer recorded eight authorized requests, zero unexpected requests and
all three held operations physically closed; node shutdown was clean. All 17
deployment deletions succeeded once in 150.48 seconds. The actual first-to-final
OS resource-sample span was 921.20 seconds, independently establishing that the
old 900-second owner was insufficient for this finite workload. This successful
execution qualifies the bounded 1,200-second fixture correction at this source,
not the final TypeScript-specific PR head or an earlier failed run.

[Broad CI 35963178726](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35963178726)
also passed. Artifact `10794656924` retains the discovered 2,768 active cases
and actual execution of all 17 local-service cases, the three slow-preparation
regressions, the real 32 KiB audit-writer drain and CLI counter projection tests.
Rust, C, Java and security workflows passed as well. Website checks do not
replace the separate human newcomer review #345 or lift the release hold.

That head is not merge-ready: its
[Go cross-check 35963178643](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35963178643)
failed before signed-node or guide execution. Artifact `10793745523` retains
nine passing SDK cases and one failed nested-service case (130.53 seconds total).
The first permitted child stopped at `Queued` with `DependencyFailed/Unavailable`,
zero fuel/memory/effects and 438 microseconds of wall time; its parent failed
the expected-result assertion after 7.095 seconds. The private child rejection
detail was not retained, so the cause remains unknown. This differs from the
earlier `Resolved` stale-load failure. The fixture uses a fixed supply-chain
clock; real elapsed time alone does not establish an expired lease.

The next candidate adds test-only diagnostics before child errors are lowered
to guest values. It retains at most 32 fixed stage/code/reason records, never
raw messages, paths, tokens or payloads. Unknown shapes remain unclassified;
overflow, contention or poisoned observation storage explicitly marks the
record incomplete. The original start, future, outcome and owners pass through
once without copying payloads, changing authority or retrying work. Seven native
fake-invoker regressions cover the closed shapes, malformed values, redaction,
unchanged success/error forwarding, bounded storage and pending-owner drop.
These diagnostics improve observation; they do not establish or fix the
unrecovered private cause. Fresh exact-source runtime qualification is required.

The integrated head `9f51c60cdd686eb23aab5408f5dde75b4e7f7d09` passed
[run 35942901339](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35942901339).
Artifact `10785948026` matches 2,346 captured Git inputs with no generated SDK
outputs. All ten SDK cases passed in 95.82 seconds, followed by 27 signed-node
invocations, 24 resource observations, dormant populations 5/9/17 and clean
node/HTTP-peer shutdown. All eight peer requests were authorized, none was
unexpected and all three held operations closed. The six printed guide blocks
passed in 28.47 seconds. Audit readiness took one 15 ms observation with every
required counter zero; the guide's single deletion received a durable audit
acknowledgment and the retained catalog has zero deployments.

The before/after source and execution-tool inventories match. Runtime source
identity is `sha256:b12a96b6e49b9ad36ae3326c35df5a19bc3930a30ce48c51ec51f41de5933653`
(2,185 files, 13,727,514 bytes); qualification marker identity is
`sha256:06140e5617cfc8f8117a519577bfb2ead26796f2291aaeb15932c4732c00c0c1`.
The separate source archive matches all 4,105 selected Git blobs and modes,
SHA-256 `e8f959828303f35dd1cefd3ed3de884e9552d78984718d413a5d74d6559fa7ee`.
The CI merge `b8fbb53c0d72072c40b65286a2a3210885eb53b8` and reviewed head
share tree `e6c317a0a28305291411ebab7966ac1521f54ea3`.

That head also passed broad repository CI and the Rust, C, Java, Go and security
workflows, but its TypeScript cross-check
[run 35942901312](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35942901312)
failed, so that head was not merge-ready. Artifact `10786577160` retains ten passing
SDK cases (872.12 seconds), the 5/9/17 dormant populations, 20 invocation
receipts and 18 resource samples. The first allowed HTTP invocation returned
the declared `connection-failed` result with a known outcome after 47.92 seconds;
HTTP cancellation, subsequent cleanup and the guide were not qualified.
The test peer has a 300-second listener lifetime, but the preceding sequential
control and invocation receipts total at least 726.85 seconds. This establishes
a fixture lifetime mismatch with the existing 900-second authoring owner.
The prior peer exit was not captured, so its exact private failure cause is not
claimed recovered. No invocation or uncertain mutation was retried. A corrected
fixture and every final-head CI gate remain required for delivery.

The correction ties the peer to an absolute, finite owner deadline, including
startup, request and held-socket work; ordinary peer use keeps its 300-second
default. Only TypeScript's end-to-end qualification allowance becomes 1,200
seconds. The retained first HTTP result already ends at least 774.77 seconds
into the old 900-second allowance. Its 26 remaining package inspections are
estimated to need about 153 seconds from the measured 5.9-second TypeScript
inspection cost and independently observed Go deletion curve; this is not a
measured TypeScript cleanup result. The 20-minute harness bound leaves finite
room to execute the unchanged case set. Other language allowances, 120-second
activations, the 30-second binding-compile deadline, control-call bounds,
1,800-second demo proofs, resource quotas and authorization remain unchanged.
Failed runs now retain bounded peer exit/reaping diagnostics. New exact-source
execution remains required; no earlier failed run is reclassified as a pass.

[Run 35934374519](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35934374519)
repeated the complete qualification successfully at
`f8fff6bb1f0e854e6caff3a577848bd87a12a883`. Artifact `10782987086` contains all ten
SDK cases, 27 signed-node invocations, 24 resource observations, the 5/9/17 dormant
populations and all six printed Bash steps. The node and HTTP peer shut down
cleanly, all three held HTTP operations closed and no unexpected requests occurred.
Independent Git comparison verified 2,341 captured inputs, including exactly the
tracked SDK sources: zero generated build or Python-cache outputs were included.
The source and execution-tool inventories remained unchanged before and after
qualification. The runtime digest is
`sha256:5e68470fa3a4985748fe90586981b8c2a88c126a59d8f799328327cdffa1bf15`
(2,181 files, 13,680,816 bytes), and the qualification marker digest is
`sha256:ac9f38c9d50e03533639125b568352e12c495c5234278b21212f6ff486b46eb0`.
The separate immutable archive matched all 4,084 expected Git blobs and modes,
SHA-256 `1f9b9dd15268c62bd0a6536be4dc87c9c5178566252c717876401922b586b03f`.

The same head's broader CI run `35934375368` separately failed the unchanged
small-WAT concurrent local-service acceptance case in the Phase 3 security matrix.
The existing wrapper retained only `command-exit`, not the assertion details;
that gate is not claimed green and its cause is not inferred from the successful
.NET qualification. Final integrated CI must pass it with bounded failure
diagnostics available.

The later integrated head `0c08d3f175f8cb58546208abe7f797cd27d6b61b`
failed [run 35938546333](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35938546333)
at the printed guide's final `deployment delete`. Artifact `10783703577`
retains the complete attempt. All ten SDK cases and the separate signed-node
workload passed: 27 invocations, 24 samples, the 5/9/17 dormant populations and
clean node/HTTP-peer teardown. The guide also built, published and deployed its
component and returned both expected greeting answers. Its deletion returned
public `resource-exhausted`, with `requestDispatched: true` and
`outcomeKnown: true`; no deletion was retried. The retained catalog still
contains the deployment at generation 2. The exit trap stopped the guide's node
cleanly, but that is not successful deployment cleanup or guide qualification.

No delete attempt appears in the seven retained audit records. The last two
records are the valid invocation's monotonic-clock grant/outcome observations,
immediately before the rejected cleanup. The guide configures eight audit queue
operations, which derive a 32 KiB byte allowance; each observation and a new
control reservation occupy 16 KiB of that allowance until physically released.
This supports audit-byte pressure as an explanation, but the private rejection
reason was not retained and is not claimed proven. The source archive matches
all 4,102 selected Git blobs and modes, SHA-256
`37b335092e4d1aac855669e92c7594c98f07cd3ca7128d123b908ae6cb70fed8`.
The failed attempt remains a failed gate regardless of earlier successful runs.

The guide now makes bounded read-only observations of audit ownership before
issuing its one deletion. Existing queued-byte, durable staging and recovery
state are exposed through matching server/CLI counters; missing, malformed,
closed or recovery-pending observations fail closed. The observation has a
five-second deadline, at most 32 reads and finite process/output cleanup bounds.
It neither reserves future capacity nor changes journal quotas, policy, leases
or deletion checks. Local tests cover these boundaries; the deterministic
two-observation/32 KiB journal regression and full guide still require Linux CI
at the new source. This correction is not a retroactive pass for the failed run.

The same integrated head's TypeScript cross-check also failed
[run 35938546318](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35938546318).
Artifact `10784514997` retains nine passing SDK cases and the failed nested-call
case. Its child stopped at `Resolved` with `Unavailable` and zero consumption;
the parent failed after 67.45 seconds. This test composition sampled its
synthetic healthy load only before the parent request, while normal admission
rejects samples older than 60 seconds. Stale child load is a supported inference,
not a recovered private rejection reason. The fixture now samples the same
healthy profile at every admission; production health sources, freshness limits,
quotas and invocation deadlines are unchanged. Deterministic real-WAT regressions
retain both the stale-child rejection and the fresh parent/child path, without
sleeping or retrying either admission. Linux execution remains required.

The separate TypeScript candidate's
[run 35938383435](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35938383435)
retained `admission-clock-lease-uncovered` in artifact `10784737181` after one
bounded deployment preparation took 6.18 seconds. The existing
authenticated control owner now renews its finite clock lease after successful
package inspection, before compiling the binding plan. Initial eligibility and
the existing final live-policy, proof-expiry, revocation and deadline checks
remain; startup/recovery receives no renewal authority. Registered real-package
tests advance a fake clock across that boundary and cover cancellation,
revoked/expired proofs and startup failure. These shared changes need successful
Linux CI at the new integrated source; they do not qualify the earlier failure.

The following first-success measurements remain tied to their original source,
not to the later integration head.

[Run 35932426366](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35932426366)
passed at `57fbc36690d9ccad65b6a18d2c49a4188e1ff061`. Artifact `10782416468`
retains five standalone builds, nine actual SDK builds, seven ownership checks,
all ten admitted SDK cases (78.33 seconds), 27 signed-node invocation receipts,
24 resource observations, 123 recorded control calls and all six printed Bash
steps (22.29 seconds). Typed results, secret alias zeroization and closed owners,
allowed/denied HTTP, trap, fuel/memory exhaustion, deadline, cancellation,
disconnect, fresh subsequent state and final deployment deletion passed.
The node and HTTP peer were reaped cleanly; all three held HTTP operations closed,
with no unexpected requests or remaining activation/provider/compiler owners.

The runtime source identity is
`sha256:f6ae16771985517c7a3acecb542f2ad98b9b9683f8663c6d3b466a87b20c6c2a`
(2,180 files, 13,671,845 bytes). Independent Git-blob comparison verified 2,340
runtime/SDK/WIT/schema/helper/guide inputs. The immutable source archive separately
matched all 4,083 expected files and executable modes (SHA-256
`f30b75bf8eaaf18a6cb6d7516334e6b8b275861cb4712e0b00615734879a4406`).
The qualification marker digest is
`sha256:41b2b076737de5a88d3dab2e1102f8102504df8d0f35c3f71ba69b3be6be6c0b`;
the source and tool inventories remained unchanged through node and guide execution.

The first receipt's SDK inventory also records 74 generated probe `bin`/`obj`
and Python-cache outputs (26,009,700 bytes). These are explicitly not Git source
inputs. The workflow now builds that diagnostic probe in its own temporary
directory and disables Python bytecode writes, so the final SDK source inventory
must match the reviewed tree exactly without an output exception.

Node startup measured 55.17 ms. Word-count and shipping cold requests took
2,927.95 and 2,914.49 ms; their warm repeats took 23.78 and 23.87 ms.
The first recorded greeting was already warm after the explicit runtime-grant
denial check and is not a cold-compilation measurement. Ordinary activations
peaked at 54,067,200 charged guest-memory bytes. The memory-exhaustion case
reached 121,765,888 bytes within the 128 MiB ceiling and the following fresh
invocation succeeded. The fuel-exhaustion receipt charged exactly one billion.

| Observation | Processes / threads / listeners | Node RSS bytes | Active cells / cache entries |
| --- | --- | --- | --- |
| Empty node | 1 / 8 / 1 | 56,139,776 | 0 / 0 |
| 5 dormant deployments | 1 / 7 / 1 | 67,682,304 | 0 / 0 |
| 9 dormant deployments | 1 / 7 / 1 | 67,686,400 | 0 / 0 |
| 17 dormant deployments | 1 / 7 / 1 | 67,686,400 | 0 / 0 |
| Held HTTP activation | 1 / 8 / 1 | 176,046,080 | 1 / 2 |
| After cancellation | 1 / 8 / 1 | 125,153,280 | 0 / 2 |
| After all deployment deletion | 1 / 7 / 1 | 125,169,664 | 0 / 2 |

Each dormant population has three settled samples, zero application-owned
resources and no active activation, quota or execution-cell ownership. Shared
compiled images remain bounded at two entries and one preparation; they are not
per-deployment heaps. RSS is a non-atomic process observation, not an allocator
release guarantee, and deleting deployments does not promise that RSS becomes
the initial baseline. Clean shutdown joined the fixed compiler/cleanup workers.

Standalone captured builds took 15.88–16.27 seconds including source inventories,
binding checks and packaging. The larger 5,050,538-byte diagnostic component
compiled in 13.79 seconds with maximum compiler RSS of 305,296 KiB; its separate
cold-backend probe prepared in 35.99 seconds. That diagnostic is distinct from
the managed node's cold/warm observations above. None is a throughput, 100k-scale
or arbitrary-.NET-application qualification.

## Retained earlier attempts

[Run 35919449058](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35919449058)
at `7a69352177fee84c2edf1d976fcd0e3523797aab` passed the initial actual-compiler
and clock/fresh-heap diagnostics, but its standalone builder incorrectly
compared raw signed archive bytes with NuGet's normalized content hash. The
locked content was not changed; verification now uses the signature-aware
reader supplied by the exact .NET SDK.

[Run 35921141813](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35921141813)
at `1e56de8cb573c81e057df839b42845bccc455dca` passed both NativeAOT backend
diagnostics and built the standalone greeting from its captured source. The
probe compiler took 6.57 seconds with 188,212 KiB maximum compiler RSS. Its
2,288,059-byte component prepared cold in 13.36 seconds; observed echo/wide
activations peaked at 54,067,200 guest linear-memory bytes. Those measurements
describe this probe and runner, not whole-node RSS or arbitrary C# applications.

That run failed closed during package inspection at the conservative component
reference-work limit. A bounded native diagnosis measured 1,304,239 conservative
reference visits but only 11,921 actual binary/type visits, 2,488 functions and
293,022 operators in the 2,292,496-byte greeting. Whole-instance alias summaries
account for the difference. Reference expansion now has an independent finite
2,097,152 ceiling; actual type/allocation work remains capped at 262,144 and
depth remains capped at 64. All 71 packaging unit tests and inspection of the
retained actual greeting pass locally. Linux qualification must still validate
the final source; this local inspection is not node execution evidence.

## Earlier SDK and node failures

[Run 35929987442](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35929987442)
at `c844116196341fdb373f3bcbca6a61499ed189a8` passed all ten admitted SDK
cases in 97.14 seconds, including the actual compiled secret alias-zeroization,
preserved-copy, repeated-disposal and use-after-close assertions. The nested
service returned successfully cold in 7.538 seconds and warm in about 16 ms.
Each caller/callee activation peaked at 54,067,200 charged guest-memory bytes;
the parent receipt includes 108,134,400 aggregate bytes. These are this runner's
observations, not throughput or whole-process RSS guarantees.

The enforced node reached dormant populations of 5 and 9 with one process,
seven threads, one listener and no active activation/cell ownership. Applying
`dormant-09` then failed closed with `signature-stale-proof`: the isolated demo
signer's 60-second proof age contradicted its 30-minute signed experiment.
Artifact `10780739918` preserves that failed run; the 17-deployment, invocation,
cleanup and printed-guide stages were not qualified by that attempt. The exact source archive
independently matched all 4,082 expected Git blobs (archive SHA-256
`da8aa0ff351fcb26809ecb699d7f7c3967f43f639f61674836b77d191c08dde4`).
The broad Rust gate also caught a shared test-module dependency, now corrected
by passing the explicit admission-memory ceiling from its caller. Its failed
CI is not treated as passing delivery evidence.

The isolated demo signer now aligns both proof-age ceilings with its existing
1,800-second signature lifetime. Real cryptographic regressions check positive
proofs at 61, 900 and 1,799 seconds, exact rejection at 1,800, and independent
enforcement of a shorter publisher or builder proof age. This does not change
production policy defaults, revocation/currentness enforcement or the finite
five-second durable clock lease. The successful full run above includes this
correction through the node and printed-guide stages.

[Rust regression run 35932426453](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35932426453)
at `57fbc36690d9ccad65b6a18d2c49a4188e1ff061` reached dormant populations
5, 9 and 17 and passed all four greeting invocations. The first word-count
invocation then failed closed with `admission-authority-busy`, a known outcome
before execution with zero fuel, memory and effects. Artifact `10782136500`
retains this attempt. The authority intentionally rejects currentness checks
while its fence is held; the qualification does not retry that request or relax
the fence. A new isolated final-head run must pass the complete regression.

[Run 35928271057](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35928271057)
at `79ef782ab9f3440baa10123a3581ed727c875c87` passed the expanded actual
NativeAOT probe, all five standalone and nine SDK builds, seven ownership
checks and eight of ten SDK runtime tests. The secret success/typed-error
diagnostic and actual secret/streaming cases passed. Artifact `10780656604`
retains two admission failures: the nested caller declared its required
256 MiB ceiling, but the signing fixture still advertised a 128 MiB runtime.
The fixture now uses the same explicit nested-service ceiling as the node
composition; ordinary package profiles remain at 128 MiB. No production
delegation rule or authority is widened. The successful full run above includes
the nested service and complete signed-node/printed-guide stages.

[Run 35926712630](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35926712630)
at `2a2e131d1a51971cfc24eb792fea5323240114f1` executed the actual full-width
and aggregate value cases successfully. Its declared-error probe returned the
correct typed error, but the test used a success-only assertion. Artifact
`10779557766` retains that harness failure. The assertion now checks the error
category and exact payload separately. A local diagnostic of that unchanged
compiled component also traced member lookup through `String.GetHashCode`
to the closed runtime's ambient-entropy denial. Reflection lookup is therefore
an explicit negative test, separate from supported library/task/GC checks.
The successful full run above also passes the following fresh invocations.

[Run 35922933562](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35922933562)
at `2dc9ed406cfb0975024b4454e749677d3d4b6f55` built all five standalone and
nine SDK components, passed six owner checks and seven of ten admitted SDK
cases. Artifact `10778646686` retains the failures. The streaming example
did not handle its expected typed denial; the nested service caller's 128 MiB
reservation could not fund the callee under the node's half-remaining-memory
delegation rule. Each NativeAOT activation measured about 54 MiB. Only that
nested caller now explicitly reserves 256 MiB; the callee and standalone
templates stay at 128 MiB, and production delegation is unchanged.

An actual retained secret component reproduced the third failure under the
native diagnostic. Its full backtrace identifies unsupported
`CryptographicOperations.ZeroMemory`; the later ambient-randomness trap came
from exception reporting, not the secret provider. Local owned bytes now use
non-elidable volatile zero stores with an additional alias-observation test.
The compiled SDK diagnostic checks success/disposal and all four typed errors.
The closed runtime still denies ambient entropy. The successful full Linux run
above covers these changes; the failed attempt remains a failure.

`tools/qualify_dotnet_capsules.py` must retain five standalone builds, nine
actual SDK builds, seven explicit disposable-owner/zeroization checks and all ten
admitted provider/ownership cases. The compiled probe also checks full-width
signed/unsigned values, UTF-8/NUL strings, options, nested record lists, declared
errors, rooted WIT exports after trimming, dynamic-code flags,
activation-local tasks and GC collection. A separate negative member-lookup
probe verifies that unsupported runtime reflection traps without ambient
hash-seed entropy, followed by fresh successful invocations. Compilation alone does not pass those
execution checks.

The signed real-node workflow must cover the three tutorials, allowed/denied
HTTP, errors, cancellation/disconnect, deadlines, trap/fuel/memory exhaustion,
fresh subsequent state and cleanup. Resource receipts must include startup,
active ownership, bounded shared caches and dormant populations of 5, 9 and 17.
The six printed Bash guide steps must execute unchanged. Each failed attempt
retains `QUALIFICATION-FAILED.json`; only the final `qualification.json` with
`status: passed`, source-bound receipts and exact-head PR CI approve delivery.

After installing the guide's pinned prerequisites, use a fresh directory:

```sh
python3 tools/qualify_dotnet_capsules.py --tools "$LSF_DOTNET_TOOLS" \
  --output "$(mktemp -d)/dotnet-authoring"
```

Final PR/issue evidence must identify the reviewed source and successful run.
This does not qualify 100k deployment scale, transactional state, clusters or
runtime release publication. Those gates and #345 remain separate.
