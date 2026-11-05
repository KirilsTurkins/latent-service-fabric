using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics.CodeAnalysis;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;

namespace OutsideFiniteWaits;

// DIAGNOSTIC ONLY: this reflects the existing WASI hook and dispatcher slot.
// It does not replace an executor, enqueue a synthetic pollable, or change a deadline.
internal static class PollPrefetchWitness
{
    private const int DelayMilliseconds = 1200;
    private const BindingFlags Static = BindingFlags.Static | BindingFlags.NonPublic;
    private const BindingFlags Instance = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;
    private static readonly IList<int> NoHandles = Array.Empty<int>();

    private static void Need(bool condition, string stage)
    {
        if (!condition) throw new InvalidOperationException("poll-prefetch-observation:" + stage);
    }

    private sealed class Probe
    {
        internal readonly object Marker = new();
        internal readonly TaskCompletionSource<int> Sibling = new(TaskCreationOptions.RunContinuationsAsynchronously);
        internal readonly CancellationTokenSource HookStop = new();
        internal readonly CancellationTokenSource TimerStop = new();
        internal readonly object Queue;
        internal readonly FieldInfo Slot;
        internal readonly FieldInfo NormalState;
        internal readonly FieldInfo DefaultState;
        internal readonly FieldInfo MainTask;
        internal readonly FieldInfo AggregateTarget;
        internal readonly Func<bool> Prefetched;
        internal Task? Driver;
        internal int BeforeCount;
        internal bool BeforeMatches;
        internal bool UnexpectedResolve;

        internal Probe(object queue, FieldInfo slot, FieldInfo normalState, FieldInfo defaultState,
            FieldInfo mainTask, FieldInfo aggregateTarget, Func<bool> prefetched)
        {
            Queue = queue; Slot = slot; NormalState = normalState; DefaultState = defaultState;
            MainTask = mainTask; AggregateTarget = aggregateTarget; Prefetched = prefetched;
        }

        internal IList<int> BeforePoll(object? state)
        {
            ++BeforeCount;
            try
            {
                object? item = Slot.GetValue(Queue);
                FieldInfo? itemState = item is null ? null :
                    NormalState.DeclaringType!.IsInstanceOfType(item) ? NormalState :
                    DefaultState.DeclaringType!.IsInstanceOfType(item) ? DefaultState : null;
                BeforeMatches = BeforeCount == 1 && ReferenceEquals(state, Marker)
                    && itemState is not null && ReferenceEquals(itemState.GetValue(item), Marker)
                    && Prefetched() && ThreadPool.PendingWorkItemCount == 0
                    && ReferenceEquals(MainTask.GetValue(null), Sibling.Task)
                    && AggregateTarget.GetValue(null) is null
                    && Driver is not null && !Driver.IsCompleted;
            }
            catch (Exception) { BeforeMatches = false; }
            // No handles: the original TimerQueue pollable is the only actual input.
            return NoHandles;
        }

        internal void OnResolve(object? _) => UnexpectedResolve = true;

        internal void RunSibling(object? state)
        {
            try
            {
                Need(ReferenceEquals(state, Marker), "sibling-state");
                Need(BeforeCount == 1 && BeforeMatches && !UnexpectedResolve, "decision-observation");
                Need(Driver is not null && (!Driver.IsCompleted || Driver.IsCompletedSuccessfully), "driver-terminal-state");
                // Read the ORIGINAL holder Task before canceling either registration.
                // The old poll path resolves it before this sibling; the fixed path
                // allows the sibling to run while it is still pending.
                int resolvedBeforeSibling = Driver!.IsCompletedSuccessfully ? 1 : 0;
                HookStop.Cancel();
                TimerStop.Cancel();
                Sibling.TrySetResult(resolvedBeforeSibling);
            }
            catch (Exception error) { Sibling.TrySetException(error); }
        }
    }

    // These preserve only the internal members that this diagnostic reflects.
    // CoreLib's aggregate field and prefetch helper are created by the selected
    // existing managed rewrite before NativeAOT reads its reference assembly.
    [DynamicDependency("RegisterWasiPollHook", "System.Threading.WasiEventLoop", "System.Private.CoreLib")]
    [DynamicDependency("s_pollables", "System.Threading.WasiEventLoop", "System.Private.CoreLib")]
    [DynamicDependency("s_hooks", "System.Threading.WasiEventLoop", "System.Private.CoreLib")]
    [DynamicDependency("s_checkScheduled", "System.Threading.WasiEventLoop", "System.Private.CoreLib")]
    [DynamicDependency("s_mainTask", "System.Threading.WasiEventLoop", "System.Private.CoreLib")]
    [DynamicDependency("s_lsfAggregateTarget", "System.Threading.WasiEventLoop", "System.Private.CoreLib")]
    [DynamicDependency("taskCompletionSource", "System.Threading.WasiEventLoop.PollableHolder", "System.Private.CoreLib")]
    [DynamicDependency("s_workQueue", "System.Threading.ThreadPool", "System.Private.CoreLib")]
    [DynamicDependency("_nextWorkItemToProcess", "System.Threading.ThreadPoolWorkQueue", "System.Private.CoreLib")]
    [DynamicDependency("LsfManagedWorkPrefetchedReady", "System.Threading.ThreadPoolWorkQueue", "System.Private.CoreLib")]
    [DynamicDependency("_state", "System.Threading.QueueUserWorkItemCallback", "System.Private.CoreLib")]
    [DynamicDependency("_state", "System.Threading.QueueUserWorkItemCallbackDefaultContext", "System.Private.CoreLib")]
    internal static string Run()
    {
        var core = typeof(ThreadPool).Assembly;
        Type loop = core.GetType("System.Threading.WasiEventLoop", throwOnError: true)!;
        Type queueType = core.GetType("System.Threading.ThreadPoolWorkQueue", throwOnError: true)!;
        Type holderType = core.GetType("System.Threading.WasiEventLoop+PollableHolder", throwOnError: true)!;
        Type normal = core.GetType("System.Threading.QueueUserWorkItemCallback", throwOnError: true)!;
        Type defaultContext = core.GetType("System.Threading.QueueUserWorkItemCallbackDefaultContext", throwOnError: true)!;
        var pollables = (IList)loop.GetField("s_pollables", Static)!.GetValue(null)!;
        var hooks = (IList)loop.GetField("s_hooks", Static)!.GetValue(null)!;
        FieldInfo scheduled = loop.GetField("s_checkScheduled", Static)!;
        FieldInfo main = loop.GetField("s_mainTask", Static)!;
        FieldInfo target = loop.GetField("s_lsfAggregateTarget", Static)!;
        FieldInfo source = holderType.GetField("taskCompletionSource", Instance)!;
        object queue = typeof(ThreadPool).GetField("s_workQueue", Static)!.GetValue(null)!;
        FieldInfo slot = queueType.GetField("_nextWorkItemToProcess", Instance)!;
        FieldInfo normalState = normal.GetField("_state", Instance)!;
        FieldInfo defaultState = defaultContext.GetField("_state", Instance)!;
        var prefetched = (Func<bool>)queueType.GetMethod("LsfManagedWorkPrefetchedReady", Static)!
            .CreateDelegate(typeof(Func<bool>));
        var register = (Action<object?, Func<object?, IList<int>>, Action<object?>, CancellationToken>)
            loop.GetMethod("RegisterWasiPollHook", Static)!.CreateDelegate(
                typeof(Action<object, Func<object, IList<int>>, Action<object>, CancellationToken>));
        var probe = new Probe(queue, slot, normalState, defaultState, main, target, prefetched);
        Func<object?, IList<int>> before = probe.BeforePoll;
        Action<object?> resolve = probe.OnResolve;
        WaitCallback sibling = probe.RunSibling;
        try
        {
            // Fail closed if unrelated queued work or an existing poll driver
            // would make the exact pair of FIFO items ambiguous.
            Need(ThreadPool.PendingWorkItemCount == 0 && !prefetched() && pollables.Count == 0
                && hooks.Count == 0 && !(bool)scheduled.GetValue(null)!, "initial-idle");
            register(probe.Marker, before, resolve, probe.HookStop.Token);
            Need(hooks.Count == 1 && pollables.Count == 0 && (bool)scheduled.GetValue(null)!
                && ThreadPool.PendingWorkItemCount == 1 && !prefetched(), "hook-queued-check");
            Task delayed = Task.Delay(DelayMilliseconds, probe.TimerStop.Token);
            Need(!delayed.IsCompleted && hooks.Count == 1 && pollables.Count == 1
                && ThreadPool.PendingWorkItemCount == 1 && !prefetched(), "timer-registered");
            object holder = pollables[0]!;
            Need(holderType.IsInstanceOfType(holder), "timer-holder-type");
            var completion = (TaskCompletionSource)source.GetValue(holder)!;
            probe.Driver = completion.Task;
            Need(!probe.Driver.IsCompleted, "driver-incomplete");
            Need(ThreadPool.QueueUserWorkItem(sibling, probe.Marker), "queue-sibling");
            Need(ThreadPool.PendingWorkItemCount == 2 && !prefetched(), "exact-fifo-pair");
            int result = probe.Sibling.Task.GetAwaiter().GetResult();
            Need(result is 0 or 1 && probe.BeforeCount == 1 && probe.BeforeMatches && !probe.UnexpectedResolve,
                "observation-not-reached");
            try { delayed.GetAwaiter().GetResult(); throw new InvalidOperationException("poll-prefetch-delay-not-canceled"); }
            catch (OperationCanceledException error) { Need(error.CancellationToken == probe.TimerStop.Token, "timer-token"); }
            return result == 0 ? "prefetch-observed:sibling-before-driver" : "prefetch-observed:driver-before-sibling";
        }
        finally
        {
            // The original hook and timer own their own registrations. Host
            // retirement must still prove queued maintenance drained afterward.
            probe.HookStop.Cancel(); probe.TimerStop.Cancel();
            probe.HookStop.Dispose(); probe.TimerStop.Dispose();
        }
    }
}

public static class Library
{
    public static string Run(string mode)
    {
        if (mode != "poll-prefetch") throw new ArgumentOutOfRangeException(nameof(mode));
        return PollPrefetchWitness.Run();
    }
}
