# Ordinary managed tasks without HTTP authority

The selected NativeAOT/WASI profile joins ordinary incomplete managed tasks
through the original CoreLib ThreadPoolWorkQueue dispatcher and WASI event loop.
It requires an authenticated canonical async export, declared monotonic CLOCK
and ACTIVATION interfaces, and separately installed operator grants. An HTTP
declaration is unnecessary for task and timer progress. The compiler selects the
existing activation adapter; it adds no network import, provider or grant.

The private `dotnet-stackful-task-wait-v1` derivation preserves the exact original
CoreLib preimage, dispatch, ExecutionContext entry/restore and TaskAwaiter error
paths. It limits nested joins to 32. Finite and cancellable blocking waits retain
their original unsupported boundary. The derived assembly must be the sole
CoreLib reference in both the compiler list and the actual NativeAOT response
file. Application assemblies and the shared package cache are unchanged.

`tools/qualify_dotnet_task_runtime.py` captures an outside local NuGet library
through normal add, resolve and exact candidate review. Its library calls
ordinary Task.Run, WhenAll, QueueUserWorkItem, TaskScheduler.Default,
ExecutionContext/AsyncLocal, Task.Delay, CancelAfter, nested joins and reentrant
monitor entry. Pending cases use a real incomplete TaskCompletionSource gate;
the programme rejects a task represented as already completed. It installs no
SynchronizationContext, scheduler, executor, HTTP handler or task implementation.
The original source and local feed are removed before offline NativeAOT build.

The signed programme keeps all 27 original node cases and adds a distinct
activation-authority refusal plus 12 managed task cases. Every successful case
requires the actual expected return value, known and reaped invocation, original
fuel/memory limits, zero outbound/log/effect consumption, provider-idle counters
and physical retirement observations. Original shutdown and cleanup assertions
remain mandatory. Provider limits are eight tasks, two executors, eight queued
records, sixteen waits, eight timers, eight results and eight native owners.
These are existing bounded provider settings, not measured CLR heap costs.

All 12 cases passed a separate reference CLR control using SDK 10.0.303. The
20 focused selection, authority and observation controls also pass. These results
do not qualify guest execution: actual fresh NativeAOT compilation and signed
execution are pending until a source-bound passing receipt is retained.

[#746](https://github.com/KirilsTurkins/latent-service-fabric/issues/746) remains
open. This finite queue/join programme does not establish compiler-safe CPU
preemption without yields, parked Monitor.Wait or Thread behavior, logical
ThreadLocal isolation, complete periodic/reset/disposal races, accepted background
work after root return, cross-tenant late-wake fences, or complete queue/GC/stack
admission and exhaustion costs. Standard sockets/DNS/TLS retain their separate
authority and qualification gates. No full CLR, multicore or transactional
runtime claim is made.
