# Java guest authoring qualification

Status: complete source- and binary-matched qualification passed at the revision
below. Merge still requires all CI checks on the final PR head, including any
subsequent documentation or contract-boundary change.
This report tracks [#548](https://github.com/KirilsTurkins/latent-service-fabric/issues/548).
The [authoring guide](../component-development/java-authoring.md) and
[SDK reference](../../sdk/java-guest/README.md) describe the implemented path.

## Passing source and execution evidence

The [complete Linux run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35927188206)
qualified source revision
[`9a47a088430d2219bf79efe79bdfc77104254957`](https://github.com/KirilsTurkins/latent-service-fabric/tree/9a47a088430d2219bf79efe79bdfc77104254957).
The CI checkout merge revision is
`cc674871e021b6d6492c71149edbacf1e6c5b331`. Retained
[execution evidence](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35927188206/artifacts/10780336228)
and the
[source archive](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35927188206/artifacts/10778893388)
are linked before issue closure. Independent Git-blob verification matched all
2350 captured runtime, SDK, WIT, schema, helper and guide files to the source
revision; every one of the 3496 archived source files also matches its Git blob.
The source archive digest is
`sha256:4d3c990493bd464121038bb509a01504bde0c34b6c10a9fed0cfcc1a332ba3ba`.
The before/after source identities and all five executable identities
are equal; no SDK-stage rebuild replaces the initially qualified tools.

| Evidence | Passed coverage |
| --- | --- |
| Actual Java compiler and ABI | Maintained TeaVM C backend, real Java exceptions/GC, full-width s64 MIN/MAX and u64 MAX, UTF-8/NUL, empty/populated record lists and async host suspension. |
| Editable standalone projects | Five outside-checkout projects: greeting, word-count, shipping, HTTP status and recovery. |
| Typed capability ownership | Nine actual Java components and all ten signed-package SDK tests covering all eight current interfaces. |
| Enforced node | 29 recorded invocations, declared errors, denied/allowed authority, deadline, cancellation, disconnect, traps, exhaustion and fresh-state recovery. |
| Resource observations | 26 samples, dormant populations of 5/9/17, bounded cache, suspended active calls and physical cleanup. |
| Printed newcomer commands | All six Bash blocks passed, with typed answers and clean node shutdown. |

The evidence identities are:

```text
runtime:      sha256:10dce1b18602b9bafb477056aa26a0eede9848048f9a6287d7bf6c55b96b4354
qualification: sha256:bf5400bbb32c4630f1b65ddd80f90736a1cc08c30155effe32da3a59ecaa46c0
printed guide: sha256:ea6aedccb76f98d1e8120d3527c74175bd9e182be7fcb9cb53b81c8315996487
bindings:     sha256:12d3b88496c490feea8959d1abae2d6de4c8064967bb1eeef73f2c9a72f8b234
```

These measurements remain attributed to that immutable baseline. A final-head
CI rerun and its source/execution artifact links belong in the delivery PR and
issue; a later report edit does not retroactively change the tested revision.

## Qualification contract

`tools/qualify_java_capsules.py` captures exact runtime, SDK, WIT, schema, helper
and printed-guide identities. It builds five outside-checkout projects from
their Java sources, nine separate capability components, and runs the actual
signed package/production admission fixture tests. No prebuilt Wasm or C fixture
may stand in for application Java. Build observations require the separately
approved `https://latent.dev/build/java-capsule/v1` recipe; Rust/C/echo approvals
do not authorize Java. Tools and source inputs are rechecked after execution.

The closed node workflow tests valid/invalid greeting, word-count and shipping
calls; denied and allowed HTTP; cancellation, deadline and disconnect with a real
held peer; caught/uncaught Java exceptions, managed heap exhaustion, aggregate
host memory exhaustion and fuel exhaustion; and fresh successful calls after
every failure. Runtime clocks are denied before explicit grants. Provider-idle
receipts and OS samples check cleanup. Populations of 5, 9 and 17 dormant
deployments test bounded node process/thread/listener behavior, and the cache
remains globally bounded rather than a Java heap/process per service.

The guide gate executes all six printed Bash blocks, verifies both typed answers
and cleanly stops its node. Failure leaves `QUALIFICATION-FAILED.json`, build
markers, bounded compiler/runtime diagnostics and the failed stage. Passing
diagnostic probes or CI without these receipts is not completion.

## Runtime accounting

`engine.javaGuest` enables a profile distinct in compiler, prepared-cache and AOT
compatibility identity. Wasm GC instructions remain disabled. Wasm exception
support uses a fixed 4 MiB non-moving exception GC reservation, fully charged
before Store creation; linear memory consumes the remainder of the same budget.
TeaVM's fixed 4 MiB managed heap, C allocations and canonical buffers are inside
linear memory. No per-service JVM or guest host thread is installed. The default
engine does not gain Java features or larger operator limits. Pooling and mixed
renderer installation are rejected for this profile.

The evidence distinguishes static reservation charge from actual resident RSS.
Node receipts retain process-tree RSS/high-water RSS, thread counts, provider ownership,
prepared-cache metrics, cold/warm timing and invocation memory/fuel receipts.
Those observations are measured evidence, not a general claim about every Java
class-library program. The selected examples use 64 MiB aggregate memory,
1 billion fuel and an explicit 120-second cold-invocation ceiling; the larger
SDK fixture grant is 10 billion fuel. Caller deadlines and cancellation remain
authoritative. The host build uses `.cargo/managed-guest.toml` to optimize only
the compiler implementation libraries while keeping debug assertions and
checked arithmetic. No production timeout or memory default is raised.

## Measured supported profile

Node readiness took **57.12 ms**. Component sizes include the reachable TeaVM
runtime; no separate JVM image is deployed. The table distinguishes receipt
wall time from whole CLI round-trip time, in milliseconds. The first word-count,
shipping, recovery and HTTP executions include cold compilation. Greeting had
already been prepared by the denied-runtime-grant control, so its first
successful call is not labelled cold.

| Component | Component bytes | First successful receipt / CLI ms | Warm receipt / CLI ms | Charged peak bytes |
| --- | ---: | ---: | ---: | ---: |
| Greeting | 487057 | 6.413 / 21.246 | 6.856 / 20.059 | 9109504 |
| Word-count | 480938 | 732.618 / 747.737 | 5.049 / 19.874 | 9109504 |
| Shipping | 427184 | 565.180 / 578.771 | 5.536 / 19.749 | 9109504 |
| Recovery | 355707 | 370.681 / 386.833 | 5.184 / 20.005 | 9043968 |
| HTTP status | 566016 | 1045.380 / 1060.906 | 9.925 / 24.972 | 9175040 |

The nine capability components range from 428820 bytes (callee) to 815330 bytes
(local-service caller): blob 780050, events 549700, buffered HTTP 578268,
metrics 527091, random 536933, secrets 515458 and streaming HTTP 747370 bytes.
Each package is built from its own maintained Java sources and is admitted with
its exact declared imports; a generic prebuilt fixture does not stand in for it.

### Dormant, active and retained shared memory

All samples below have **one node process and one listener**. Dormant rows each
represent three samples. The thread count does not grow with deployments and
there are no prepared cache entries before first invocation.

| Phase | Dormant deployments | Process-tree RSS bytes | Threads | Prepared entries |
| --- | ---: | ---: | ---: | ---: |
| Empty node | 0 | 56217600 | 8 | 0 |
| Dormant | 5 | 62070784 | 8 | 0 |
| Dormant | 9 | 62078976 | 8 | 0 |
| Dormant | 17 | 62210048 | 7 | 0 |
| After tutorials | 17 | 82960384 | 8 | 2 |
| Suspended cancellation call | 17 | 93298688 | 8 | 2 |
| After cancellation | 17 | 86495232 | 8 | 2 |
| Suspended disconnected call | 17 | 93339648 | 8 | 2 |
| After disconnect | 17 | 86528000 | 8 | 2 |
| After deleting all deployments | 0 | 86532096 | 8 | 2 |

The final bounded shared cache retains two entries, 1237832 compiled-image
bytes and 921723 source bytes, with 26 hits, five misses and three evictions.
RSS need not return to the initial baseline: shared compiler/cache data and
allocator retention remain in the node. These non-atomic process-tree samples
are RSS/high-water RSS, not PSS, and do not isolate allocator-retained bytes.
The ownership counters, not a claim of zero RSS, prove that dormant services
and retired activations retain no Store, instance, execution cell or Java heap.

### Failure taxonomy and physical reclamation

An uncaught Java exception and managed 4 MiB heap exhaustion are `guest-trap`,
with respective receipt times 6.055 and 7.149 ms. The fuel test consumes exactly
1000000000 fuel and returns `resource-exhausted` in 1779.093 ms. An aggregate
4 MiB memory grant cannot cover the exception reservation plus linear memory;
it is rejected as `resource-exhausted` before Store creation, with zero charged
fuel/peak guest memory and a 0.891 ms receipt. Fresh successful calls follow each
case; static guest state is not reused.

The 100 ms deadline returns `deadline-exceeded` in a 102.324 ms receipt
(116.891 ms CLI round trip). The explicitly cancelled call returns `cancelled`
in a 52.342 ms receipt (67.813 ms round trip). These are invocation times, not
isolated cancellation-to-reclamation latency measurements. The disconnected
caller deliberately receives no terminal receipt; the held peer closes, idle
counters return, and a subsequent invocation succeeds.

The held HTTP peer records eight authorized requests, no unexpected request,
and all three held requests physically closed. Node shutdown reports zero
live Stores, host states, instances, temporary buffers, execution-cell
reservations, quota owners, IO/provider owners and provider connections, with
the compiler worker and epoch helper joined. Both node and peer are reaped.

## Support and delivery boundary

The maintained TeaVM 0.15.0 C/WASI-SDK 29 path compiles actual Java sources.
Its supported language/class-library/dependency profile and explicit ownership
rules are documented in the SDK reference. Application JARs/build scripts,
reflection-based dynamic loading, JNI and host threads are not admitted inputs.
Native Rust tests also cover explicit engine policy, aggregate exception
reservation plus linear-memory accounting, separate Java source-bound builder
authorization and native/ledger clock-fuel synchronization.

The generator rejects unsupported contracts before compiling Java. Empty
records are not valid component values. Owned or borrowed resources, including
nested resources, cannot appear in the node's public JSON RPC parameters or
results; resources on imported capabilities remain supported and exercised.
This early rejection matches production signature validation, rather than
changing resource semantics or promising an uncallable export.

The isolated demo's publisher and builder proof ages now match its existing
finite 1800-second signature window. The earlier fast passing runs did not
expose a one-minute proof-age limit that contradicted the guide's 30-minute
interactive session. Real cryptographic regressions check both roles after
61, 900 and 1799 seconds, reject currentness and re-verification at signature
expiry, and independently preserve a deliberately lowered one-minute ceiling.
Production defaults, revocation checks and admission-currentness fences are
unchanged. The corrected policy and printed guide require a new exact-head run.

Runtime release publication remains on HOLD; issue #345 still requires human
newcomer review independently of automated guide execution. Exact final-head
CI and artifact verification are mandatory before squash-admin merge into
`development`. This ticket does not authorize a development-to-release promotion.

## Retained failed attempts

The [first full signed-SDK attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35913215300)
built all five projects and nine actual Java components. It rejected the SDK
fixture's engine configuration because that fixture omitted cooperative fuel
yielding; the production node already used a finite yield interval. The fixture
now matches the production interval of 10000 fuel, without changing defaults.

The [next attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35915999660)
passed five of ten real SDK tests. It exposed canonical empty strings/lists
whose non-null sentinel owns no C allocation. A retained actual Java random
component reproduced an invalid `free` of that sentinel; the corrected bridge
only clears/frees non-empty owned allocations. Empty string execution is now an
early regression case. Local service also exposed the difference between cold
component compilation and an accidental five-second fixture deadline. The
documented Java profile explicitly allows 120 seconds; caller cancellation and
100 ms deadline tests remain unchanged.

The [nine-of-ten attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35918990021)
at `f794609ee71b1c79015eaea5e672e10d5b8216a9` proves the sentinel correction:
both blob tests, buffered HTTP, randomness, events, metrics, secrets, streaming,
and exact signed-package admission passed. Its sole failure was local service.
The fixture's clock policy authorized the original user but not the child
service principal deliberately derived by production admission. The corrected
fixture uses distinct exact caller and child identities, services and
publications within one tenant, and retains bounded child-terminal diagnostics.
It does not inherit user authority, add a wildcard, or change production policy.

These attempts and their bounded diagnostics remain failed evidence, not
substitutes for the required complete node/guide qualification.

An additional [contract-boundary probe](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35921295847)
demonstrated that the WIT parser/C generator accepts an empty-record declaration
but the component validator rejects it with `record type must have at least one
field`. Empty records now fail explicitly before Java compilation, and the
generator validates its real component-type metadata before invoking TeaVM.
The executable regression uses valid empty and populated lists of a non-empty
record. This unsupported contract is not silently translated into another type.

The [first enforced-node attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35922138058)
at `8f3c11f9df5d129b2aaaecc5847495f3a19e888a` passed all ten real SDK tests,
including local service, in 30.90 seconds. Five initial deployments, dormant
populations of 5/9/17, all twelve typed tutorial calls, Java exception cleanup,
managed heap exhaustion and fresh subsequent invocations passed. Fuel exhaustion
then exposed a shared clock-accounting defect: provider calls charged the common
ledger without reducing the native Store counter, so final accounting overran
the grant by the clock charges and masked the fuel interruption as a trap.
Both clock imports now checkpoint and synchronize the native counter at the
host boundary. The finite fuel budget and required resource-exhausted outcome
remain unchanged. A real two-clock/infinite-loop regression checks exact guest
plus host accounting and fresh reuse with and without cooperative fuel yielding.
At that revision, the remainder of the node workflow and printed guide were
unqualified; the complete corrected run linked above subsequently passed.

The [complete execution attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35924966518)
at `b4da8d288c3b2d127f47450dca80a68d5e8df089` passed all ten SDK tests in
30.71 seconds, all 29 recorded node invocations, dormant/active observations,
physical cleanup, and all six printed guide blocks. The node and held HTTP peer
were cleanly reaped; fuel exhaustion remained resource exhaustion, and fresh
calls succeeded after every failure. The overall attempt nevertheless failed
its final binary-identity guard. The SDK builder's narrower Cargo package set
changed feature unification and replaced both packaging executables after they
were recorded. The corrected qualifier supplies its exact prebuilt tools to the
SDK stage; standalone SDK builds may still build their own tools. Both stages
retain and compare the original and final binary identities, with explicit
failure diagnostics and regression tests. These passing execution receipts do
not override the failed overall integrity check. The later fully source- and
binary-matched qualification linked above passed the unchanged guard.
