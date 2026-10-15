# C# stackful canonical async exports

The `dotnet-native-aot-stackful-async-exports-v1` compiler bridge preserves the
ordinary synchronous C# implementation interface while giving declared WIT
`async` exports a real canonical async lift. This is a prerequisite candidate
for [default HttpClient qualification](https://github.com/KirilsTurkins/latent-service-fabric/issues/693).
Managed Task scheduling, cancellation, sibling progress and full default-client
execution remain independently unqualified under
[#746](https://github.com/KirilsTurkins/latent-service-fabric/issues/746).

Previously, the binding generator projected every async implementation kind to
synchronous C# and restored the original WIT metadata. An actual encoder control
shows that an ordinary core export still receives a synchronous canonical lift
with that metadata. A potentially blocking canonical wait or synchronous
subtask cancellation can then trap before the task returns. Metadata comparison
alone does not prove a suspendable implementation.

The compiler now generates the original stackful bindings and a second export
projection with wit-bindgen 0.62.0. Imported implementation kinds remain
synchronous, including imports whose indirect parameters the pinned C# async
generator cannot implement. The complete reparsed projection must equal the
expected graph. Only the selected export interop classes are replaced; public
C# interfaces and ordinary application methods remain the original baseline.
The bridge retains the pinned argument/result marshalling, executes the actual
application method, calls canonical `task.return`, then releases result pins.
It creates no completed Task, application executor or new invocation budget.
An unexpected stackless callback traps instead of inventing completion.

The admitted runtime/HTTP adapters select async canonical lifts for their
potentially blocking WASI poll, pollable block and HTTP stream read/flush
implementations. Closed streams retain their synchronous implementation. The
helper and adapter sources are captured SDK/recipe inputs, and the actual
isolated NativeAOT binding invocation uses the captured neighboring helper
without resolving application modules through Python's import path.

Twelve source regressions cover retained marshalling/pin order, unchanged C#
interfaces, real export names, imported versus exported kinds and fail-closed
generator/source drift. Separate actual pinned generator controls cover scalar,
string, result-less, inline-interface and large-import-parameter contracts. A
host SDK 10.0.303 Roslyn syntax/type control completed with zero warnings/errors;
it does not replace the pinned Linux NativeAOT 10.0.100 compiler. Synthetic
component encoder controls validate the async callback/task-return calling
shape; they are not emitted managed applications.

Normal adapter compilation, signed/admitted ordinary HttpClient execution,
pending cancellation/disposal, closing/drain, physical ownership and the full
shared HTTP matrix remain required execution gates. The original failed managed
execution and interrupted build attempts remain retained separately. No ticket
closure, production enablement or complete CLR/ThreadPool support follows from
these source and encoder controls.
