# Java guest authoring qualification

Status: implementation in progress; signed-node qualification is not yet passed.
This report tracks [#548](https://github.com/KirilsTurkins/latent-service-fabric/issues/548).
The [authoring guide](../component-development/java-authoring.md) and
[SDK reference](../../sdk/java-guest/README.md) describe the implemented path.

## Evidence required before completion

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
Node receipts retain process-tree RSS/PSS, thread counts, provider ownership,
prepared-cache metrics, cold/warm timing and invocation memory/fuel receipts.
Those observations are measured evidence, not a general claim about every Java
class-library program. Final component sizes, compilation and activation times
must be reported from the exact passing source revision below.

## Current verification boundary

The maintained TeaVM 0.15.0 C/WASI-SDK 29 path compiles actual Java sources.
Local generated-source checks cover all five project templates and nine SDK
fixtures. Native Rust tests cover explicit engine policy, aggregate exception
reservation plus linear-memory accounting, and separate Java source-bound
builder authorization. These checks do not replace the Linux node matrix.

The full artifact/source verification, measured result table and exact final
CI links are pending. Runtime release publication remains on HOLD; issue #345
still requires human newcomer review independently of automated guide execution.

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
