# Accepted late facility callbacks in Java and .NET

This finite programme supplements the existing joined-resource receipts for #681.
A callback that already entered must complete its supported resource, clock,
entropy and logging work after an ordinary cancellation/disposal request. The
root joins that work before the activation physically retires. This does not
claim callback execution after Store destruction, an asynchronous console flush
queue, native threads, or whole Java/.NET runtime qualification.

Java uses an ordinary one-shot `TimerTask`, two independent classpath streams
from an outside transitive JAR, and a monitor rendezvous. The root observes the
entered callback, requires `TimerTask.cancel()` to return false, cancels its
Timer, then releases the callback. The callback checks its separate ThreadLocal,
finishes both streams and immutable UTF-8/NUL/empty resources, reads monotonic
and wall clocks, draws eight SecureRandom bytes, closes the readers and emits
one synchronous PrintStream marker. The root joins its finally notification.

.NET uses an ordinary one-shot `Timer` and two manifest-resource streams from
an outside transitive package. Its entered callback requests its own
`DisposeAsync()` and requires the returned ValueTask to remain incomplete.
It finishes the resource/clock/RandomNumberGenerator work, emits one ordinary
Console marker, executes finally, and supplies the actual disposal Task to the
root. The root joins both the callback completion and that exact disposal Task.
AsyncLocal flows through the ordinary captured ExecutionContext.

Each language compiles one fresh outside project through normal reviewed
capture and an offline build, removes the original library inputs, then uses
normal neutral signing/admission for two separately authorized tenants. The
programme retains two missing-runtime pre-entry denials, a foreign credential
denial, two late callbacks and two fresh invocations in the same execution cell.
The invocation results encode the exact resource bytes and lifecycle conditions;
the host consumption must match exactly one ASCII completion record plus the
frozen host's correlated JSON envelope. All eighteen active provider counters
and the physical guest/cell/cleanup owners must retire before the next call.
Final deployment deletion, clean/reaped node shutdown and zero-contact peer
shutdown remain required.

The original 8-task, 2-executor, 8-queue, 16-wait, 8-timer, 8-result and
8-native-owner ceilings stay unchanged. Java retains 64 MiB, one-billion fuel
and 256 log bytes; .NET retains 128 MiB, one-billion fuel and 16,384 log bytes.
Every invocation keeps its original 120-second execution limit. The frozen
`6fd19eab2c224fc31481d03de5008de4d3e4429e` five-product tuple and all 134 source
materials are authenticated before and after use. Its historical compiled native
source is separate from the current compiler/SDK and observed consumer source.
The campaign builds no native host/engine or five-template SDK baseline.

Before the first invocation, each exact admitted tenant publication uses the
existing bounded PrepareRelease operation. Its setup-only wait is clipped by
the original node/controller deadline and returns `executionAuthorized:false`.
This separates cold compilation from the unchanged 120-second execution window;
it adds no grant and cannot alias another tenant's publication or cache entry.

Use the existing language resource workflow with only `late_facilities=true`.
That selector defaults to false; all earlier workflow commands and limits are
preserved. The new Java lane resolves pinned compiler configurations without an
extra greeting component; the .NET lane installs only the normal captured
compiler and current small adapters. Reference JDK/CLR controls execute the exact
ordinary library bodies, separately from signed guest evidence.

The reference JDK 25 and .NET 10 late/fresh paths passed separately. The
[Java signed observation](evidence/java-resource-late-signed-2026-10-21.json)
records actual run `39617980436`, job `119283767665`, artifact `12354221143`,
compiled from `df4f5628add1a9ba9b1562ee00353fad57e4f7d5`: two pre-entry denials
and four late/fresh calls passed, with six physical retirements, all eighteen
active provider counters zero, four exact 183-byte completion logs and a clean,
reaped node. Its component digest is
`sha256:c19d31b7cf9bdf2c6e2cc6901b3112e23802d5477aad8e17cc581d56f0278365`.

The sibling .NET run `39617997010`, job `119283819097`, artifact `12353339133`
completed and packaged its fresh component but failed before node execution:
the reader expected `runtime-logging` while the current compiler correctly
selected `runtime-managed-logging`. The first node-only continuation
`39623608654` also failed before signing: the command runner rejected a
fractional setup deadline. Both original failures remain retained without guest
credit. The correction floors the remaining setup time within its original
deadline; invocation and owner limits stay unchanged.

The [.NET signed observation](evidence/dotnet-resource-late-signed-2026-10-21.json)
records successful node-only run `39626040271`, job `119311438368`, artifact
`12355949645`, at consumer source `919ff6d022a334513500c3eebe75f025624d3c4b`.
It reuses the exact original 2,783,038-byte component
`sha256:8187d723f0c41b6232752a2a3e265cdbbde85b6dc6df7991af3d6489ae1e09b1`,
its `df4` compiler/package records, all 138 SDK files, 64 recipe files and the
historical `6fd` five products/134 materials. Two pre-entry denials and four
late/fresh calls passed, including two actual pending self-disposals, six
physical retirements, all eighteen active provider counters zero, four exact
183-byte completion logs and clean/reaped shutdown with zero peer contacts.
No AOT or native product was rebuilt for either reader/controller correction.

The explicit `replay_late_facilities=true`, `late_facilities=false` workflow
selector authenticates that one fixed original artifact and all original Git
preimages. It requires exact reviewed reader/workflow byte identities and retains
before/after package, SDK, native and source fences. Both original workflow jobs
skip only for that explicit selection. Existing joined receipts retain their
original source identities and explicit absence of late-facility qualification;
the two new observations supply that separate finite evidence.
