# C# guest SDK (experimental)

Follow [Create your own C# capsule](../../docs/component-development/dotnet-authoring.md)
for an editable project outside the checkout, compilation, signed admission,
publish/deploy/invoke, declared errors and cleanup. Client-side .NET RPC SDKs
are separate and are not used to implement guest capabilities.

## Compiler and supported contract

Linux x86-64 is the qualified compiler host. The exact inputs are .NET SDK
10.0.100, Componentize.NET SDK and WitBindgen 0.8.0-preview00011, NativeAOT LLVM
10.0.0-rc.1.26306.1, WASI SDK 29.0 (LLVM 21.1.4), wit-bindgen 0.62.0 and
wasm-tools 1.254.0. The six-package NuGet lock and SHA-512 package content
hashes are checked. No application package or MSBuild override is admitted.
Compiler SDK, runtime, reference-pack, NuGet and WASI trees are inventoried
before and after each build. The observation deliberately says non-hermetic,
declared-inputs-incomplete and reproducibility-not-checked.

Edit `src/Main.cs` and authoritative `wit/world.wit`; keep the captured
`vendor/lsf` SDK unchanged. The driver generates and independently checks
typed C# bindings, compares the generated inputs used by the actual compiler,
and derives package contracts from that WIT. Full-width integers use C#
`long`/`ulong` and `int`/`uint`, without JSON-number conversion.
Canonical strings preserve UTF-8 and embedded NUL; lists, records, variants,
options, typed results and resources use the generated canonical ABI.
First-class WIT future/stream, map and fixed-size-list forms are explicitly
rejected. Async imports use a reviewed synchronous C# binding projection:
Wasmtime suspends the activation stack while host operations are pending.
This is not permission to turn asynchronous operations into blocking host I/O.

NativeAOT has no JIT or dynamic assembly loading. The compiled profile probe
checks dynamic-code flags, statically rooted method metadata after trimming,
UTF-8 library round-trips, completed/uncompleted activation-local tasks and
explicit GC collection. Reflection is limited to statically visible, rooted
metadata; this is not arbitrary runtime discovery. Arbitrary reflection,
Reflection.Emit, application threads, timers, task schedulers and a CLR host
event loop are outside this profile. An unresolved managed task may belong
to an activation, but cannot preserve an application after its activation
ends. Unsupported host operations trap; they do not acquire ambient authority.

## Capabilities and ownership

The generated SDK only includes imports present in the application world:

| Wrapper | Behavior |
| --- | --- |
| HTTP | Buffered request, full typed response/error, no retries. |
| Streaming HTTP | Explicit upload, body and chunk owners; finish/abort consumes upload ownership. |
| Blobs | Writer/reader/handle/chunk ownership, one-shot materialization and explicit seal/close. |
| Secrets | Explicit lease, bounded scoped byte access, zeroed local owned bytes on disposal. |
| Events | Typed publish result and full-width accepted sequence. |
| Local service | Typed payload and declared-error result; cancellation propagates to the child. |
| Random | Bounded byte count and full-width unsigned value. |
| Metrics | Typed single counter observation, bounded labels and no retries. |

`Owner<T, TKind>` invalidates before consuming effects, rejects use after
close and concurrent/reentrant borrows, and never uses a finalizer for release.
`Scope` owns at most 256 resources, closes in reverse order and continues
closing remaining resources if a drop throws. Use `using`/explicit disposal;
GC collection is not resource cleanup. Host cancellation revokes activation
authority and releases host resources even when guest code cannot resume.

## Runtime and evidence

The closed WASI adapter denies ambient files, sockets, wall time and entropy.
NativeAOT GC monotonic time is routed through
`latent:clock/monotonic@0.1.0`, declared in WIT and separately granted by
the operator. Missing authority fails closed. Host calls share the activation's
budget and deadline; wrappers do not retry or widen them.

Standalone capsules use a 128 MiB memory ceiling, finite one-billion fuel
ceiling and explicit 120-second cold invocation ceiling. The all-SDK harness
uses ten-billion fuel for its deliberately multi-operation cases. Its nested
service caller alone explicitly reserves 256 MiB; the callee stays at 128 MiB.
Measured NativeAOT caller and callee activations each need about 54 MiB, and
the node delegates only half the parent's remaining memory. A 128 MiB caller
cannot fund that child. This is a finite manifest and operator reservation,
not a change to production admission or delegation. Cold compile
cost is separate from warm activation cost; neither is described as free.
The retained node workflow checks fixed host baseline, active work, bounded
shared code/cache and increasing dormant deployments. No dormant application
owns a process, thread pool, cell, event loop or initialized managed heap.

`tools/qualify_dotnet_capsules.py` retains five actual standalone builds,
nine SDK builds, the ten shared runtime cases, disposable-owner misuse tests,
signed enforced-node workflow, memory/deadline/cancellation/trap recovery and
the six verbatim Bash guide steps. CI retains failed attempts and immutable
source inputs too. Local typechecks alone are not qualification evidence.
Release publication remains on hold; this does not close human review #345.
