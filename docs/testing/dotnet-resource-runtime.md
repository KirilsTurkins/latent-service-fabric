# Managed resource callbacks and standard facilities

The separate [joined campaign](../../.github/workflows/dotnet-resource-runtime.yml)
uses two normally captured outside managed packages. The transitive package
embeds UTF-8/NUL, binary and empty data. Two independent standard assembly
resource streams remain live across genuine incomplete `Task.Run`/`WhenAll`
callbacks, `Task.Delay` and `AsyncLocal` context capture. Those callbacks use
ordinary `Stopwatch`, UTC time, cryptographic RNG and `Console` operations.
The application installs no scheduler, context, logger or entropy replacement.

One new hosted NativeAOT component is required. The ordinary current installer
prepares the pinned compiler and small WASI adapters; it does not rebuild
CoreLib from source, a native host, or the five guest templates. Existing
compiler-owned exact-preimage TaskWait, closed-filesystem and managed entropy
derivations remain mandatory, including their actual final ILC/linker bindings.
The original source77bf V7 native products retain their separate authenticated
compiled-source identity. No old build or qualification receipt is rewritten.

The selected profile retains eight tasks, two executors, eight queued items,
sixteen waits, eight timers, eight results and eight native owners. Explicit
per-tenant CLOCK/WALL/RANDOM/LOG/ACTIVATION declarations and grants are required;
HTTP is absent. Noncryptographic hash-seed byte authority is retained while the
ordinary secure RNG call must catch its exact cryptographic error before the
secure `u64-value` operation is granted under the same finite entropy budget.

Eleven joined calls cover completion, cleared timers, root trap, pending
cancellation/deadline, callback error and subsequent same/foreign-tenant fresh
activations. Two missing-runtime denials and two caught secure-operation denials
are separate outcomes. The two pending calls require a fresh unchanged native
accepted-timer/entered-wait pair, all five live physical guest owners and a
retained provider call. Audit labels, explicit capture loss or a closed audit
read refusal never replace those positive witnesses. Every terminal call must
be known/reaped with zero active provider owners before cell reuse; final node
and zero-contact observation-peer retirement remain mandatory.

Focused source/authority controls and three ordinary
[CLR reference modes](evidence/dotnet-resource-runtime-clr-reference-2026-10-20.json) pass.
NativeAOT and signed joined execution are pending. This campaign does not
qualify native threads, `ThreadLocal` isolation, CPU preemption, asynchronous
console flushing, a separately observed late wake, or whole-ticket completion.
