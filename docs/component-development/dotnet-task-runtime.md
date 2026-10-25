# Ordinary managed tasks without HTTP authority

The selected NativeAOT/WASI profile joins ordinary incomplete managed tasks
through the original CoreLib ThreadPoolWorkQueue dispatcher and WASI event loop.
It requires an authenticated canonical async export, declared monotonic CLOCK
and ACTIVATION interfaces, and separately installed operator grants. The
fixture also explicitly declares RANDOM for the original CoreLib thread-pool
selector seed and installs the existing bounded bytes-only entropy policy. No
production grant is automatic. The timer fixture also declares WALL because the
pinned BCL TimerQueue static initializer records DateTime.UtcNow alongside the
monotonic tick count. Its separate wall policy reads only now-unix-millis; actual
timer waiting still uses the activation/monotonic clock. An HTTP
declaration is unnecessary for task and timer progress. The compiler selects the
existing activation adapter; it adds no network import, provider or grant.

The private `dotnet-stackful-task-wait-v1` derivation preserves the exact original
CoreLib preimage, dispatch, ExecutionContext entry/restore and TaskAwaiter error
paths. It limits nested joins to 32. With all four explicit task/timer declarations,
[finite and cancellable Task.Wait](../testing/dotnet-finite-task-waits.md) now uses
the original Task.WhenAny/Task.Delay through that pump, preserving exact token,
validation, fault and timeout behavior. Its separate eighteen-outcome signed
programme includes pending root cancellation/deadline and fresh recovery; it
does not relabel the historical twelve/sixteen-case receipts below. Unselected
infinite-only output is unchanged. The derived assembly must be the sole
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

The signed programme keeps all 27 original node cases and adds distinct
activation/entropy setup refusals, four isolated single-missing-grant refusals
and 16 managed task cases. Every successful case
requires the actual expected return value, known and reaped invocation, original
fuel/memory limits, zero outbound/log/effect consumption, provider-idle counters
and physical retirement observations. Original shutdown and cleanup assertions
remain mandatory. Provider limits are eight tasks, two executors, eight queued
records, sixteen waits, eight timers, eight results and eight native owners.
These are existing bounded provider settings, not measured CLR heap costs.

All 12 managed cases passed the actual fresh NativeAOT and signed-node
[run39348130572](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39348130572/job/118385603833).
The [source-bound receipt](../testing/evidence/dotnet-ordinary-tasks-signed-2026-10-20.json)
records the captured package, sole derived CoreLib binding, component identity,
44 known/reaped invocations, four isolated grant refusals, 18 provider-idle
observations, 36 physical samples and clean node/peer shutdown. The original
historical helper binaries and companion builds remain explicitly identified;
this fresh application execution does not claim a rebuilt current native host.
The integration preserves all exercised compiler/runtime inputs. Its shared
runner differs only by the separately qualified, default-off TypeScript clock
programme; whole-module AST projection confirms unchanged task execution.

All 12 cases also passed a separate reference CLR control using SDK 10.0.303.
The focused selection, authority and observation controls remain distinct from
actual guest execution. Two actual failures are retained: the first Task.Run
exposed the original ThreadPoolWorkQueue selector's RANDOM dependency; after
that explicit grant, six initial cases passed before the first timer exposed
TimerQueue's WALL dependency. The final passing run includes both declarations
and independently refuses each of the four missing grants before guest entry.

Four additional ordinary timer lifecycle cases now cover periodic callback
ExecutionContext with stable post-disposal counts, disabled/change/reset behavior,
disposal before a due time with rejected reset, and a callback that observes its
own DisposeAsync as genuinely incomplete until the callback returns. Their four
reference CLR controls pass with SDK10.0.303. The pinned BCL Timer.Change returns
false after cancellation; the fixture preserves that behavior. No callback,
scheduler or Timer implementation is replaced.

All sixteen cases passed the fresh signed NativeAOT
[run39352737634](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39352737634/job/118400465348).
The [expanded source-bound receipt](../testing/evidence/dotnet-timer-lifecycle-signed-2026-10-20.json)
records exactly48 known/reaped invocations within the original48-call ceiling,
22 provider-idle observations,40 complete physical process-tree samples, all
four isolated missing-grant denials and clean node/peer shutdown. All eight
exercised helper/compiler source files and the full runtime-input digest match
the integrated source. The identified historical native binaries are reused;
this does not claim a rebuilt current host. Complete simultaneous reset/dispose
races, shutdown/tenant fencing and managed CPU scheduling remain separate.

## Qualification-private WaitAll reference

The ordinary driver still selects its existing finite single-task implementation.
`Task.WaitAll` is not promoted to that default by this source milestone. The
private `--aggregate-task-wait` tool variant retains the original nine public/core
method remainders, countdown, completion actions and detach-finally, with one
bounded aggregate-ready target and the existing depth32/context restoration.
It adds no application scheduler, replacement completion task, authority or grant.

All23 CLR reference controls passed the actual
[run40180463429](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/40180463429/job/121130229483)
at source732c53e98570ad59428af546fb095f81d518e2fb. The
[bounded receipt](../testing/evidence/dotnet-waitall-reference-2026-10-25.json)
binds the authenticated128-member artifact,46 Git inputs,60 zero-exit commands,
120 raw channels, three byte-identical old-mode DLL/receipt comparisons, the
95-helper derivation and all23 exact outcomes. Actual SDK is10.0.100 and CLR is
10.0.13; controller execution took69.298450009s within600s. Both target and context
restoration, original exception/token identity, two-task completion ordering,
one finite interval, no added infinite-wait clock reads and cleanup refusals are
checked. The earlier four failed runs retain their original failed status.

This is an explicit host reference: real CLR tasks/MRES/token/ExecutionContext and
the host's private countdown counterpart run with controlled dispatch/clock ports.
Three exact real ThrowHelpers translate four source enum constants by name to the
actual CLR enum, rethrowing the original exception object. One pinned nonvirtual
instance-call opcode is projected to a static DynamicMethod call only after
proving its fresh nonnull countdown receiver; source/projected hashes and unchanged
branch/local/EH scope are recorded. The production candidate IL stays unchanged.
This does not execute pinned WASI polling/accounting or qualify native exception,
physical-retirement, default NativeAOT, signed-component or whole-cost behavior.
Normal promotion and one fresh signed programme remain separate required work.

[#746](https://github.com/KirilsTurkins/latent-service-fabric/issues/746) remains
open. This finite queue/join programme does not establish compiler-safe CPU
preemption without yields, parked Monitor.Wait or Thread behavior, logical
ThreadLocal isolation, complete periodic/reset/disposal races, accepted background
work after root return, cross-tenant late-wake fences, or complete queue/GC/stack
admission and exhaustion costs. Standard sockets/DNS/TLS retain their separate
authority and qualification gates. No full CLR, multicore or transactional
runtime claim is made.
