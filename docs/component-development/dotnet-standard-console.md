# Ordinary .NET Console logging

The source profile routes the unchanged BCL `Console` implementation through
`wasi:cli/stdout` and `stderr` at **0.2.6** to the existing
`latent:log/log@0.1.0` capability. Declare that exact log import in the application's
WIT world. The compiler selects a logging primary only when the NativeAOT output
actually imports stdout or stderr. The declaration does not install a provider,
create a binding or grant authority. The operator must do those separately.

The ordinary closed, activation and HTTP primary adapters each have a logging
variant. Each variant retains its original WASI resource family, quota and
readiness implementation; it does not compose a second incompatible stream
resource beside the HTTP adapter. Without the declaration, stdout and stderr
keep their existing closed behavior. Stdin, filesystem and secure entropy remain
closed. There is no application `Console.SetOut` callback, BCL assembly rewrite,
ambient output descriptor or implicit operating-system logger.

| Operation | Finite mapping |
| --- | --- |
| `Console.Write`, `WriteLine`, `Console.Out` | Original BCL formatting and encoding; stdout writes at `info` level |
| `Console.Error.Write`, `WriteLine` | Original BCL formatting and encoding; stderr writes at `error` level |
| `Console.OpenStandardOutput`, `OpenStandardError` | The same bounded WASI output streams |
| Complete UTF-8 bytes | One synchronous typed log call per complete nonempty write prefix, at most 256 bytes |
| Split UTF-8 code point | At most three unfinished bytes retained on that stream |
| Malformed bytes, failed permit or oversized raw write | Stream failure before invalid text is dispatched |
| Provider `false`, budget, invalid-field or unavailable error | Sticky stream failure; no silent success or automatic retry |
| WASI `flush` / blocking flush | Success only after every complete prefix was accepted by the current host sink and no partial UTF-8 remains |
| Drop/dispose | Original resource destruction; no implicit output worker or queued retry |

The stream participates in the original **64-resource** guest quota; error
resources use the same quota and remain charged until their actual destruction.
Its memory remains on the activation's ordinary Wasm memory ledger. A raw write
must follow `check-write` and fit the returned permit. Larger BCL writes can be
split by the unchanged BCL stream implementation. Empty writes do not dispatch.
Formatting, newline and encoder replacement behavior before WASI follow the BCL;
the adapter validates the bytes it actually receives. Raw overlapping operations
on one handle fail closed; this is not a new .NET worker or synchronization port.

No guest fields are supplied to the log capability. The existing host derives
tenant, service, activation and trace context and charges the original policy
and invocation log budget. Text that resembles metadata is still message text.
Host sink acceptance is not durable delivery to a remote exporter. Flush makes
no remote acknowledgment claim. Dropping an unfinished UTF-8 tail does not
invent a successful flush or a late write after the activation ends.

The pinned BCL [Unix Console stream](https://github.com/dotnet/runtimelab/blob/8449ba666dd991e495d8363d9852f18eb86a1aa1/src/libraries/System.Console/src/System/ConsolePal.Unix.ConsoleStream.cs)
checks disposal in `Flush`, then calls its
[base no-op implementation](https://github.com/dotnet/runtimelab/blob/8449ba666dd991e495d8363d9852f18eb86a1aa1/src/libraries/System.Console/src/System/IO/ConsoleStream.cs).
This port preserves that behavior. Ordinary `Console.Out.Flush` can flush the
BCL text encoder, but does not by itself prove that the canonical WASI flush
was called. The signed malformed-continuation case requires a write failure;
only the port reference directly checks an unfinished tail at canonical flush.
There is no claim that the unchanged raw Console stream adds a final UTF-8
validation or remote delivery acknowledgment at `Flush` or disposal.

## Qualification boundary

`tools/qualify_dotnet_standard_console.py` creates a developer-owned NuGet parent
and transitive child with an embedded UTF-8 resource, uses normal dependency
add/resolve/exact-review, removes the original library and feed, then compiles
the actual component offline. It reuses the identity-checked native tuple and
four unchanged companion builds from the ordinary .NET qualification only after
the prepared source inventory matches its recorded digest and the current .NET
qualification inputs exactly. It signs
the five-build release set and retains all original 27 node outcomes before
adding two missing-log-grant denials, three phase calls and twelve Console outcomes: eight ordinary
API/error cases plus trap/fuel and fresh-Store recovery. Each added completed
activation is followed by the existing physical-owner sample. The fuel case
uses twice the measured initializer fuel, strictly below the original ceiling;
it cannot fail merely because of an arbitrary budget below managed startup cost.

The unchanged 75-minute owning .NET workflow runs this campaign after its existing
default HttpClient and NuGet/resource campaigns. Those prior commands, budgets,
14 original HTTP cases and both 15-case synchronous/pre-cancellation programmes
remain intact. Artifacts retain source/build/recipe identities, exact decoded
results, policy, consumption, idle samples and clean shutdown.

The phase calls enter a separate class, read only the captured resource, then
perform one plain `Console.Write` before the unchanged original initializer and
eight cases. Only the write phase may consume log bytes. Caught failures return
closed exception-type labels without messages or stack traces, and still fail
the original positive result assertion; they cannot qualify a failed case.

Current local evidence comprises eleven Python source/protocol controls and eight
native reference tests of the actual port against a bounded fake log import.
The reference does not qualify WASI/BCL lowering or a signed component. The
[first actual NativeAOT campaign](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39277107487/job/118144257047)
compiled, signed and admitted the component, but its first initializer call
trapped before any log write (50,922,019 fuel; 54,132,736 peak memory bytes).
That result does not identify a cause within resource lookup, formatting or
Console startup. The additive phase calls and all original Console acceptance
cases still require successful signed execution.
Cross-tenant logging, default asynchronous workers, callback cancellation,
pending remote exporters and the complete six-language #681 matrix remain
separate acceptance work. This profile adds no scratch filesystem.
