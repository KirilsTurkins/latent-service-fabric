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
    private static ulong settlementRefusal;
    private static bool settlementUnknown;
    private static int refusedSettlements;
    private static int controlDispatches;
    private static bool rootJoinReturned;
    private static bool rootSettlementControl, multipleConversionControl;
    private static bool rootFinalizationReturned;
    private static bool refuseContextClear, contextThrowsBeforeClear;
    private static ulong rootIdentifier, storageIdentifier;
    private static int rootSettlements, storageSettlements, contextClearAttempts;
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
        if (id == rootIdentifier) rootSettlements++;
        if (id == storageIdentifier) storageSettlements++;
        if (id == settlementRefusal)
        {
            Need(generation == 17 && id > uint.MaxValue);
            refusedSettlements++;
            // A refusal retains the token; an ambiguous trap may follow removal.
            if (settlementUnknown) Need(Owners.Remove(id));
            else Need(Owners.ContainsKey(id));
            throw new InvalidOperationException("managed-work-settlement-refused");
        }
        Need(generation == 17 && id > uint.MaxValue && Owners.Remove(id));
    }
    internal static void Step()
    {
        Need(Work.Count != 0); controlDispatches++; Work.Dequeue()();
    }
    private static void Context(ulong generation, ulong id)
    {
        if (refuseContextClear && (generation, id) == (0UL, 0UL))
        {
            contextClearAttempts++;
            if (!contextThrowsBeforeClear) context = (generation, id);
            throw new InvalidOperationException("control-context-clear-failed");
        }
        context = (generation, id);
    }
    private static void Begin() => ManagedWorkRuntime.Install(Reserve, Settle, () => closing = true, Context);
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
    private static void OwnerSettlementControl(bool callback, bool unknown)
    {
        var pending = Pending();
        object item = callback ? new object() : pending.Task;
        if (callback) { ManagedWorkRuntime.Enqueue(item); ManagedWorkRuntime.Dequeue(item); }
        else ManagedWorkRuntime.Schedule(pending.Task);
        var previous = ManagedWorkRuntime.Enter(item);
        var original = context;
        var captured = ExecutionContext.Capture() ?? throw new InvalidOperationException("control-context");
        ManagedWorkRuntime.Exit(previous);
        Need(original.Item1 == 17 && Owners.ContainsKey(original.Item2) && Count(0) == 2);
        settlementRefusal = original.Item2; settlementUnknown = unknown;
        if (!callback) pending.SetResult(1);
        void CompleteOwner()
        {
            if (callback) ManagedWorkRuntime.CallbackCompleted(item);
            else ManagedWorkRuntime.Completed(pending.Task);
        }
        Refuses(CompleteOwner, "managed-work-settlement-refused");
        if (callback) Refuses(CompleteOwner, "managed-work-double-settle");
        ExecutionContext.Run(captured, _ =>
        {
            Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-parent-retired");
            Need(context == (0UL, 0UL));
        }, null);
        if (!callback) Refuses(CompleteOwner, "managed-work-double-settle");
        Refuses(() => ManagedWorkRuntime.Enqueue(item), "managed-work-owner-retired");
        Refuses(() => { ManagedWorkRuntime.Enter(item); }, "managed-work-execution-parent");
        Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; },
            "managed-work-double-settle");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(refusedSettlements == 1 && Count(0) == (unknown ? 1 : 2)
            && Count(3) == 0 && Owners.ContainsKey(original.Item2) != unknown
            && context.Item1 == 17 && context.Item2 != original.Item2 && Work.Count == 0);
    }
    private static void ResultSettlementControl(bool unknown)
    {
        var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
        var originalError = new ArgumentException("control-original-fault");
        pending.SetException(originalError); ManagedWorkRuntime.Completed(pending.Task);
        Need(Count(0) == 1 && Count(6) == 1);
        settlementRefusal = Owners.Single(entry => entry.Value == 6).Key;
        settlementUnknown = unknown;
        Refuses(() => ManagedWorkRuntime.Observed(pending.Task), "managed-work-settlement-refused");
        Refuses(() => ManagedWorkRuntime.Observed(pending.Task), "managed-work-double-settle");
        AggregateException? received = null;
        try { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; }
        catch (AggregateException error) { received = error; }
        Need(received is not null && ReferenceEquals(received.InnerException, originalError));
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!rootJoinReturned && refusedSettlements == 1 && Count(0) == 1
            && Count(6) == (unknown ? 0 : 1) && Owners.ContainsKey(settlementRefusal) != unknown
            && Count(3) == 0 && Work.Count == 0);
    }
    private static void RootSettlementControl(bool storage, bool unknown)
    {
        rootSettlementControl = true;
        rootIdentifier = context.Item2;
        storageIdentifier = Owners.Single(entry => entry.Value == 7).Key;
        var captured = ExecutionContext.Capture() ?? throw new InvalidOperationException("control-context");
        Need(rootIdentifier != 0 && storageIdentifier != rootIdentifier && Count(0) == 1 && Count(7) == 1);
        ManagedWorkRuntime.JoinAcceptedWork();
        settlementRefusal = storage ? storageIdentifier : rootIdentifier;
        settlementUnknown = unknown;
        Refuses(() => { ManagedWorkRuntime.FinishedPhysicalDrain(); rootFinalizationReturned = true; },
            "managed-work-settlement-refused");
        Refuses(() => { ManagedWorkRuntime.FinishedPhysicalDrain(); rootFinalizationReturned = true; },
            "managed-work-finalization-uncertain");
        Refuses(Begin, "managed-work-installation");
        Need(context == (0UL, 0UL));
        ExecutionContext.Run(captured, _ =>
        {
            Need(context == (0UL, 0UL));
            Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-independent-admission-closed");
        }, null);
        Need(context == (0UL, 0UL) && !rootFinalizationReturned && refusedSettlements == 1
            && storageSettlements == 1 && rootSettlements == (storage ? 0 : 1)
            && Owners.ContainsKey(storageIdentifier) == (storage && !unknown)
            && Owners.ContainsKey(rootIdentifier) == (storage || !unknown)
            && Count(3) == 0 && Work.Count == 0);
    }
    private static void RootContextClearControl(bool failSettlement)
    {
        rootSettlementControl = true;
        rootIdentifier = context.Item2;
        storageIdentifier = Owners.Single(entry => entry.Value == 7).Key;
        ManagedWorkRuntime.JoinAcceptedWork();
        if (failSettlement) settlementRefusal = storageIdentifier;
        refuseContextClear = true; contextThrowsBeforeClear = failSettlement;
        Refuses(() => { ManagedWorkRuntime.FinishedPhysicalDrain(); rootFinalizationReturned = true; },
            failSettlement ? "managed-work-settlement-refused" : "control-context-clear-failed");
        refuseContextClear = false;
        Refuses(() => { ManagedWorkRuntime.FinishedPhysicalDrain(); rootFinalizationReturned = true; },
            "managed-work-finalization-uncertain");
        Refuses(Begin, "managed-work-installation");
        Need(!rootFinalizationReturned && context == (failSettlement ? (17UL, rootIdentifier) : (0UL, 0UL))
            && contextClearAttempts == 1 && rootSettlements == (failSettlement ? 0 : 1) && storageSettlements == 1
            && refusedSettlements == (failSettlement ? 1 : 0) && Owners.Count == (failSettlement ? 2 : 0));
    }
    private static void FaultConversionControl(bool unknown)
    {
        var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
        var previous = ManagedWorkRuntime.Enter(pending.Task);
        var original = context;
        var captured = ExecutionContext.Capture() ?? throw new InvalidOperationException("control-context");
        ManagedWorkRuntime.Exit(previous);
        var originalError = new ArgumentException("control-fault-conversion");
        pending.SetException(originalError);
        settlementRefusal = original.Item2; settlementUnknown = unknown;
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-settlement-refused");
        Need(Count(6) == 1);
        var result = Owners.Single(entry => entry.Value == 6).Key;
        Need(ManagedWorkRuntime.PendingResultForControl(pending.Task) == (17UL, result));
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
        ExecutionContext.Run(captured, _ =>
        {
            Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-parent-retired");
        }, null);
        Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; },
            "managed-work-double-settle");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!rootJoinReturned && refusedSettlements == 1 && Count(6) == 1 && Owners.ContainsKey(result)
            && ManagedWorkRuntime.PendingResultForControl(pending.Task) == (17UL, result)
            && Owners.ContainsKey(original.Item2) != unknown && Count(0) == (unknown ? 1 : 2));
    }
    private static void MultipleFaultConversionsControl()
    {
        multipleConversionControl = true;
        var first = Pending(); var second = Pending();
        ManagedWorkRuntime.Schedule(first.Task); ManagedWorkRuntime.Schedule(second.Task);
        var previous = ManagedWorkRuntime.Enter(first.Task); ulong firstId = context.Item2;
        ManagedWorkRuntime.Exit(previous);
        previous = ManagedWorkRuntime.Enter(second.Task); ulong secondId = context.Item2;
        ManagedWorkRuntime.Exit(previous);
        first.SetException(new ArgumentException("control-first-fault"));
        second.SetException(new ArgumentException("control-second-fault"));
        settlementRefusal = firstId;
        Refuses(() => ManagedWorkRuntime.Completed(first.Task), "managed-work-settlement-refused");
        var firstResult = ManagedWorkRuntime.PendingResultForControl(first.Task);
        settlementRefusal = secondId;
        Refuses(() => ManagedWorkRuntime.Completed(second.Task), "managed-work-settlement-refused");
        var secondResult = ManagedWorkRuntime.PendingResultForControl(second.Task);
        Need(firstResult is not null && secondResult is not null && firstResult != secondResult
            && Owners.ContainsKey(firstResult.Value.Id) && Owners.ContainsKey(secondResult.Value.Id)
            && Owners.ContainsKey(firstId) && Owners.ContainsKey(secondId));
        Refuses(() => ManagedWorkRuntime.Completed(first.Task), "managed-work-double-settle");
        Refuses(() => ManagedWorkRuntime.Completed(second.Task), "managed-work-double-settle");
        Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; },
            "managed-work-double-settle");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!rootJoinReturned && refusedSettlements == 2 && Count(0) == 3 && Count(6) == 2);
    }
    private static void QueueSettlementControl(bool rollback, bool unknown)
    {
        Limits[3] = 2;
        object item = new(); ManagedWorkRuntime.Enqueue(item);
        var original = ManagedWorkRuntime.QueuedTokenForControl(item)
            ?? throw new InvalidOperationException("missing-original-control-queue-token");
        settlementRefusal = original.Id; settlementUnknown = unknown;
        Refuses(() => {
            if (rollback) ManagedWorkRuntime.EnqueueFailed(item);
            else ManagedWorkRuntime.Dequeue(item);
        }, "managed-work-settlement-refused");
        Refuses(() => ManagedWorkRuntime.Dequeue(item), "managed-work-queue-settlement-uncertain");
        Refuses(() => ManagedWorkRuntime.EnqueueFailed(item), "managed-work-queue-settlement-uncertain");
        Refuses(() => ManagedWorkRuntime.Enqueue(item), "managed-work-queue-settlement-uncertain");
        object other = new(); ManagedWorkRuntime.Enqueue(other);
        ManagedWorkRuntime.Dequeue(other); ManagedWorkRuntime.CallbackCompleted(other);
        Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; },
            "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!rootJoinReturned && refusedSettlements == 1 && Count(0) == 2 && Count(3) == (unknown ? 0 : 1)
            && ManagedWorkRuntime.QueuedTokenForControl(item) == original
            && Owners.ContainsKey(original.Id) != unknown && Work.Count == 0);
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
            case "queue-rollback-refusal-prevents-retry": QueueSettlementControl(true, false); break;
            case "queue-rollback-unknown-prevents-retry": QueueSettlementControl(true, true); break;
            case "queue-dequeue-refusal-prevents-retry": QueueSettlementControl(false, false); break;
            case "queue-dequeue-unknown-prevents-retry": QueueSettlementControl(false, true); break;
            case "enqueue-failure-settlement-refusal-retains-owner":
            case "dequeue-settlement-refusal-retains-owner": {
                object item = new(); ManagedWorkRuntime.Enqueue(item);
                var original = ManagedWorkRuntime.QueuedTokenForControl(item)
                    ?? throw new InvalidOperationException("missing-original-control-queue-token");
                settlementRefusal = original.Id;
                Need(Count(0) == 2 && Count(3) == 1 && original.Generation == 17);
                Refuses(() => {
                    if (name == "enqueue-failure-settlement-refusal-retains-owner") ManagedWorkRuntime.EnqueueFailed(item);
                    else ManagedWorkRuntime.Dequeue(item);
                }, "managed-work-settlement-refused");
                if (ManagedWorkRuntime.QueuedTokenForControl(item) != original)
                    throw new InvalidOperationException("managed-work-control-queue-token-lost");
                Need(Count(0) == 2 && Count(3) == 1 && Owners.ContainsKey(original.Id));
                // No synthetic completion, callback replay or automatic acknowledgement retry.
                Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; },
                    "managed-work-unproven-quiescence");
                Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
                Need(refusedSettlements == 1 && Work.Count == 0
                    && ManagedWorkRuntime.QueuedTokenForControl(item) == original
                    && Count(0) == 2 && Count(3) == 1);
                break;
            }
            case "task-settlement-refusal-revokes-context": OwnerSettlementControl(false, false); break;
            case "task-settlement-unknown-revokes-context": OwnerSettlementControl(false, true); break;
            case "callback-settlement-refusal-prevents-retry": OwnerSettlementControl(true, false); break;
            case "callback-settlement-unknown-prevents-retry": OwnerSettlementControl(true, true); break;
            case "result-settlement-refusal-prevents-finalization": ResultSettlementControl(false); break;
            case "result-settlement-unknown-prevents-finalization": ResultSettlementControl(true); break;
            case "fault-conversion-success-is-idempotent": {
                var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
                pending.SetException(new ArgumentException("control-converted-result"));
                ManagedWorkRuntime.Completed(pending.Task); ManagedWorkRuntime.Completed(pending.Task);
                Need(Count(0) == 1 && Count(6) == 1
                    && ManagedWorkRuntime.PendingResultForControl(pending.Task) == (0UL, 0UL));
                ManagedWorkRuntime.Observed(pending.Task); Finish(); break;
            }
            case "fault-conversion-at-record-capacity": {
                Limits[0] = 32;
                var pending = Enumerable.Range(0, 31).Select(_ => Pending()).ToArray();
                foreach (var item in pending) ManagedWorkRuntime.Schedule(item.Task);
                pending[0].SetException(new ArgumentException("control-full-record-conversion"));
                ManagedWorkRuntime.Completed(pending[0].Task);
                Need(Count(0) == 31 && Count(6) == 1);
                ManagedWorkRuntime.Observed(pending[0].Task);
                foreach (var item in pending.Skip(1)) Complete(item);
                Finish(); break;
            }
            case "multiple-fault-conversions-retain-distinct-tokens": MultipleFaultConversionsControl(); break;
            case "fault-conversion-refusal-retains-both": FaultConversionControl(false); break;
            case "fault-conversion-unknown-retains-both": FaultConversionControl(true); break;
            case "storage-settlement-refusal-fences-root": RootSettlementControl(true, false); break;
            case "storage-settlement-unknown-fences-root": RootSettlementControl(true, true); break;
            case "root-settlement-refusal-fences-finalization": RootSettlementControl(false, false); break;
            case "root-settlement-unknown-fences-finalization": RootSettlementControl(false, true); break;
            case "root-context-clear-failure-fences-finalization": RootContextClearControl(false); break;
            case "storage-and-context-clear-fail-fences-finalization": RootContextClearControl(true); break;
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
        if (multipleConversionControl)
        {
            Console.WriteLine(JsonSerializer.Serialize(new { control = args[0], passed = true,
                registryCore = "production-source", nativeLedger = "explicit-test-port", dispatcher = "explicit-test-port",
                actualClrTasks = true, guestQualified = false, settlementRefusals = refusedSettlements,
                retainedTasks = Count(0), retainedResults = Count(6), rootSuccess = rootJoinReturned }));
            return;
        }
        if (rootSettlementControl)
        {
            Console.WriteLine(JsonSerializer.Serialize(new { control = args[0], passed = true,
                registryCore = "production-source", nativeLedger = "explicit-test-port", dispatcher = "explicit-test-port",
                actualClrTasks = true, guestQualified = false, settlementRefusals = refusedSettlements,
                retainedTasks = Count(0), retainedNativeOwners = Count(7), rootSettlements, storageSettlements,
                contextClearAttempts, finalizationSuccess = rootFinalizationReturned }));
            return;
        }
        if (settlementRefusal != 0)
        {
            Console.WriteLine(JsonSerializer.Serialize(new { control = args[0], passed = true,
                registryCore = "production-source", nativeLedger = "explicit-test-port", dispatcher = "explicit-test-port",
                actualClrTasks = true, guestQualified = false, settlementRefusals = refusedSettlements,
                retainedTasks = Count(0), retainedQueuedOwners = Count(3), controlDispatches,
                automaticRetries = refusedSettlements - 1, rootSuccess = rootJoinReturned }));
            return;
        }
        Console.WriteLine(JsonSerializer.Serialize(new { control = args[0], passed = true,
            registryCore = "production-source", nativeLedger = "explicit-test-port", dispatcher = "explicit-test-port",
            actualClrTasks = true, guestQualified = false }));
    }
}
