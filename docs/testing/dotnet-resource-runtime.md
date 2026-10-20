# Managed resource callbacks and standard facilities

The separate [joined campaign](../../.github/workflows/dotnet-resource-runtime.yml)
uses two normally captured outside managed packages. The transitive package
embeds UTF-8/NUL, binary and empty data. Two independent standard assembly
resource streams remain live across genuine incomplete `Task.Run`/`WhenAll`
callbacks, `Task.Delay` and `AsyncLocal` context capture. Those callbacks use
ordinary `Stopwatch`, UTC time, cryptographic RNG and `Console` operations.
The application installs no scheduler, context, logger or entropy replacement.

One fresh hosted NativeAOT component was compiled at source b168. The ordinary current installer
prepares the pinned compiler and small WASI adapters; it does not rebuild
CoreLib from source, a native host, or the five guest templates. Existing
compiler-owned exact-preimage TaskWait, closed-filesystem and managed entropy
derivations remain mandatory, including their actual final ILC/linker bindings.
The original source 77bf V7 native products retain their separate authenticated
compiler ancestry. The node-only replay uses a separately authenticated f919
native producer with a bounded actual wait-for Pending observer. No old build
or qualification receipt is rewritten, and no AOT compilation is repeated.

The selected profile retains eight tasks, two executors, eight queued items,
sixteen waits, eight timers, eight results and eight native owners. Explicit
per-tenant CLOCK/WALL/RANDOM/LOG/ACTIVATION declarations and grants are required;
HTTP is absent. Noncryptographic hash-seed byte authority is retained while the
ordinary secure RNG call must catch its exact cryptographic error before the
secure `u64-value` operation is granted under the same finite entropy budget.

Eleven joined calls cover completion, cleared timers, root trap, pending
cancellation/deadline, callback error and subsequent same/foreign-tenant fresh
activations. Two missing-runtime denials and two caught secure-operation denials
are separate outcomes. The two pending calls require a fresh bounded native
observation after the original wait-for future returns `Poll::Pending`, all five live physical guest owners and a
retained provider call. Audit labels, explicit capture loss or a closed audit
read refusal never replace those positive witnesses. Every terminal call must
be known/reaped with zero active provider owners before cell reuse; final node
and zero-contact observation-peer retirement remain mandatory.

Focused source/authority controls and three ordinary
[CLR reference modes](evidence/dotnet-resource-runtime-clr-reference-2026-10-20.json) pass.
The original 19ff attempt failed before AOT during generated-output capture;
b168 genuinely compiled the component, then exposed a controller generation
conflict. The 30eb exact-component replay passed both tenants' authority setup
and the first five joined calls, then failed its pending reader: the .NET PAL
uses `wait-for`, not the original observer's `timer-start`/`timer-next` path.
[Native producer f919](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39458247294/job/118750640204)
passed all eight bounded observer controls.
[The corrected signed replay](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39466265217/job/118778369144)
passed all 15 outcomes on exact source2d18: two pre-guest runtime denials,
two caught secure-operation denials and eleven joined lifecycle calls. The
[compact observation](evidence/dotnet-resource-runtime-signed-2026-10-20.json)
binds the original b168 AOT component and f919 native products separately.
Artifact12284633689 was authenticated in full:8,533,100 bytes,431 CRC/hash
members and41 exercised Git material rows. Both pending activations produced
one real Task0/Wait1/Timer1 record. Fifteen node-scope idle observations have
all18 active provider counters zero;18 physical samples, clean node shutdown
and a zero-contact reaped observation peer were verified. No AOT or native
build was repeated. The earlier c720 acquisition failed externally with an
HTTP503 account-egress limit before any node/guest ran; every original failure
remains a failure. This campaign does not
qualify native threads, `ThreadLocal` isolation, CPU preemption, asynchronous
console flushing, a separately observed late wake, or whole-ticket completion.

The f44 node-only replay reached a real native witness with Task0, Wait1,
Timer1, then failed because its reader had assumed a positive Task count.
The Timer PAL admits a Wait and the host admits a Timer; an HTTP task owner
is absent in this no-HTTP fixture. The corrected reader requires one or more
fresh real Pending records within the original configured limits, including
positive Wait/Timer counts, plus the unchanged physical/provider barriers.
Unknown, duplicate, stale, overflow and zero-owner records remain refusals.
This correction does not qualify managed Task accounting or change a capacity.
