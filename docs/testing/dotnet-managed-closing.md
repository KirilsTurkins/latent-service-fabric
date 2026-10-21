# Managed accepted-work closing

`dotnet-managed-accepted-work-v1` is a compiler-selected derivation for an
asynchronous component root that explicitly declares the activation runtime,
monotonic clock, wall clock and random interfaces. Other selections retain their
existing adapter worlds. This change requires a new guest compilation; an older
component or native receipt does not qualify it.

The compiler authenticates the complete original WASI CoreLib and copies its
finite registry into a private derived assembly. The derivation changes eighteen
enumerated Task, builder, queue and context producer bodies, in addition to the
five existing finite-wait bodies. It preserves the other 44,723 original method
bodies and all original assembly references. A generated receipt binds every
original producer body, the derived assembly, captured tool inputs and the actual
NativeAOT reference. The System.Net.Http derivation retains the actual discarded
`SendContent` Task; its original transport and request-future error channel stay
authoritative.

An accepted scheduled Task is registered before scheduling. An unwrap promise and
its actual inner Task share that logical owner until the real promise completes.
The original async builder retains its actual state-machine box before registering
an await continuation. Required continuations of that flow use a bounded private
table; they do not each become a second independently scheduled native Task.
Actual queue insertion has separate admission and failure rollback. Queue removal
does not settle its still-running Task. Unobserved completed failures retain a
Result owner and the original exception object until join reports the failure.

The private owner key is added to the original immutable ExecutionContext map.
The original application AsyncLocal entries and notification arrays remain in
use. The adapter receives the current still-live Task token, so original timer
and I/O owner registration remains parent-bound during Closing. The four-function
compiler-private WIT edge is consumed during composition and cannot become a
public capability, grant or application-selected import.

Before the original canonical task return, the root closes independent admission
and joins actual accepted Tasks and required continuations through the original
dispatcher. Existing live children may create bounded descendants. Work with no
eligible original pollable, hook or queued item fails closed as unproven
quiescence. Physical I/O drain follows managed join. Only then are the root and
metadata owners settled. Dropping a Store or aborting an Exchange is not a
successful managed join.

`tools/dotnet_managed_work_controls.py` runs fifteen actual CLR Task controls using
the production registry source with explicitly separate test dispatcher and ledger
ports. They cover native admission refusal, real unwrap-inner completion, queue
rollback, continuation failure before acceptance, queue removal, required async
work, live descendants during Closing, independent-work refusal, original fault
identity, observed faults, bounded metadata and opaque or pre-install work.
These controls do not qualify the production WASI dispatcher, context lowering or
native ledger. The separate metadata derivation and genuine wit-bindgen C#
compilation controls also do not execute a guest.

The owning signed mixed-content campaign preserves its twenty result oracles,
ten independent-tenant outcomes and original resource ceilings. Its revised
positive accepted-child premise requires an actual Closing observation while the
body remains pending. The child sends a checkpoint, receives the controller's
released 4,109-byte body and awaits a `finally` checkpoint before root success.
The peer must record pending body, child checkpoint, gate release, completed body
and finally checkpoint in that order. This adds two charged contacts: 26 mixed
contacts and 8 tenant contacts. The original two simultaneous requests, eight
outbound requests per invocation, fuel, memory and deadlines remain unchanged.

The original `9af3b431816650679c85f3da6ee4f5ad28a8473e` run and its `fc20` node-only
continuation remain failures. Their request-limit and accepted-child traps do not
become passing evidence from this source change. The selected production bridge
and all mandatory mixed outcomes require fresh hosted execution. No post-retired
Store callback, unrestricted managed thread, full timer saturation or whole
Task-runtime qualification is claimed here.
