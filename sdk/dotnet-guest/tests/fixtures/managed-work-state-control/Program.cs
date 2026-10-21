using Lsf.CompilerOwned;
using System.Text.Json;

internal static class StateControl
{
    internal static readonly Queue<Action> Work = new();
    private static readonly Dictionary<ulong, int> Owners = new();
    private static readonly int[] Limits = [4, 1, 1, 1, 2, 2, 2, 1];
    private static ulong sequence = uint.MaxValue;
    private static bool closing;
    private static (ulong, ulong) context;
    private static int maximumTasks;
    private static int maximumResults;
    private static int Count(int kind) => Owners.Values.Count(value => value == kind);
    private static void Need(bool value)
    {
        if (!value) throw new InvalidOperationException("managed-work-control-assertion");
    }
    private static void Refuses(Action action, string code)
    {
        try { action(); }
        catch (InvalidOperationException error) when (error.Message == code) { return; }
        throw new InvalidOperationException("managed-work-control-missing-refusal");
    }
    private static (ulong, ulong) Reserve(int kind, ulong generation, ulong id)
    {
        Need(0 <= kind && kind < Limits.Length);
        if ((generation, id) != (0UL, 0UL)) Need(generation == 17 && Owners.ContainsKey(id));
        if (closing) Need(generation == 17 && Owners.ContainsKey(id));
        if (Count(kind) >= Limits[kind]) throw new InvalidOperationException("control-ledger-capacity");
        ulong key = checked(++sequence);
        Owners.Add(key, kind);
        maximumTasks = Math.Max(maximumTasks, Count(0)); maximumResults = Math.Max(maximumResults, Count(6));
        return (17, key);
    }
    private static void Settle(ulong generation, ulong id)
    {
        Need(generation == 17 && id > uint.MaxValue && Owners.Remove(id));
    }
    internal static void Step()
    {
        Need(Work.Count != 0); Work.Dequeue()();
    }
    private static void Begin() => ManagedWorkRuntime.Install(Reserve, Settle, () => closing = true,
        (generation, id) => context = (generation, id));
    private static void Finish()
    {
        ManagedWorkRuntime.JoinAcceptedWork(); ManagedWorkRuntime.FinishedPhysicalDrain();
        Need(Owners.Count == 0 && context == (0UL, 0UL) && Work.Count == 0);
    }
    private static TaskCompletionSource<int> Pending() => new();
    private static void Complete(TaskCompletionSource<int> source)
    {
        source.SetResult(1); ManagedWorkRuntime.Completed(source.Task);
    }
    private static void Run(string name)
    {
        if (name == "untracked-startup-refused-before-admission")
        {
            Work.Enqueue(() => { }); Refuses(Begin, "managed-work-untracked-startup-work");
            Need(Owners.Count == 0); return;
        }
        Begin();
        switch (name)
        {
            case "native-task-admission": {
                Limits[0] = 2;
                var first = Pending(); ManagedWorkRuntime.Schedule(first.Task);
                Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "control-ledger-capacity");
                Need(Count(0) == 2); Complete(first); Finish(); break;
            }
            case "unwrap-inner-actual-completion": {
                var outer = new TaskCompletionSource<Task<int>>(); var inner = Pending();
                var actual = outer.Task.Unwrap(); ManagedWorkRuntime.Schedule(outer.Task);
                ManagedWorkRuntime.Unwrap(actual, outer.Task); ManagedWorkRuntime.Inner(actual, inner.Task);
                outer.SetResult(inner.Task); ManagedWorkRuntime.Completed(outer.Task);
                Need(!actual.IsCompleted && Count(0) == 2);
                inner.SetResult(9); Need(actual.IsCompletedSuccessfully); ManagedWorkRuntime.Completed(actual);
                Finish(); Need(maximumTasks == 2); break;
            }
            case "queued-admission-rollback": {
                object first = new(), second = new(); ManagedWorkRuntime.Enqueue(first);
                Refuses(() => ManagedWorkRuntime.Enqueue(second), "control-ledger-capacity");
                Need(Count(0) == 2 && Count(3) == 1);
                ManagedWorkRuntime.Dequeue(first); var previous = ManagedWorkRuntime.Enter(first);
                try { Need(Count(0) == 2 && Count(3) == 0); }
                finally { ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.CallbackCompleted(first); }
                Finish(); break;
            }
            case "enqueue-failure-releases-both": {
                object item = new(); ManagedWorkRuntime.Enqueue(item); ManagedWorkRuntime.EnqueueFailed(item);
                Need(Count(0) == 1 && Count(3) == 0); Finish(); break;
            }
            case "continuation-failure-before-acceptance": {
                var pending = Pending(); ManagedWorkRuntime.Continuation(pending.Task);
                Need(Count(0) == 2); ManagedWorkRuntime.ContinuationFailed(pending.Task);
                Need(Count(0) == 1 && !pending.Task.IsCompleted); Finish(); break;
            }
            case "local-pop-releases-queue-only": {
                object item = new(); ManagedWorkRuntime.Enqueue(item);
                Need(!ManagedWorkRuntime.Popped(false, item) && Count(3) == 1);
                Need(ManagedWorkRuntime.Popped(true, item) && Count(3) == 0 && Count(0) == 2);
                ManagedWorkRuntime.CallbackCompleted(item); Finish(); break;
            }
            case "join-real-required-task": {
                var actual = Pending(); ManagedWorkRuntime.CreatedAsync(actual.Task);
                bool finallyRan = false;
                Work.Enqueue(() => { Need(closing && !actual.Task.IsCompleted); finallyRan = true; Complete(actual); });
                Finish(); Need(finallyRan && actual.Task.IsCompletedSuccessfully && maximumTasks == 1); break;
            }
            case "callback-retains-async-void-task": {
                object callback = new(); var actual = Pending(); ManagedWorkRuntime.Enqueue(callback);
                ManagedWorkRuntime.Dequeue(callback); var previous = ManagedWorkRuntime.Enter(callback);
                try { ManagedWorkRuntime.CreatedAsync(actual.Task); }
                finally { ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.CallbackCompleted(callback); }
                Need(Count(0) == 2); Work.Enqueue(() => Complete(actual)); Finish(); break;
            }
            case "live-descendant-during-closing": {
                var parent = Pending(); ManagedWorkRuntime.Schedule(parent.Task);
                Work.Enqueue(() => {
                    Need(closing); var previous = ManagedWorkRuntime.Enter(parent.Task);
                    try { var descendant = Pending(); ManagedWorkRuntime.Schedule(descendant.Task); Complete(descendant); Complete(parent); }
                    finally { ManagedWorkRuntime.Exit(previous); }
                });
                Finish(); Need(maximumTasks == 3); break;
            }
            case "closing-rejects-independent": {
                ManagedWorkRuntime.JoinAcceptedWork();
                Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-independent-admission-closed");
                ManagedWorkRuntime.FinishedPhysicalDrain(); Need(Owners.Count == 0); break;
            }
            case "unobserved-original-fault-result": {
                var actual = Pending(); var original = new ArgumentException("synthetic-public-control");
                ManagedWorkRuntime.CreatedAsync(actual.Task); actual.SetException(original);
                AggregateException? received = null;
                try { ManagedWorkRuntime.JoinAcceptedWork(); }
                catch (AggregateException error) { received = error; }
                Need(received is not null && ReferenceEquals(received.InnerException, original) && maximumResults == 1);
                ManagedWorkRuntime.FinishedPhysicalDrain(); Need(Owners.Count == 0); break;
            }
            case "observed-fault-does-not-become-unhandled": {
                var actual = Pending(); ManagedWorkRuntime.CreatedAsync(actual.Task);
                actual.SetException(new ArgumentException("synthetic-public-observed"));
                _ = actual.Task.Exception; ManagedWorkRuntime.Observed(actual.Task);
                Finish(); Need(maximumResults == 0); break;
            }
            case "bounded-required-continuations": {
                var pending = Enumerable.Range(0, 32).Select(_ => Pending()).ToArray();
                foreach (var actual in pending) ManagedWorkRuntime.CreatedAsync(actual.Task);
                Refuses(() => ManagedWorkRuntime.CreatedAsync(Pending().Task), "managed-work-required-continuation-limit");
                foreach (var actual in pending) Complete(actual); Finish(); break;
            }
            case "opaque-pending-is-not-quiescent": {
                var actual = Pending(); ManagedWorkRuntime.CreatedAsync(actual.Task);
                Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
                Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-continuations");
                Need(!actual.Task.IsCompleted && Owners.Count == 2); break;
            }
            default: throw new InvalidOperationException("unknown-managed-work-control");
        }
    }
    private static void Main(string[] args)
    {
        Need(args.Length == 1); Run(args[0]);
        Console.WriteLine(JsonSerializer.Serialize(new { control = args[0], passed = true,
            registryCore = "production-source", nativeLedger = "explicit-test-port", dispatcher = "explicit-test-port",
            actualClrTasks = true, guestQualified = false }));
    }
}
