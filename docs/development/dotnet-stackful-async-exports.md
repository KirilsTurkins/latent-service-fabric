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
with that metadata. This distinction alone does not prove the cause or cure of
the retained blocking trap: Wasmtime 48.0.6 bases blocking permission on the
function type's async flag, independently of the canonical lift option. Nested
WASI I/O functions and resource destructors also have their own task boundaries.
Metadata comparison alone does not prove a complete managed runtime port.

The compiler now generates the original stackful bindings and a second export
projection with wit-bindgen 0.62.0. Imported implementation kinds remain
synchronous, including imports whose indirect parameters the pinned C# async
generator cannot implement. The complete reparsed projection must equal the
expected graph. Selected export interop classes are replaced; public
C# interfaces and ordinary application methods remain the original baseline.
The bridge retains the pinned argument/result marshalling, executes the actual
application method, calls canonical `task.return`, then releases result pins.
It retains the original raw core parameters and moves the generator's argument
lifting into the synchronous helper. This also handles the pinned generator's
malformed async record-parameter declarations without inventing a C# type mapping.
The original completion tail must match exactly, and generated calls must have
balanced parentheses with no injected statements or comments.
It creates no completed Task, application executor or new invocation budget.
An unexpected stackless callback traps instead of inventing completion.

The admitted runtime/HTTP adapters select async canonical lifts for their
potentially blocking WASI poll, pollable block and HTTP stream read/flush
implementations. These four private function types are projected on both the
raw NativeAOT import and matching adapter export. Closed stream implementations
still return immediately using their synchronous calling convention. The
helper and adapter sources are captured SDK/recipe inputs, and the actual
isolated NativeAOT binding invocation uses the captured neighboring helper
without resolving application modules through Python's import path.

The first hosted attempt failed during adapter encoding before any application
execution: an async canonical export had a synchronous WASI function type.
That rejected attempt is retained in
[run 38825558809](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38825558809).
The compiler now matches the complete actual function shapes, unbundles core
modules, projects only those four internal types, and uses normal wasm-tools
encoding and validation. It clones shared function types so `read` remains
synchronous when `blocking-read` changes. Every original core-module payload
must remain byte-for-byte identical; the complete resulting WIT graph must equal
the explicitly expected projection. Public application WIT, other imports,
resource identities, source and compiler cache inputs remain unchanged.
The original compiler component and its graph remain separately retained.

The pinned printer's `--name-unnamed` output places identifiers before a type
export's name, which its own text parser rejects. The finite reconstruction
moves only those identifiers into their item signatures. The final graph and
core-byte comparisons independently guard this syntax normalization. No code is
disassembled, no validator check is skipped, and no engine blocking rule changes.
Seven source controls and an actual finite synthetic component projection check
these boundaries. The normal independent Smoke probe uses the same owner before
its existing composition steps; their commands and limits remain intact.

The [next hosted attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38833208836)
compiled the normal adapters, then reached the real NativeAOT transaction
component. It exposed a reconstruction error: real component export aliases
must retain their identifier before the export string, whereas type-signature
exports need the syntax normalization above. The traversal now repairs only
exports within component/instance type definitions. Actual pinned parser,
validator and complete-graph roundtrip controls cover both forms. The failed
attempt remains retained; fresh NativeAOT qualification is still required.

The [following hosted attempt](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38837686118)
reached C# generation for the original authored aggregate and rejected its
multiline record argument. Actual pinned generation reproduced both that
shape and the malformed async helper parameter declaration. The bridge now
retains the exact raw core parameter list and argument-lifting prelude together.
The original three-operation aggregate, complete graph checks, generated-output
drift check, unchanged application and SDK facades pass host Roslyn 10.0.303
compilation with zero warnings/errors. This is a generator/type control;
NativeAOT and signed node execution remain separate required checks.

The [Smoke probe build](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38850941693)
then exposed a missing support dependency: asynchronous nested-list result
lowering needs the pinned `MemoryHelper.AlignStackPtr`, which the synchronous
projection does not always emit. The bridge retains that exact pure helper
beside its original return-area class without copying the generator's Task
runtime. Changed helper bodies and changed placement are rejected. The complete
original Smoke application and selected generated sources compile under host
Roslyn 10.0.303 with zero warnings/errors; native execution is still pending.

Seventeen source regressions cover retained marshalling/pin order, unchanged C#
interfaces, real export names, imported versus exported kinds and fail-closed
generator/source drift. Separate actual pinned generator controls cover scalar,
string, result-less, inline-interface and large-import-parameter contracts. A
host SDK 10.0.303 Roslyn syntax/type control completed with zero warnings/errors;
it does not replace the pinned Linux NativeAOT 10.0.100 compiler. Synthetic
component encoder controls validate the async callback/task-return calling
shape; they are not emitted managed applications.

The maintained `qualify_dotnet_standard_http.py` gate creates an independent
captured project with `new HttpClient()` and a declared async component root.
It parses JSON inside the guest, preserves the default client timeout and
tests normal/error status, Unicode domain values, POST bytes, truncation,
oversize, malformed JSON, forbidden headers, early body disposal, cancellation
while headers/body are pending, uncertain mutation, destination denial and a
fresh static counter. No handler, transport, proxy, resolver or Task pump is
injected into application code. The signed node checks every activation's
physical provider owners, cleanup slots, quotas and topology before proceeding;
the controlled peer verifies contact/mutation counts and no secondary contact.
The compiler is bounded to 900 seconds and the node/peer to 300 seconds under a
1200 second enclosing deadline. It reuses the unchanged five native products
from the successful ordinary authoring qualification; it does not rebuild or
instrument a host. The existing hosted job retains all prior commands, its
75 minute limit and failed inputs. This gate has been added but has not yet
completed native execution.

Normal adapter compilation, signed/admitted ordinary HttpClient execution,
pending cancellation/disposal, closing/drain, physical ownership and the full
shared HTTP matrix remain required execution gates. The original failed managed
execution and interrupted build attempts remain retained separately. No ticket
closure, production enablement or complete CLR/ThreadPool support follows from
these source and encoder controls.
The separate `dotnet-owned-retirement-v1` candidate addresses the synchronous
destructor boundary. `Exchange.abort` and pending timer destruction transfer the
exact pinned future, resources, original owner and quota slot into a bounded
activation-local retirement queue. The destructor does not drop that future.
The compiler adds one parameterless async private drain import, invokes it
before the original root task-return while result pins remain live, and consumes
it through the selected runtime adapter. Public source WIT remains unchanged;
actual encoder comparisons require its complete graph to survive adding and
removing only that private edge. The final composed component must retain no
additional host authority or public retirement export.
Applications without the activation interface return their original source
before any retirement compiler query. A synchronous root does not select the
private edge merely because it imports the activation interface.

The private async drain drops each retained future under its original canonical
task owner before releasing its resources and quota slot. The pinned generator's
future destructor performs the real canonical terminal cancellation protocol;
the queue does not manufacture completion. Remaining accepted canonical work
causes a closed failure. Queue capacity remains 32, and ownership is retained
until draining. This is not a CLR sibling-task scheduler or a proof that every
managed task has retired.

Five source controls cover the exact private interface, unchanged public graph
boundary, real task-return/pin ordering and rejection of ambiguous interface
identities, plus unchanged unselected-profile behavior. Actual pinned encoder and C# generator controls pass, including
generator drift verification. Rust binding generation passes for all three
adapter worlds. A separate host SDK 10.0.303 compilation of the actual generated
bindings with the unchanged standard HttpClient fixture reports zero warnings
and errors. These are codec, generator and host type checks; the normal Linux
NativeAOT build, signed pending cancellation/disposal matrix and physical
retirement observations remain required before this candidate is qualified.

The [first actual retirement build](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/38857166351/job/116831132298)
compiled NativeAOT, composed the runtime and passed final component validation,
then rejected the private owner import as undeclared authority. The exact
multi-facet composer had connected only WASI imports. It now receives the
compiler's authenticated retirement selection, checks both exact parameterless
async `drain` signatures with no result or types, and connects that private
import exactly once to the primary runtime. Additional facets cannot provide
or duplicate it. The final private-import/export and undeclared-authority
checks remain in place. Six new composition controls retain all eleven earlier
cases and guards, including byte-identical unselected composition and the
existing denial controls. The following actual build on 3cd580ed passed the selected private composition,
validation and signing, then the first HTTP JSON invocation trapped without a
decoded result. Both original failures remain retained; the new joined Task
wait candidate still requires fresh signed pending/disposal and retirement
qualification.

## Joined Task wait candidate

The pinned WASI CoreLib has a concrete additional boundary: direct
`TaskAwaiter.GetResult()` enters `Task.InternalWaitCore` for a pending Task,
and that original method throws `PlatformNotSupportedException` on WASI.
The original first signed HTTP JSON calls still trapped without a decoded
result. The exact CoreLib path explains a source-level failure candidate;
the retained public trap alone does not prove its original managed exception.

The selected `dotnet-stackful-task-wait-v1` derivation requires declared clock,
typed HTTP and activation imports plus an authenticated stackful async export.
It changes a private copy of the exact locked CoreLib. An infinite wait with a
noncancellable wait token runs the original WASI work queue until that actual
Task completes. The original event loop still performs its real WASI readiness
polls. The helper saves and restores the previous main Task in `finally`,
limits nested waits to 32, and leaves fault/cancellation propagation to the
original TaskAwaiter. Its private callback enters the unchanged dispatcher
through CoreLib's `ExecutionContext.RunInternal(Default, callback, actualTask)`.
That original primitive restores the raw caller ExecutionContext, including
suppressed flow, SynchronizationContext, culture and AsyncLocal notifications
before the join returns or throws. This matters because Dispatch deliberately
clears both current-thread context fields. Finite waits and waits with a cancellable wait token
retain the original unsupported path. This is a bounded joined-wait candidate,
not complete Task, ThreadPool or detached-work compatibility.

The idle-driver extension gives a private cancellation source only to
`TimerQueue.SetNextTimer` registrations. When the original `Timer.ActiveCount`
is zero, it invalidates the driver epoch, resets scheduled-driver state, and
cancels/disposes that source through the original owned-pollable path. Original
Task identity and epoch guard stale continuations and rearming after callbacks.
Queued user callbacks, `s_scheduledTimersToFire`, live logical timers, exchanges
and foreign registrations remain untouched. Flow suppression covers only the
new registration and is restored before the original continuation registration.
The existing async retirement queue still destroys the original future and
resources; remaining-owner assertions remain. No resolved-pollable cache cleanup
is added. Earlier managed/native receipts retain their original source
identities; the new repair's locked NativeAOT and signed 14-case ownership and
retirement qualification is pending.

The transformer authenticates the complete CoreLib and the original wait,
event-loop, dispatch, RunInternal and context-restoration IL. After writing, it
verifies all 44,742 unaffected original methods, the three explicitly transformed
TimerQueue bodies, the complete original wait remainder behind the selected
prologue, all eight added method bodies and the five added field identities.
Normal compilation must bind exactly one derived CoreLib in both the ILC
reference list and its actual response file. Original packages, captured sources,
derived bytes and targets are rechecked; unselected profiles keep their original
CoreLib.

The earlier [managed tool control](../testing/evidence/dotnet-task-wait-source-2026-10-16.json)
rewrote the actual pinned assembly twice deterministically and rejected a
whole-assembly mutation before output. It used host SDK 10.0.303 and is not
locked Linux NativeAOT 10.0.100 or guest execution. A separate host CoreLib
reference control exercises normal, faulted, cancelled, nested and throwing
callbacks with suppressed and ordinary flow, culture, custom synchronization
contexts and AsyncLocal change notifications. Both unwrapped negative cases
lose caller state as expected. All 12 cases run on owned host threads; this
does not execute the pinned WASI CoreLib or qualify its runtime behavior.
Eleven additional compiler controls
cover profile selection, source/target/product drift and exact reference and
receipt binding. The unchanged 14-case signed HTTP gate, pending cancellation,
physical retirement, budget/readiness behavior and the wider #746 runtime
contract remain required before claiming runtime compatibility.
