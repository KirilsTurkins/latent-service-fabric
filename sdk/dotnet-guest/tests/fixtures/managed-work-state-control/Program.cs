using Lsf.CompilerOwned;
using System.Text.Json;

internal static class StateControl
{
    internal static readonly Queue<Action> Work = new();
    internal static bool FailQueueAllocation;
    internal static readonly OutOfMemoryException QueueAllocationFailure = new("control-queue-allocation-failed");
    internal static Action? QueueAllocationCallback;
    internal static Action? RecordAllocationCallback;
    private static Action? QueueReserveCallback;
    private static Action? ResultReservationCallback, AfterSettlementCallback, AfterContextClearCallback, AfterContextRestoreCallback;
    private static ulong afterSettlementTarget, refuseContextRestore, afterContextRestoreTarget;
    private static bool contextThrowsBeforeRestore;
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
    private static int unknownReservationKind = -1;
    private static ulong unknownReservationToken;
    private static int malformedReservationKind = -1;
    private static bool malformedGeneration;
    private static readonly InvalidOperationException UnknownReservation = new("control-original-reservation-unknown");
    private static bool failOwnerRollback, unknownOwnerRollback;
    private static ulong rollbackOwner;
    private static int ownerRollbackAttempts;
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
        if (kind == 3 && QueueReserveCallback is { } callback)
        { QueueReserveCallback = null; callback(); }
        if (kind == 3 && failOwnerRollback)
        {
            rollbackOwner = Owners.Single(entry => entry.Value == 0 && entry.Key != context.Item2).Key;
            return default; // Explicit selected-bridge WIT refusal.
        }
        if (Count(kind) >= Limits[kind])
        {
            if (kind is 0 or 3 or 6) return default;
            throw new InvalidOperationException("control-ledger-capacity");
        }
        ulong key = checked(++sequence);
        Owners.Add(key, kind);
        maximumTasks = Math.Max(maximumTasks, Count(0)); maximumResults = Math.Max(maximumResults, Count(6));
        if (kind == 6 && ResultReservationCallback is { } resultCallback)
        { ResultReservationCallback = null; resultCallback(); }
        if (kind == unknownReservationKind)
        {
            unknownReservationToken = key;
            throw UnknownReservation;
        }
        if (kind == malformedReservationKind)
        {
            unknownReservationToken = key;
            return malformedGeneration ? (0UL, key) : (17UL, 0UL);
        }
        return (17, key);
    }
    private static void Settle(ulong generation, ulong id)
    {
        if (id == rootIdentifier) rootSettlements++;
        if (id == storageIdentifier) storageSettlements++;
        if (failOwnerRollback && id == rollbackOwner)
        {
            ownerRollbackAttempts++;
            if (unknownOwnerRollback) Need(Owners.Remove(id));
            throw new InvalidOperationException("control-owner-rollback-failed");
        }
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
        if (id == afterSettlementTarget && AfterSettlementCallback is { } callback)
        { AfterSettlementCallback = null; callback(); }
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
        if (refuseContextRestore != 0 && (generation, id) == (17UL, refuseContextRestore))
        {
            if (!contextThrowsBeforeRestore) context = (generation, id);
            throw new InvalidOperationException("control-context-restore-failed");
        }
        context = (generation, id);
        if (context == (0UL, 0UL) && AfterContextClearCallback is { } callback)
        { AfterContextClearCallback = null; callback(); }
        if (id == afterContextRestoreTarget && AfterContextRestoreCallback is { } restored)
        { AfterContextRestoreCallback = null; restored(); }
    }
    private static void Begin() => ManagedWorkRuntime.Install(Reserve, Settle, () => closing = true, Context);
    private static void Finish()
    {
        ManagedWorkRuntime.JoinAcceptedWork(); ManagedWorkRuntime.FinishedPhysicalDrain();
        Need(Owners.Count == 0 && context == (0UL, 0UL) && Work.Count == 0);
    }
    private static object? Enqueue(object item)
    {
        var ticket = ManagedWorkRuntime.Enqueue(item);
        ManagedWorkRuntime.EnqueueFinalized(ticket, 2);
        return ticket;
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
        if (callback) { Enqueue(item); ManagedWorkRuntime.Dequeue(item); }
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
        Refuses(() => Enqueue(item), "managed-work-owner-retired");
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
    private static void ResultTransitionObservationControl(string point)
    {
        var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
        var previous = ManagedWorkRuntime.Enter(pending.Task);
        ulong taskToken = context.Item2;
        pending.SetException(new ArgumentException("control-observed-transition"));
        int observations = 0;
        void Observe()
        {
            observations++;
            Need(context == (0UL, 0UL));
            ManagedWorkRuntime.Observed(pending.Task);
            Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
            Refuses(() => ManagedWorkRuntime.ContinuationFailed(pending.Task), "managed-work-double-settle");
            Refuses(() => ManagedWorkRuntime.Schedule(pending.Task), "managed-work-owner-retired");
            Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-parent-retired");
            Refuses(() => ManagedWorkRuntime.Enter(pending.Task), "managed-work-execution-parent");
            ManagedWorkRuntime.CallbackCompleted(pending.Task);
            Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-admission-in-progress");
            Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-admission-in-progress");
        }
        if (point == "clear") AfterContextClearCallback = Observe;
        else if (point == "reservation") ResultReservationCallback = Observe;
        else if (point == "task-settlement")
        { afterSettlementTarget = taskToken; AfterSettlementCallback = Observe; }
        else if (point == "result-settlement")
        {
            ResultReservationCallback = () =>
            {
                Observe();
                afterSettlementTarget = Owners.Single(entry => entry.Value == 6).Key;
                AfterSettlementCallback = Observe;
            };
        }
        else throw new InvalidOperationException("unknown-result-observation-point");
        ManagedWorkRuntime.Completed(pending.Task);
        Need(observations == (point == "result-settlement" ? 2 : 1)
            && Count(0) == 1 && Count(6) == 0 && context == (0UL, 0UL)
            && maximumResults == (point == "clear" ? 0 : 1));
        ManagedWorkRuntime.Exit(previous); Finish();
    }
    private static void ResultReservationFailureControl(string mode)
    {
        var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
        var previous = ManagedWorkRuntime.Enter(pending.Task);
        var original = context;
        pending.SetException(new ArgumentException("control-result-reservation"));
        if (mode == "refusal") Limits[6] = 0;
        else if (mode == "unknown") unknownReservationKind = 6;
        else { malformedReservationKind = 6; malformedGeneration = mode == "generation"; }
        if (mode == "unknown")
        {
            Exception? received = null;
            try { ManagedWorkRuntime.Completed(pending.Task); }
            catch (Exception error) { received = error; }
            Need(ReferenceEquals(received, UnknownReservation));
        }
        else Refuses(() => ManagedWorkRuntime.Completed(pending.Task),
            mode == "refusal" ? "managed-work-admission-refused" : "managed-work-reservation-token");
        if (mode == "refusal")
        {
            Need(context == original && Count(0) == 2 && Count(6) == 0);
            ManagedWorkRuntime.Exit(previous);
            ManagedWorkRuntime.Observed(pending.Task); ManagedWorkRuntime.Completed(pending.Task); Finish();
            return;
        }
        Need(context == (0UL, 0UL) && unknownReservationToken != 0
            && Owners.ContainsKey(unknownReservationToken) && Count(0) == 2 && Count(6) == 1);
        ManagedWorkRuntime.Observed(pending.Task);
        ManagedWorkRuntime.CallbackCompleted(pending.Task);
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
        ManagedWorkRuntime.Exit(previous);
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-double-settle");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(Count(0) == 2 && Count(6) == 1 && Owners.ContainsKey(unknownReservationToken));
    }
    private static void ResultContextFailureControl(bool restore, bool before)
    {
        var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
        var previous = ManagedWorkRuntime.Enter(pending.Task);
        var original = context;
        pending.SetException(new ArgumentException("control-result-context"));
        if (restore) { Limits[6] = 0; refuseContextRestore = original.Item2; contextThrowsBeforeRestore = before; }
        else { refuseContextClear = true; contextThrowsBeforeClear = before; }
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task),
            restore ? "managed-work-admission-refused" : "control-context-clear-failed");
        Need(context == (!restore && before ? original : (0UL, 0UL)) && Count(0) == 2 && Count(6) == 0);
        refuseContextRestore = 0; refuseContextClear = false;
        ManagedWorkRuntime.Observed(pending.Task); ManagedWorkRuntime.CallbackCompleted(pending.Task);
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
        ManagedWorkRuntime.Exit(previous);
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-double-settle");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(Count(0) == 2 && Count(6) == 0 && Owners.ContainsKey(original.Item2));
    }
    private static void ResultRefusalRestoreReentryControl()
    {
        var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
        var rootContext = ExecutionContext.Capture() ?? throw new InvalidOperationException("control-root-context");
        var rootAdapterContext = context;
        var previous = ManagedWorkRuntime.Enter(pending.Task);
        var original = context;
        pending.SetException(new ArgumentException("control-refusal-restoration"));
        Limits[6] = 0; afterContextRestoreTarget = original.Item2;
        bool observed = false, nestedContextRestored = false;
        AfterContextRestoreCallback = () =>
        {
            observed = true; Need(context == original);
            ManagedWorkRuntime.Observed(pending.Task);
            Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
            Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-parent-retired");
            Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-admission-in-progress");
            Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-admission-in-progress");
            // A nested execution context can replace native TLS and then
            // restore the still-inactive Task while this adapter call runs.
            ExecutionContext.Run(rootContext, _ => Need(context == rootAdapterContext), null);
            nestedContextRestored = context == original;
        };
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-admission-refused");
        Need(observed && nestedContextRestored && context == original && Count(0) == 2 && Count(6) == 0);
        ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.Completed(pending.Task); Finish();
    }
    private static void ResultDispatchSettlementFailureControl(bool unknown)
    {
        var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
        var previous = ManagedWorkRuntime.Enter(pending.Task);
        settlementRefusal = context.Item2; settlementUnknown = unknown;
        pending.SetException(new ArgumentException("control-dispatch-fault"));
        Exception? original = null; Exception? received = null;
        try
        {
            try { ManagedWorkRuntime.Completed(pending.Task); }
            catch (Exception error) { original = error; throw; }
            finally { ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.CallbackCompleted(pending.Task); }
        }
        catch (Exception error) { received = error; }
        Need(original is not null && ReferenceEquals(received, original)
            && original.Message == "managed-work-settlement-refused");
        ManagedWorkRuntime.Observed(pending.Task);
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-double-settle");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(refusedSettlements == 1 && Count(6) == 1 && Count(0) == (unknown ? 1 : 2));
    }
    private static void ObservedResultSettlementFailureControl(bool unknown)
    {
        var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
        var previous = ManagedWorkRuntime.Enter(pending.Task);
        pending.SetException(new ArgumentException("control-observed-result-settlement"));
        ResultReservationCallback = () =>
        {
            ManagedWorkRuntime.Observed(pending.Task);
            settlementRefusal = Owners.Single(entry => entry.Value == 6).Key;
            settlementUnknown = unknown;
        };
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-settlement-refused");
        ManagedWorkRuntime.Observed(pending.Task); ManagedWorkRuntime.CallbackCompleted(pending.Task);
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
        ManagedWorkRuntime.Exit(previous);
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-double-settle");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(refusedSettlements == 1 && Count(0) == 1 && Count(6) == (unknown ? 0 : 1));
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
    private static void QueueSettlementControl(bool unknown)
    {
        Limits[3] = 2;
        object item = new(); var ticket = Enqueue(item);
        var original = ManagedWorkRuntime.QueuedTokenForControl(item)
            ?? throw new InvalidOperationException("missing-original-control-queue-token");
        settlementRefusal = original.Id; settlementUnknown = unknown;
        Refuses(() => ManagedWorkRuntime.Dequeue(item), "managed-work-settlement-refused");
        Refuses(() => ManagedWorkRuntime.Dequeue(item), "managed-work-queue-uncertain");
        ManagedWorkRuntime.EnqueueFinalized(ticket, 0);
        Refuses(() => Enqueue(item), "managed-work-queue-uncertain");
        object other = new(); Enqueue(other);
        ManagedWorkRuntime.Dequeue(other); ManagedWorkRuntime.CallbackCompleted(other);
        Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; },
            "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!rootJoinReturned && refusedSettlements == 1 && Count(0) == 2 && Count(3) == (unknown ? 0 : 1)
            && ManagedWorkRuntime.QueuedTokenForControl(item) == original
            && Owners.ContainsKey(original.Id) != unknown && Work.Count == 0);
    }
    private static void BeforeInsertionSettlementControl(bool unknown)
    {
        object item = new(); var ticket = ManagedWorkRuntime.Enqueue(item);
        var queueToken = ManagedWorkRuntime.QueuedTokenForControl(item)
            ?? throw new InvalidOperationException("missing-original-control-queue-token");
        settlementRefusal = queueToken.Id; settlementUnknown = unknown;
        bool originalFailure = false;
        try
        {
            try { throw new InvalidOperationException("control-original-enqueue-failure"); }
            catch { ManagedWorkRuntime.EnqueueFinalized(ticket, 0); throw; }
        }
        catch (InvalidOperationException error) when (error.Message == "control-original-enqueue-failure")
        { originalFailure = true; }
        Need(originalFailure && refusedSettlements == 1);
        ManagedWorkRuntime.EnqueueFinalized(ticket, 0);
        Need(Count(3) == (unknown ? 0 : 1) && Count(0) == 2
            && ManagedWorkRuntime.QueuedTokenForControl(item) == queueToken);
        Refuses(() => ManagedWorkRuntime.Dequeue(item), "managed-work-queue-uncertain");
        Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; },
            "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!rootJoinReturned && refusedSettlements == 1);
    }
    private static void BeforeInsertionReentrantControl(bool captured)
    {
        Limits[3] = 2;
        object item = new(); var ticket = ManagedWorkRuntime.Enqueue(item);
        var previous = ManagedWorkRuntime.Enter(item);
        ulong owner = context.Item2;
        var continuation = Pending();
        var saved = captured ? ExecutionContext.Capture() : null;
        if (!captured)
        {
            ManagedWorkRuntime.CreatedAsync(continuation.Task);
            Enqueue(continuation.Task);
        }
        ManagedWorkRuntime.Exit(previous);
        ManagedWorkRuntime.EnqueueFinalized(ticket, 0);
        Need(Count(0) == 2 && Owners.ContainsKey(owner) && Count(3) == (captured ? 0 : 1));
        if (captured)
        {
            Need(saved is not null);
            ExecutionContext.Run(saved!, _ =>
            {
                Need(context == (17UL, owner));
                ManagedWorkRuntime.CreatedAsync(continuation.Task);
                Enqueue(continuation.Task);
            }, null);
        }
        Need(Count(3) == 1 && !continuation.Task.IsCompleted);
        ManagedWorkRuntime.Dequeue(continuation.Task);
        previous = ManagedWorkRuntime.Enter(continuation.Task);
        try { Need(context == (17UL, owner) && Owners.ContainsKey(owner)); }
        finally { ManagedWorkRuntime.Exit(previous); }
        continuation.SetResult(1);
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(Count(0) == 2 && Count(3) == 0 && Owners.ContainsKey(owner));
    }
    private static void PreTicketUnknownReservationControl(bool queue)
    {
        unknownReservationKind = queue ? 3 : 0;
        bool observedOriginal = false;
        try { ManagedWorkRuntime.Enqueue(new object()); }
        catch (InvalidOperationException error) when (ReferenceEquals(error, UnknownReservation)) { observedOriginal = true; }
        Need(observedOriginal && unknownReservationToken != 0 && Owners.ContainsKey(unknownReservationToken));
        try { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; }
        catch (InvalidOperationException) { }
        Need(!rootJoinReturned);
        try { ManagedWorkRuntime.FinishedPhysicalDrain(); rootFinalizationReturned = true; }
        catch (InvalidOperationException) { }
        Need(!rootFinalizationReturned && Owners.ContainsKey(unknownReservationToken));
    }
    private static void PreTicketRollbackFailureControl(bool unknown)
    {
        failOwnerRollback = true; unknownOwnerRollback = unknown;
        Refuses(() => ManagedWorkRuntime.Enqueue(new object()), "managed-work-admission-refused");
        try { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; }
        catch (InvalidOperationException) { }
        Need(!rootJoinReturned && !rootFinalizationReturned && ownerRollbackAttempts == 1);
    }
    private static void PreTicketBorrowedOwnerControl()
    {
        var source = Pending(); ManagedWorkRuntime.Schedule(source.Task);
        unknownReservationKind = 3;
        bool observedOriginal = false;
        try { ManagedWorkRuntime.Enqueue(source.Task); }
        catch (InvalidOperationException error) when (ReferenceEquals(error, UnknownReservation)) { observedOriginal = true; }
        Need(observedOriginal && Owners.ContainsKey(unknownReservationToken));
        source.SetResult(1); ManagedWorkRuntime.Completed(source.Task);
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-queue");
        Need(Owners.ContainsKey(unknownReservationToken));
    }
    private static void TaskAdmissionUnknownControl(bool unwrap)
    {
        var promise = Pending(); var outer = Pending();
        unknownReservationKind = 0;
        bool observedOriginal = false;
        try
        {
            if (unwrap) ManagedWorkRuntime.Unwrap(promise.Task, outer.Task);
            else ManagedWorkRuntime.Schedule(promise.Task);
        }
        catch (InvalidOperationException error) when (ReferenceEquals(error, UnknownReservation)) { observedOriginal = true; }
        Need(observedOriginal && unknownReservationToken != 0 && Owners.ContainsKey(unknownReservationToken));
        Refuses(() => ManagedWorkRuntime.Schedule(promise.Task), "managed-work-owner-retired");
        Refuses(() => ManagedWorkRuntime.Unwrap(promise.Task, outer.Task), "managed-work-owner-retired");
        Refuses(() => ManagedWorkRuntime.Inner(promise.Task, outer.Task), "managed-work-owner-retired");
        Refuses(() => ManagedWorkRuntime.Enqueue(promise.Task), "managed-work-owner-retired");
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(Owners.ContainsKey(unknownReservationToken));
    }
    private static void PreTicketAllocationFailureControl()
    {
        FailQueueAllocation = true;
        bool observedOriginal = false;
        try { ManagedWorkRuntime.Enqueue(new object()); }
        catch (OutOfMemoryException error) when (ReferenceEquals(error, QueueAllocationFailure)) { observedOriginal = true; }
        Need(observedOriginal && Count(0) == 1 && Count(3) == 0);
        Finish();
    }
    private sealed class ContextItem(Action callback) : ManagedWorkRuntime.ContextSource
    {
        public ExecutionContext? CapturedContext() { callback(); return null; }
    }
    private sealed class ContextTask(Action<ContextTask> callback, bool fault = false)
        : Task(() => { if (fault) throw new InvalidOperationException("control-reentrant-task-fault"); }), ManagedWorkRuntime.ContextSource
    {
        public ExecutionContext? CapturedContext() { callback(this); return null; }
    }
    private static void ContextReentryQueueControl(bool failure)
    {
        Limits[3] = 2; object other = new();
        var original = new InvalidOperationException("control-original-context-failure");
        var item = new ContextItem(() => { Enqueue(other); if (failure) throw original; });
        if (failure)
        {
            bool observedOriginal = false;
            try { Enqueue(item); }
            catch (InvalidOperationException error) when (ReferenceEquals(error, original)) { observedOriginal = true; }
            Need(observedOriginal && Count(3) == 1 && ManagedWorkRuntime.QueuedTokenForControl(item) is null);
        }
        else
        {
            Enqueue(item);
            Need(Count(3) == 2 && ManagedWorkRuntime.QueuedTokenForControl(item) is { } current
                && ManagedWorkRuntime.QueuedTokenForControl(other) is { } nested && current != nested);
            ManagedWorkRuntime.Dequeue(item); ManagedWorkRuntime.CallbackCompleted(item);
        }
        ManagedWorkRuntime.Dequeue(other); ManagedWorkRuntime.CallbackCompleted(other); Finish();
    }
    private static void ContextReentryTaskControl(bool unwrap)
    {
        var outer = Pending();
        var task = new ContextTask(item =>
        {
            if (unwrap) ManagedWorkRuntime.Unwrap(item, outer.Task);
            else ManagedWorkRuntime.Schedule(item);
        });
        Enqueue(task);
        Need(Count(0) == 2 && Count(3) == 1);
        ManagedWorkRuntime.Dequeue(task); task.RunSynchronously(); ManagedWorkRuntime.Completed(task); Finish();
    }
    private static void ContextReentrySameItemControl()
    {
        ContextItem? item = null;
        item = new ContextItem(() => Refuses(() => Enqueue(item!), "managed-work-queue-uncertain"));
        Enqueue(item); Need(Count(3) == 1);
        ManagedWorkRuntime.Dequeue(item); ManagedWorkRuntime.CallbackCompleted(item); Finish();
    }
    private static void ContextReentryResultControl()
    {
        var task = new ContextTask(item =>
        {
            ManagedWorkRuntime.Schedule(item); item.RunSynchronously(); ManagedWorkRuntime.Completed(item);
        }, fault: true);
        Refuses(() => Enqueue(task), "managed-work-owner-retired");
        Need(Count(0) == 1 && Count(6) == 1 && Count(3) == 0);
        ManagedWorkRuntime.Observed(task); Finish();
    }
    private static void ContextReentryDrainControl()
    {
        var item = new ContextItem(() =>
        {
            Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-admission-in-progress");
            Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-admission-in-progress");
        });
        Enqueue(item); ManagedWorkRuntime.Dequeue(item); ManagedWorkRuntime.CallbackCompleted(item); Finish();
    }
    private static void DormantOwnerRefusalControl()
    {
        Limits[3] = 0;
        Task item = Task.FromResult(9); var outer = Pending();
        QueueReserveCallback = () =>
        {
            Refuses(() => ManagedWorkRuntime.Schedule(item), "managed-work-owner-retired");
            Refuses(() => ManagedWorkRuntime.Unwrap(item, outer.Task), "managed-work-owner-retired");
            Refuses(() => ManagedWorkRuntime.Inner(item, outer.Task), "managed-work-owner-retired");
            Refuses(() => ManagedWorkRuntime.Enter(item), "managed-work-execution-parent");
            Refuses(() => ManagedWorkRuntime.EnterDispatch(item), "managed-work-execution-parent");
            Refuses(() => ManagedWorkRuntime.BindContext(ExecutionContext.Capture(), item), "managed-work-context-owner");
            Refuses(() => ManagedWorkRuntime.ContinuationFailed(item), "managed-work-double-settle");
            Refuses(() => ManagedWorkRuntime.Completed(item), "managed-work-double-settle");
            Refuses(() => ManagedWorkRuntime.Observed(item), "managed-work-double-settle");
            Refuses(() => ManagedWorkRuntime.CallbackCompleted(item), "managed-work-double-settle");
            Refuses(() => ManagedWorkRuntime.Dequeue(item), "managed-work-queue-uncertain");
        };
        Refuses(() => Enqueue(item), "managed-work-admission-refused");
        Need(Count(0) == 1 && Count(3) == 0); Finish();
    }
    private static void QueueAllocationReentryControl()
    {
        object item = new();
        QueueAllocationCallback = () => Enqueue(item);
        Refuses(() => Enqueue(item), "managed-work-duplicate-enqueue");
        Need(Count(0) == 2 && Count(3) == 1);
        ManagedWorkRuntime.Dequeue(item); ManagedWorkRuntime.CallbackCompleted(item); Finish();
    }
    private static void RecordAllocationReentryControl(bool sameItem, bool result)
    {
        Task item = new(() => { if (result) throw new InvalidOperationException("control-record-reentry-fault"); });
        var other = Pending();
        RecordAllocationCallback = () =>
        {
            if (sameItem || result) ManagedWorkRuntime.Schedule(item);
            else ManagedWorkRuntime.Schedule(other.Task);
            if (result) { item.RunSynchronously(); ManagedWorkRuntime.Completed(item); }
        };
        if (result)
        {
            Refuses(() => Enqueue(item), "managed-work-owner-retired");
            Need(Count(0) == 1 && Count(6) == 1 && Count(3) == 0);
            ManagedWorkRuntime.Observed(item); Finish(); return;
        }
        Enqueue(item);
        Need(Count(0) == (sameItem ? 2 : 3) && Count(3) == 1);
        ManagedWorkRuntime.Dequeue(item); item.RunSynchronously();
        if (sameItem) ManagedWorkRuntime.Completed(item); else ManagedWorkRuntime.CallbackCompleted(item);
        if (!sameItem) Complete(other);
        Finish();
    }
    private static void ScheduleAllocationReentryControl()
    {
        Task item = new(() => { });
        RecordAllocationCallback = () => ManagedWorkRuntime.Schedule(item);
        ManagedWorkRuntime.Schedule(item); Need(Count(0) == 2);
        item.RunSynchronously(); ManagedWorkRuntime.Completed(item); Finish();
    }
    private static void RecordAllocationParentControl(bool result)
    {
        var pending = Pending(); object parentItem;
        if (result)
        {
            ManagedWorkRuntime.Schedule(pending.Task); parentItem = pending.Task;
        }
        else
        {
            parentItem = new object(); Enqueue(parentItem); ManagedWorkRuntime.Dequeue(parentItem);
        }
        var previous = ManagedWorkRuntime.Enter(parentItem);
        RecordAllocationCallback = () =>
        {
            if (result) { pending.SetException(new ArgumentException("control-parent-fault")); ManagedWorkRuntime.Completed(pending.Task); }
            else ManagedWorkRuntime.CallbackCompleted(parentItem);
        };
        Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-parent-retired");
        ManagedWorkRuntime.Exit(previous);
        if (result) ManagedWorkRuntime.Observed(pending.Task);
        Need(Count(0) == 1 && Count(6) == 0); Finish();
    }
    private static void RecordAllocationClosingControl()
    {
        RecordAllocationCallback = () =>
        {
            Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-admission-in-progress");
            Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-admission-in-progress");
        };
        var pending = Pending(); ManagedWorkRuntime.Schedule(pending.Task);
        Complete(pending); Finish();
    }
    private static void AllocationFinalizationControl(string operation)
    {
        ulong originalRoot = context.Item2;
        bool admissionFenced = false;
        void Reenter()
        {
            try
            {
                ManagedWorkRuntime.JoinAcceptedWork();
                ManagedWorkRuntime.FinishedPhysicalDrain();
                closing = false; Begin(); // A fresh activation must not replace the original.
            }
            catch (InvalidOperationException error) when (error.Message == "managed-work-admission-in-progress")
            { admissionFenced = true; }
            Need(admissionFenced && context.Item2 == originalRoot);
            Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-admission-in-progress");
            Refuses(Begin, "managed-work-installation");
        }
        if (operation == "queue")
        {
            object item = new(); QueueAllocationCallback = Reenter;
            Enqueue(item); ManagedWorkRuntime.Dequeue(item); ManagedWorkRuntime.CallbackCompleted(item);
        }
        else
        {
            var promise = Pending(); var outer = Pending(); RecordAllocationCallback = Reenter;
            if (operation == "schedule") ManagedWorkRuntime.Schedule(promise.Task);
            else ManagedWorkRuntime.Unwrap(promise.Task, outer.Task);
            Complete(promise);
        }
        Need(admissionFenced && context.Item2 == originalRoot); Finish();
    }
    private static void PreTicketMalformedReservationControl(bool queue, bool generation)
    {
        malformedReservationKind = queue ? 3 : 0;
        malformedGeneration = generation;
        Refuses(() => ManagedWorkRuntime.Enqueue(new object()), "managed-work-reservation-token");
        Need(unknownReservationToken != 0 && Owners.ContainsKey(unknownReservationToken));
        try { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; }
        catch (InvalidOperationException) { }
        Need(!rootJoinReturned);
        try { ManagedWorkRuntime.FinishedPhysicalDrain(); rootFinalizationReturned = true; }
        catch (InvalidOperationException) { }
        Need(!rootFinalizationReturned && Owners.ContainsKey(unknownReservationToken));
    }
    private static void Run(string name)
    {
        if (name == "untracked-startup-refused-before-admission")
        {
            Work.Enqueue(() => { }); Refuses(Begin, "managed-work-untracked-startup-work");
            Need(Owners.Count == 0); return;
        }
        if (name == "root-task-refusal-fences-reinstallation")
        {
            Limits[0] = 0;
            Refuses(Begin, "managed-work-admission-refused");
            Need(Owners.Count == 0 && Count(7) == 0);
            Refuses(Begin, "managed-work-installation");
            Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-state");
            return;
        }
        if (name == "root-task-unknown-fences-reinstallation")
        {
            unknownReservationKind = 0;
            bool observedOriginal = false;
            try { Begin(); }
            catch (InvalidOperationException error) when (ReferenceEquals(error, UnknownReservation)) { observedOriginal = true; }
            Need(observedOriginal && unknownReservationToken != 0
                && Owners.ContainsKey(unknownReservationToken) && Count(7) == 0);
            Refuses(Begin, "managed-work-installation");
            Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-state");
            return;
        }
        if (name is "root-task-malformed-generation-fences-reinstallation" or "root-task-malformed-id-fences-reinstallation")
        {
            malformedReservationKind = 0;
            malformedGeneration = name.Contains("generation");
            Refuses(Begin, "managed-work-reservation-token");
            Need(unknownReservationToken != 0 && Owners.ContainsKey(unknownReservationToken) && Count(7) == 0);
            Refuses(Begin, "managed-work-installation");
            Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-state");
            return;
        }
        Begin();
        switch (name)
        {
            case "native-task-admission": {
                Limits[0] = 2;
                var first = Pending(); ManagedWorkRuntime.Schedule(first.Task);
                Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-admission-refused");
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
                object first = new(), second = new(); Enqueue(first);
                Refuses(() => Enqueue(second), "managed-work-admission-refused");
                Need(Count(0) == 2 && Count(3) == 1);
                ManagedWorkRuntime.Dequeue(first); var previous = ManagedWorkRuntime.Enter(first);
                try { Need(Count(0) == 2 && Count(3) == 0); }
                finally { ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.CallbackCompleted(first); }
                object fresh = new(); Enqueue(fresh); ManagedWorkRuntime.Dequeue(fresh);
                ManagedWorkRuntime.CallbackCompleted(fresh);
                Finish(); break;
            }
            case "enqueue-failure-retains-uncertain-owners": {
                object item = new(); var ticket = ManagedWorkRuntime.Enqueue(item);
                ManagedWorkRuntime.EnqueueFinalized(ticket, 1);
                Need(Count(0) == 2 && Count(3) == 1);
                Refuses(() => ManagedWorkRuntime.Dequeue(item), "managed-work-queue-uncertain");
                Refuses(() => Enqueue(item), "managed-work-queue-uncertain");
                Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
                Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
                Need(Count(0) == 2 && Count(3) == 1); break;
            }
            case "enqueue-before-insertion-retains-created-owner": {
                object item = new(); var ticket = ManagedWorkRuntime.Enqueue(item);
                ManagedWorkRuntime.EnqueueFinalized(ticket, 0);
                Need(Count(0) == 2 && Count(3) == 0);
                Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
                Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners"); break;
            }
            case "enqueue-before-insertion-keeps-borrowed-owner": {
                var actual = Pending(); ManagedWorkRuntime.Schedule(actual.Task);
                var ticket = ManagedWorkRuntime.Enqueue(actual.Task);
                ManagedWorkRuntime.EnqueueFinalized(ticket, 0);
                Need(Count(0) == 2 && Count(3) == 0 && !actual.Task.IsCompleted);
                Complete(actual); Finish(); break;
            }
            case "enqueue-before-insertion-retains-reentrant-work": BeforeInsertionReentrantControl(false); break;
            case "enqueue-before-insertion-retains-captured-context": BeforeInsertionReentrantControl(true); break;
            case "pre-ticket-queue-reservation-unknown-fences-drain": PreTicketUnknownReservationControl(true); break;
            case "pre-ticket-task-reservation-unknown-fences-drain": PreTicketUnknownReservationControl(false); break;
            case "pre-ticket-borrowed-owner-unknown-fences-drain": PreTicketBorrowedOwnerControl(); break;
            case "schedule-unknown-reservation-fences-retry": TaskAdmissionUnknownControl(false); break;
            case "unwrap-unknown-reservation-fences-retry": TaskAdmissionUnknownControl(true); break;
            case "pre-ticket-owner-rollback-refusal-preserves-error": PreTicketRollbackFailureControl(false); break;
            case "pre-ticket-owner-rollback-unknown-preserves-error": PreTicketRollbackFailureControl(true); break;
            case "pre-ticket-queue-allocation-fails-before-owner": PreTicketAllocationFailureControl(); break;
            case "queue-allocation-reentry-before-scan": QueueAllocationReentryControl(); break;
            case "context-reentry-keeps-other-queued-item": ContextReentryQueueControl(false); break;
            case "context-reentry-error-keeps-other-queued-item": ContextReentryQueueControl(true); break;
            case "context-reentry-reuses-scheduled-task": ContextReentryTaskControl(false); break;
            case "context-reentry-reuses-unwrapped-task": ContextReentryTaskControl(true); break;
            case "context-reentry-same-item-is-fenced": ContextReentrySameItemControl(); break;
            case "context-reentry-result-owner-is-fenced": ContextReentryResultControl(); break;
            case "context-reentry-drain-fences-null-owner": ContextReentryDrainControl(); break;
            case "queue-refusal-dormant-owner-fences-entry": DormantOwnerRefusalControl(); break;
            case "record-allocation-reuses-same-task": RecordAllocationReentryControl(true, false); break;
            case "record-allocation-preserves-other-task": RecordAllocationReentryControl(false, false); break;
            case "record-allocation-fences-result-owner": RecordAllocationReentryControl(false, true); break;
            case "schedule-allocation-reuses-same-task": ScheduleAllocationReentryControl(); break;
            case "record-allocation-retired-parent-is-fenced": RecordAllocationParentControl(false); break;
            case "record-allocation-result-parent-is-fenced": RecordAllocationParentControl(true); break;
            case "record-allocation-closing-root-is-fenced": RecordAllocationClosingControl(); break;
            case "queue-allocation-finalization-is-fenced": AllocationFinalizationControl("queue"); break;
            case "schedule-allocation-finalization-is-fenced": AllocationFinalizationControl("schedule"); break;
            case "unwrap-allocation-finalization-is-fenced": AllocationFinalizationControl("unwrap"); break;
            case "pre-ticket-queue-malformed-generation-fences-drain": PreTicketMalformedReservationControl(true, true); break;
            case "pre-ticket-queue-malformed-id-fences-drain": PreTicketMalformedReservationControl(true, false); break;
            case "pre-ticket-task-malformed-generation-fences-drain": PreTicketMalformedReservationControl(false, true); break;
            case "pre-ticket-task-malformed-id-fences-drain": PreTicketMalformedReservationControl(false, false); break;
            case "queue-before-insertion-refusal-retains-owner": BeforeInsertionSettlementControl(false); break;
            case "queue-before-insertion-unknown-retains-owner": BeforeInsertionSettlementControl(true); break;
            case "queue-dequeue-refusal-prevents-retry": QueueSettlementControl(false); break;
            case "queue-dequeue-unknown-prevents-retry": QueueSettlementControl(true); break;
            case "dequeue-settlement-refusal-retains-owner": {
                object item = new(); Enqueue(item);
                var original = ManagedWorkRuntime.QueuedTokenForControl(item)
                    ?? throw new InvalidOperationException("missing-original-control-queue-token");
                settlementRefusal = original.Id;
                Need(Count(0) == 2 && Count(3) == 1 && original.Generation == 17);
                Refuses(() => ManagedWorkRuntime.Dequeue(item), "managed-work-settlement-refused");
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
            case "result-observed-during-context-clear": ResultTransitionObservationControl("clear"); break;
            case "result-observed-during-reservation": ResultTransitionObservationControl("reservation"); break;
            case "result-observed-during-task-settlement": ResultTransitionObservationControl("task-settlement"); break;
            case "result-observed-during-result-settlement": ResultTransitionObservationControl("result-settlement"); break;
            case "result-reservation-refusal-restores-owner": ResultReservationFailureControl("refusal"); break;
            case "result-reservation-unknown-retains-custody": ResultReservationFailureControl("unknown"); break;
            case "result-reservation-malformed-generation-retains-custody": ResultReservationFailureControl("generation"); break;
            case "result-reservation-malformed-id-retains-custody": ResultReservationFailureControl("id"); break;
            case "result-context-clear-failure-before-mutation": ResultContextFailureControl(false, true); break;
            case "result-context-clear-failure-after-mutation": ResultContextFailureControl(false, false); break;
            case "result-context-restore-failure-before-mutation": ResultContextFailureControl(true, true); break;
            case "result-context-restore-failure-after-mutation": ResultContextFailureControl(true, false); break;
            case "result-refusal-restore-observation-and-reentry": ResultRefusalRestoreReentryControl(); break;
            case "fault-dispatch-settlement-refusal-preserves-error": ResultDispatchSettlementFailureControl(false); break;
            case "fault-dispatch-settlement-unknown-preserves-error": ResultDispatchSettlementFailureControl(true); break;
            case "observed-result-settlement-refusal-retains-custody": ObservedResultSettlementFailureControl(false); break;
            case "observed-result-settlement-unknown-retains-custody": ObservedResultSettlementFailureControl(true); break;
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
                object item = new(); Enqueue(item);
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
                object callback = new(); var actual = Pending(); Enqueue(callback);
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
