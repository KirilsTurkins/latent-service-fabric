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

The local JDK 25 and .NET 10 reference late/fresh paths passed with exact result
strings and one-character completion output. Signed hosted execution of these
new paths is pending. Existing joined receipts retain their original explicit
absence of late-facility qualification.
