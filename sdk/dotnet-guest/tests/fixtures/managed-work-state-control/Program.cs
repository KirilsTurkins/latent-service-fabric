using Lsf.CompilerOwned;
using System.Text.Json;

internal static class StateControl
{
    internal static readonly Queue<Action> Work = new();
    internal static bool FailQueueAllocation;
    internal static readonly OutOfMemoryException QueueAllocationFailure = new("control-queue-allocation-failed");
    internal static Action? QueueAllocationCallback;
    internal static Action? RecordAllocationCallback;
    internal static Action? RequiredPublishedCallback, RequiredReservedCallback;
    internal static Action? StartupAllocationCallback, StartupRootPublishedCallback;
    private static Action? QueueReserveCallback;
    private static Action? ResultReservationCallback, AfterSettlementCallback, AfterContextClearCallback, AfterContextRestoreCallback, AfterContextFenceCallback;
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
    private static int bridgeZeroBothKind = -1;
    private static bool malformedGeneration;
    private static readonly InvalidOperationException UnknownReservation = new("control-original-reservation-unknown");
    private static readonly InvalidOperationException StartupContextError = new("control-startup-context-error");
    private static readonly InvalidOperationException StartupCleanupError = new("control-startup-cleanup-error");
    private static readonly OutOfMemoryException StartupAllocationError = new("control-startup-allocation-error");
    private static readonly InvalidOperationException StartupReadinessError = new("control-startup-readiness-error");
    private static Action? StartupReserveCallback, StartupContextCallback, StartupReadinessCallback;
    private static bool startupInspect, startupContextFailure, startupContextBefore, startupClearFailure,
        startupClearBefore, startupNativeCleanupFailure, startupRootCleanupFailure, startupCleanupAfter;
    private static ulong startupRoot, startupNative, startupExtra;
    private static int startupRootAttempts, startupNativeAttempts;
    private static int readinessCalls, failReadinessAt;
    private static bool failOwnerRollback, unknownOwnerRollback;
    private static ulong rollbackOwner;
    private static int ownerRollbackAttempts;
    private static int controlDispatches;
    private static bool rootJoinReturned;
    private static bool rootSettlementControl, multipleConversionControl;
    private static bool rootFinalizationReturned;
    private static bool captureTaskParent;
    private static (ulong, ulong) capturedTaskParent;
    private static bool refuseContextClear, contextThrowsBeforeClear, refuseContextFence, contextFenceThrowsAfter;
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
        if (context == (0UL, 1UL)) return default; // The selected Rust bridge refuses before the host call.
        if (kind == 0 && captureTaskParent) capturedTaskParent = (generation, id);
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
            if (kind == 6 && ResultReservationCallback is { } refused)
            { ResultReservationCallback = null; refused(); }
            if (startupInspect && kind == 7 && StartupReserveCallback is { } startupRefused)
            { StartupReserveCallback = null; startupRefused(); }
            if (kind is 0 or 3 or 6 or 7) return default;
            throw new InvalidOperationException("control-ledger-capacity");
        }
        ulong key = checked(++sequence);
        Owners.Add(key, kind);
        if (startupInspect && kind == 0 && startupRoot == 0) startupRoot = key;
        if (startupInspect && kind == 7)
        { if (startupNative == 0) startupNative = key; else startupExtra = key; }
        maximumTasks = Math.Max(maximumTasks, Count(0)); maximumResults = Math.Max(maximumResults, Count(6));
        if (startupInspect && StartupReserveCallback is { } startup)
        { StartupReserveCallback = null; startup(); }
        if (kind == 6 && ResultReservationCallback is { } resultCallback)
        { ResultReservationCallback = null; resultCallback(); }
        if (kind == unknownReservationKind)
        {
            unknownReservationToken = key;
            throw UnknownReservation;
        }
        if (kind == bridgeZeroBothKind)
        {
            unknownReservationToken = key;
            throw new InvalidOperationException("managed-work-reservation-token");
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
        if (startupInspect && id == startupRoot) startupRootAttempts++;
        if (startupInspect && id == startupNative) startupNativeAttempts++;
        if (startupInspect && ((id == startupRoot && startupRootCleanupFailure)
            || (id == startupNative && startupNativeCleanupFailure)))
        {
            if (startupCleanupAfter) Need(Owners.Remove(id)); else Need(Owners.ContainsKey(id));
            throw StartupCleanupError;
        }
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
    internal static bool ReadyForControl()
    {
        readinessCalls++;
        if (readinessCalls == 1 && StartupReadinessCallback is { } callback)
        { StartupReadinessCallback = null; callback(); }
        if (readinessCalls == failReadinessAt) throw StartupReadinessError;
        return Work.Count != 0;
    }
    private static void Context(ulong generation, ulong id)
    {
        if ((generation, id) == (0UL, 1UL) && refuseContextFence && !contextFenceThrowsAfter)
            throw new InvalidOperationException("control-context-fence-failed");
        if (startupInspect && generation == 17 && id == startupRoot)
        {
            if (startupContextFailure && startupContextBefore) throw StartupContextError;
            context = (generation, id);
            if (StartupContextCallback is { } startupCallback)
            { StartupContextCallback = null; startupCallback(); }
            if (startupContextFailure) throw StartupContextError;
            return;
        }
        if (startupInspect && startupClearFailure && (generation, id) == (0UL, 0UL))
        {
            if (!startupClearBefore) context = (generation, id);
            throw StartupCleanupError;
        }
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
        if (context == (0UL, 1UL) && refuseContextFence && contextFenceThrowsAfter)
            throw new InvalidOperationException("control-context-fence-failed");
        if (context == (0UL, 1UL) && AfterContextFenceCallback is { } fenced)
        { AfterContextFenceCallback = null; fenced(); }
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
    private static (object Callback, TaskCompletionSource<int> Required) RequiredFaultParent()
    {
        object callback = new(); Enqueue(callback); ManagedWorkRuntime.Dequeue(callback);
        var previous = ManagedWorkRuntime.Enter(callback);
        var pending = Pending(); ManagedWorkRuntime.CreatedAsync(pending.Task);
        pending.SetException(new ArgumentException("control-required-result-fault"));
        ManagedWorkRuntime.Exit(previous);
        return (callback, pending);
    }
    private static void RequiredResultObservationControl(string point)
    {
        var (callback, pending) = RequiredFaultParent(); int observations = 0;
        void Observe()
        {
            observations++;
            ManagedWorkRuntime.Observed(pending.Task);
            if (point != "allocation")
                Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
            // Recursive completion of the parent must keep it alive and must
            // not reserve a second Result for this same Required entry.
            ManagedWorkRuntime.CallbackCompleted(callback);
            Need(Count(0) == 2);
            Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-admission-in-progress");
            Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-admission-in-progress");
        }
        if (point == "allocation") RecordAllocationCallback = Observe;
        else if (point == "published") RequiredPublishedCallback = Observe;
        else if (point == "reserve") ResultReservationCallback = Observe;
        else if (point == "returned") RequiredReservedCallback = Observe;
        else if (point == "settle") ResultReservationCallback = () =>
        {
            Observe(); afterSettlementTarget = Owners.Single(entry => entry.Value == 6).Key;
            AfterSettlementCallback = Observe;
        };
        else throw new InvalidOperationException("unknown-required-result-observation");
        ManagedWorkRuntime.CallbackCompleted(callback);
        Need(observations == (point == "settle" ? 2 : 1) && Count(0) == 1 && Count(6) == 0
            && maximumResults == (point is "allocation" or "published" ? 0 : 1));
        Finish();
    }
    private static void RequiredResultUnknownControl(string mode)
    {
        var (callback, pending) = RequiredFaultParent();
        if (mode == "unknown") unknownReservationKind = 6;
        else { malformedReservationKind = 6; malformedGeneration = mode == "generation"; }
        Exception? received = null;
        try { ManagedWorkRuntime.CallbackCompleted(callback); } catch (Exception error) { received = error; }
        Need(mode == "unknown" ? ReferenceEquals(received, UnknownReservation)
            : received is InvalidOperationException && received.Message == "managed-work-reservation-token");
        Need(unknownReservationToken != 0 && Owners.ContainsKey(unknownReservationToken)
            && Count(0) == 2 && Count(6) == 1);
        // The parent remains active because it still owns this Required entry.
        var previous = ManagedWorkRuntime.Enter(callback); ManagedWorkRuntime.Exit(previous);
        ManagedWorkRuntime.Observed(pending.Task); ManagedWorkRuntime.CallbackCompleted(pending.Task);
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
        Refuses(() => ManagedWorkRuntime.CallbackCompleted(callback), "managed-work-required-result-uncertain");
        Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; },
            "managed-work-required-result-uncertain");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!rootJoinReturned && Count(0) == 2 && Count(6) == 1 && Owners.ContainsKey(unknownReservationToken));
    }
    private static void RequiredResultRefusalControl()
    {
        var (callback, pending) = RequiredFaultParent(); Limits[6] = 0;
        ResultReservationCallback = () =>
        {
            ManagedWorkRuntime.Observed(pending.Task); ManagedWorkRuntime.CallbackCompleted(callback);
            Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
            Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-admission-in-progress");
        };
        Refuses(() => ManagedWorkRuntime.CallbackCompleted(callback), "managed-work-admission-refused");
        Need(Count(0) == 2 && Count(6) == 0);
        ManagedWorkRuntime.CallbackCompleted(callback); Finish();
    }
    private static void RequiredResultTransportControl(bool afterReservation)
    {
        var (callback, pending) = RequiredFaultParent();
        void Transport()
        {
            ManagedWorkRuntime.RequiredTransport(pending.Task);
            ManagedWorkRuntime.CallbackCompleted(callback);
            Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-admission-in-progress");
        }
        if (afterReservation) ResultReservationCallback = Transport;
        else RequiredPublishedCallback = Transport;
        ManagedWorkRuntime.CallbackCompleted(callback);
        Need(Count(0) == 1 && Count(6) == 0 && maximumResults == (afterReservation ? 1 : 0));
        Finish();
    }
    private static void RequiredResultAllocationFailureControl()
    {
        var (callback, pending) = RequiredFaultParent();
        var original = new OutOfMemoryException("control-required-result-allocation");
        RecordAllocationCallback = () => throw original;
        Exception? received = null;
        try { ManagedWorkRuntime.CallbackCompleted(callback); } catch (Exception error) { received = error; }
        Need(ReferenceEquals(received, original) && Count(0) == 2 && Count(6) == 0);
        ManagedWorkRuntime.Observed(pending.Task); ManagedWorkRuntime.CallbackCompleted(callback); Finish();
    }
    private static void RequiredResultSlotReentryControl()
    {
        var (callback, pending) = RequiredFaultParent(); var other = Pending();
        ResultReservationCallback = () =>
        {
            ManagedWorkRuntime.Schedule(other.Task); ManagedWorkRuntime.CallbackCompleted(callback);
            Need(Count(0) == 3 && Count(6) == 1);
        };
        ManagedWorkRuntime.CallbackCompleted(callback);
        Need(Count(0) == 2 && Count(6) == 1 && !other.Task.IsCompleted);
        var previous = ManagedWorkRuntime.Enter(other.Task); ManagedWorkRuntime.Exit(previous);
        ManagedWorkRuntime.Observed(pending.Task); Complete(other); Finish();
    }
    private static (Task Promise, TaskCompletionSource<int> Required,
        TaskCompletionSource<int> Blocker) RequiredAliasParent()
    {
        var outer = new TaskCompletionSource<Task<int>>(); var required = Pending(); var blocker = Pending();
        var promise = outer.Task.Unwrap();
        ManagedWorkRuntime.Schedule(outer.Task); ManagedWorkRuntime.Unwrap(promise, outer.Task);
        ManagedWorkRuntime.Inner(promise, required.Task);
        var previous = ManagedWorkRuntime.Enter(promise);
        ManagedWorkRuntime.CreatedAsync(required.Task); ManagedWorkRuntime.CreatedAsync(blocker.Task);
        required.SetException(new ArgumentException("control-required-alias-fault"));
        ManagedWorkRuntime.Exit(previous); outer.SetResult(required.Task);
        ManagedWorkRuntime.Completed(outer.Task); Need(promise.IsFaulted);
        ManagedWorkRuntime.Observed(promise);
        return (promise, required, blocker);
    }
    private static void RequiredResultActiveAliasControl()
    {
        var (promise, required, blocker) = RequiredAliasParent();
        ManagedWorkRuntime.Completed(promise);
        Need(Count(0) == 2 && Count(6) == 1 && !blocker.Task.IsCompleted);
        // The parent promise still resolves to its original live owner.
        var previous = ManagedWorkRuntime.Enter(promise); ManagedWorkRuntime.Exit(previous);
        ManagedWorkRuntime.Inner(promise, required.Task); ManagedWorkRuntime.Schedule(promise);
        ManagedWorkRuntime.Observed(required.Task);
        Need(Count(6) == 0 && Count(0) == 2);
        blocker.SetResult(1); ManagedWorkRuntime.Completed(promise); Finish();
    }
    private static void RequiredResultUncertainAliasControl()
    {
        var (promise, required, blocker) = RequiredAliasParent();
        unknownReservationKind = 6; Exception? received = null;
        try { ManagedWorkRuntime.Completed(promise); } catch (Exception error) { received = error; }
        Need(ReferenceEquals(received, UnknownReservation) && Count(0) == 2 && Count(6) == 1
            && !blocker.Task.IsCompleted);
        ManagedWorkRuntime.Observed(required.Task);
        Refuses(() => Enqueue(required.Task), "managed-work-owner-retired");
        Refuses(() => ManagedWorkRuntime.Completed(required.Task), "managed-work-double-settle");
        Refuses(() => ManagedWorkRuntime.Completed(promise), "managed-work-required-result-uncertain");
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-required-result-uncertain");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(Count(0) == 2 && Count(6) == 1 && Owners.ContainsKey(unknownReservationToken));
    }
    private static void RequiredResultOrdinaryAliasControl()
    {
        var (promise, required, blocker) = RequiredAliasParent();
        var previous = ManagedWorkRuntime.Enter(promise); var original = context;
        ManagedWorkRuntime.Exit(previous);
        previous = ManagedWorkRuntime.Enter(required.Task); Need(context == original);
        ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.Schedule(required.Task);
        Need(Count(0) == 2 && Count(6) == 0);
        ManagedWorkRuntime.Observed(required.Task); blocker.SetResult(1);
        ManagedWorkRuntime.Completed(promise); Finish();
    }

    // The registry calls below model the order of the injected pinned-CoreLib
    // hooks; the Tasks and Unwrap continuation are the real host CLR objects.
    private static void IndependentInnerFaultControl()
    {
        var failure = new ArgumentException("control-independent-inner-fault");
        var inner = new Task(() => throw failure);
        var outer = new Task<Task>(() => inner);
        ManagedWorkRuntime.Schedule(outer);
        var promise = outer.Unwrap();
        ManagedWorkRuntime.Unwrap(promise, outer);
        ManagedWorkRuntime.Schedule(inner);
        Need(Count(0) == 3);
        outer.RunSynchronously();
        ManagedWorkRuntime.Inner(promise, inner);
        ManagedWorkRuntime.Completed(outer);
        inner.RunSynchronously();
        Need(inner.IsFaulted && promise.IsFaulted);
        // Unwrap's pinned TrySetFromTask observes the original inner fault
        // before the promise's FinishStageThree completes.
        ManagedWorkRuntime.Observed(inner);
        ManagedWorkRuntime.Completed(promise);
        ManagedWorkRuntime.Completed(inner);
        try { promise.GetAwaiter().GetResult(); throw new InvalidOperationException("missing-task-fault"); }
        catch (ArgumentException error) when (ReferenceEquals(error, failure)) { }
        ManagedWorkRuntime.Observed(promise);
        Finish();
    }

    private static void InnerScheduledAfterAliasControl()
    {
        var inner = new Task(() => { });
        var outer = new Task<Task>(() => inner);
        ManagedWorkRuntime.Schedule(outer);
        var promise = outer.Unwrap();
        ManagedWorkRuntime.Unwrap(promise, outer);
        outer.RunSynchronously();
        ManagedWorkRuntime.Inner(promise, inner);
        ManagedWorkRuntime.Completed(outer);
        ManagedWorkRuntime.Schedule(inner);
        Need(Count(0) == 3);
        inner.RunSynchronously();
        ManagedWorkRuntime.Completed(promise);
        ManagedWorkRuntime.Completed(inner);
        Finish();
    }

    private static void IndependentInnerCapacityControl()
    {
        Limits[0] = 3;
        var inner = new Task(() => { });
        var outer = new Task<Task>(() => inner);
        ManagedWorkRuntime.Schedule(outer);
        var promise = outer.Unwrap();
        ManagedWorkRuntime.Unwrap(promise, outer);
        ManagedWorkRuntime.Schedule(inner);
        var pending = Pending();
        var previous = ManagedWorkRuntime.Enter(promise);
        ManagedWorkRuntime.CreatedAsync(pending.Task);
        ManagedWorkRuntime.Exit(previous);
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, inner); ManagedWorkRuntime.Completed(outer);
        previous = ManagedWorkRuntime.Enter(promise); var parentToken = context; ManagedWorkRuntime.Exit(previous);
        previous = ManagedWorkRuntime.Enter(inner); var innerToken = context; ManagedWorkRuntime.Exit(previous);
        Need(innerToken != parentToken);
        Enqueue(inner);
        Need(ManagedWorkRuntime.QueuedOwnerForControl(inner) == innerToken);
        var dispatch = ManagedWorkRuntime.BeginDispatch(inner);
        previous = ManagedWorkRuntime.EnterDispatch(inner, dispatch); Need(context == innerToken);
        ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.DispatchReturned(dispatch);
        inner.RunSynchronously(); ManagedWorkRuntime.Completed(promise); ManagedWorkRuntime.Completed(inner);
        Need(Count(0) == 2 && !pending.Task.IsCompleted);
        var later = new Task(() => { }); ManagedWorkRuntime.Schedule(later);
        later.RunSynchronously(); ManagedWorkRuntime.Completed(later);
        pending.SetResult(1); ManagedWorkRuntime.Completed(promise); Finish();
    }

    private static void SharedIndependentInnerControl(bool late)
    {
        var failure = new ArgumentException("control-shared-inner-fault");
        var inner = new Task(() => throw failure);
        var first = new Task<Task>(() => inner);
        var second = new Task<Task>(() => inner);
        ManagedWorkRuntime.Schedule(first); var a = first.Unwrap(); ManagedWorkRuntime.Unwrap(a, first);
        ManagedWorkRuntime.Schedule(second); var b = second.Unwrap(); ManagedWorkRuntime.Unwrap(b, second);
        if (!late) ManagedWorkRuntime.Schedule(inner);
        first.RunSynchronously(); ManagedWorkRuntime.Inner(a, inner); ManagedWorkRuntime.Completed(first);
        second.RunSynchronously(); ManagedWorkRuntime.Inner(b, inner); ManagedWorkRuntime.Completed(second);
        if (late) ManagedWorkRuntime.Schedule(inner);
        Need(Count(0) == 4);
        inner.RunSynchronously(); Need(inner.IsFaulted && a.IsFaulted && b.IsFaulted);
        // Each original Unwrap observes the same inner exception.
        ManagedWorkRuntime.Observed(inner); ManagedWorkRuntime.Observed(inner);
        ManagedWorkRuntime.Completed(a); ManagedWorkRuntime.Completed(b); ManagedWorkRuntime.Completed(inner);
        try { a.GetAwaiter().GetResult(); throw new InvalidOperationException("missing-first-task-fault"); }
        catch (ArgumentException error) when (ReferenceEquals(error, failure)) { }
        ManagedWorkRuntime.Observed(a);
        try { b.GetAwaiter().GetResult(); throw new InvalidOperationException("missing-second-task-fault"); }
        catch (ArgumentException error) when (ReferenceEquals(error, failure)) { }
        ManagedWorkRuntime.Observed(b); Finish();
    }

    private static void IndependentInnerReentryControl()
    {
        var inner = new Task(() => { }); var outer = new Task<Task>(() => inner);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, inner); ManagedWorkRuntime.Completed(outer);
        RecordAllocationCallback = () => ManagedWorkRuntime.Schedule(inner);
        ManagedWorkRuntime.Schedule(inner); Need(Count(0) == 3);
        inner.RunSynchronously(); ManagedWorkRuntime.Completed(promise); ManagedWorkRuntime.Completed(inner); Finish();
    }

    private static void IndependentInnerRefusalControl(bool unknown)
    {
        var inner = new Task(() => { }); var outer = new Task<Task>(() => inner);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, inner); ManagedWorkRuntime.Completed(outer);
        if (unknown) unknownReservationKind = 0; else Limits[0] = 2;
        if (unknown)
        {
            Exception? error = null; try { ManagedWorkRuntime.Schedule(inner); } catch (Exception caught) { error = caught; }
            Need(ReferenceEquals(error, UnknownReservation) && Count(0) == 3 && Owners.ContainsKey(unknownReservationToken));
            Refuses(() => ManagedWorkRuntime.Schedule(inner), "managed-work-owner-retired");
            Refuses(() => Enqueue(inner), "managed-work-owner-retired");
            Refuses(() => { ManagedWorkRuntime.Enter(inner); }, "managed-work-execution-parent");
            return;
        }
        Refuses(() => ManagedWorkRuntime.Schedule(inner), "managed-work-admission-refused");
        Need(Count(0) == 2 && !inner.IsCompleted && !promise.IsCompleted);
        // Only the registry admission was invoked; no actual Task.Start was
        // attempted before this model retry.
        Limits[0] = 3; ManagedWorkRuntime.Schedule(inner);
        inner.RunSynchronously(); ManagedWorkRuntime.Completed(promise); ManagedWorkRuntime.Completed(inner); Finish();
    }

    private static void InnerAndOuterAliasControl(bool reentrant)
    {
        var shared = new Task<Task>(() => Task.CompletedTask);
        var first = new Task<Task>(() => shared);
        ManagedWorkRuntime.Schedule(first); var a = first.Unwrap(); ManagedWorkRuntime.Unwrap(a, first);
        first.RunSynchronously(); ManagedWorkRuntime.Inner(a, shared); ManagedWorkRuntime.Completed(first);
        Task? b = null;
        void AdmitAndUnwrap()
        {
            ManagedWorkRuntime.Schedule(shared);
            b = shared.Unwrap(); ManagedWorkRuntime.Unwrap(b, shared);
        }
        if (reentrant)
        {
            RecordAllocationCallback = AdmitAndUnwrap;
            ManagedWorkRuntime.Schedule(shared);
        }
        else
        {
            AdmitAndUnwrap();
            ManagedWorkRuntime.Schedule(shared);
        }
        Need(Count(0) == 3 && b is not null);
        shared.RunSynchronously();
        ManagedWorkRuntime.Inner(b!, Task.CompletedTask);
        ManagedWorkRuntime.Completed(a); ManagedWorkRuntime.Completed(b!); ManagedWorkRuntime.Completed(shared);
        Finish();
    }

    private static void InnerAndInactiveOuterAliasControl()
    {
        var shared = new Task<Task>(() => throw new ArgumentException("control-inactive-outer-fault"));
        var first = new Task<Task>(() => shared);
        ManagedWorkRuntime.Schedule(first); var a = first.Unwrap(); ManagedWorkRuntime.Unwrap(a, first);
        first.RunSynchronously(); ManagedWorkRuntime.Inner(a, shared); ManagedWorkRuntime.Completed(first);
        ManagedWorkRuntime.Schedule(shared); var b = shared.Unwrap(); ManagedWorkRuntime.Unwrap(b, shared);
        var previous = ManagedWorkRuntime.Enter(b); settlementRefusal = context.Item2; ManagedWorkRuntime.Exit(previous);
        shared.RunSynchronously(); Need(a.IsFaulted && b.IsFaulted);
        Refuses(() => ManagedWorkRuntime.Completed(b), "managed-work-settlement-refused");
        Refuses(() => ManagedWorkRuntime.Schedule(shared), "managed-work-owner-retired");
        Need(refusedSettlements == 1 && Count(0) == 3 && Count(6) == 1);
        // The control terminates with the uncertain owner retained, without retry.
        settlementRefusal = 0;
    }

    private static void InactiveInnerAliasWithPrimaryControl(bool fault)
    {
        var inner = new Task(() => { if (fault) throw new ArgumentException("control-inactive-inner-fault"); });
        var outer = new Task<Task>(() => inner);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        ManagedWorkRuntime.Schedule(inner);
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, inner); ManagedWorkRuntime.Completed(outer);
        var previous = ManagedWorkRuntime.Enter(promise); settlementRefusal = context.Item2; ManagedWorkRuntime.Exit(previous);
        inner.RunSynchronously();
        if (fault) ManagedWorkRuntime.Observed(inner); // The original Unwrap observes its source fault.
        Refuses(() => ManagedWorkRuntime.Completed(promise), "managed-work-settlement-refused");
        Refuses(() => ManagedWorkRuntime.Schedule(inner), "managed-work-owner-retired");
        Refuses(() => Enqueue(inner), "managed-work-owner-retired");
        Refuses(() => { ManagedWorkRuntime.Enter(inner); }, "managed-work-execution-parent");
        Refuses(() => ManagedWorkRuntime.Observed(inner), "managed-work-double-settle");
        Refuses(() => ManagedWorkRuntime.Completed(inner), "managed-work-double-settle");
        Need(refusedSettlements == 1 && Count(0) == 3 && Count(6) == (fault ? 1 : 0));
        // Retain the uncertain alias and stop without another settlement attempt.
        settlementRefusal = 0;
    }

    private static void MultipleUnwrapFaultControl(string observed)
    {
        var failure = new ArgumentException("control-multiple-unwrap-fault");
        var inner = new TaskCompletionSource<int>();
        var outer = new Task<Task>(() => inner.Task);
        ManagedWorkRuntime.Schedule(outer);
        var first = outer.Unwrap(); ManagedWorkRuntime.Unwrap(first, outer);
        var second = outer.Unwrap(); ManagedWorkRuntime.Unwrap(second, outer);
        Need(!ReferenceEquals(first, second) && !first.IsCompleted && !second.IsCompleted);
        outer.RunSynchronously();
        ManagedWorkRuntime.Inner(first, inner.Task); ManagedWorkRuntime.Inner(second, inner.Task);
        ManagedWorkRuntime.Completed(outer);
        inner.SetException(failure); Need(first.IsFaulted && second.IsFaulted);
        // The host Tasks are real; registry calls model the selected pinned
        // Unwrap and FinishStageThree hooks in their completion order.
        ManagedWorkRuntime.Observed(inner.Task); ManagedWorkRuntime.Completed(first);
        ManagedWorkRuntime.Observed(inner.Task); ManagedWorkRuntime.Completed(second);
        if (observed is "first" or "both")
        {
            try { first.GetAwaiter().GetResult(); throw new InvalidOperationException("missing-first-fault"); }
            catch (ArgumentException error) when (ReferenceEquals(error, failure)) { }
            ManagedWorkRuntime.Observed(first);
        }
        if (observed is "second" or "both")
        {
            try { second.GetAwaiter().GetResult(); throw new InvalidOperationException("missing-second-fault"); }
            catch (ArgumentException error) when (ReferenceEquals(error, failure)) { }
            ManagedWorkRuntime.Observed(second);
        }
        AggregateException? received = null;
        try { ManagedWorkRuntime.JoinAcceptedWork(); } catch (AggregateException error) { received = error; }
        int expected = observed == "both" ? 0 : observed == "neither" ? 2 : 1;
        Need((received?.Flatten().InnerExceptions.Count ?? 0) == expected);
        if (received is not null) Need(received.Flatten().InnerExceptions.All(error => ReferenceEquals(error, failure)));
        ManagedWorkRuntime.FinishedPhysicalDrain(); Need(Owners.Count == 0 && Work.Count == 0);
    }

    private static void MultipleUnwrapPendingControl(bool firstFinishes)
    {
        // Explicit task ports model the two completion-hook orders; no
        // scheduler or guest execution is inferred from this control.
        var outer = new TaskCompletionSource<Task>(); var first = Pending(); var second = Pending();
        ManagedWorkRuntime.Schedule(outer.Task);
        ManagedWorkRuntime.Unwrap(first.Task, outer.Task); ManagedWorkRuntime.Unwrap(second.Task, outer.Task);
        var done = firstFinishes ? first : second; var pending = firstFinishes ? second : first;
        done.SetResult(1); ManagedWorkRuntime.Completed(done.Task);
        bool returned = false;
        Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); returned = true; }, "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!returned && !pending.Task.IsCompleted && Count(0) == 2);
    }

    private static void MultipleUnwrapCapacityControl()
    {
        var source = new TaskCompletionSource<int>(); var outer = new Task<Task>(() => source.Task);
        ManagedWorkRuntime.Schedule(outer);
        var first = outer.Unwrap(); ManagedWorkRuntime.Unwrap(first, outer);
        for (int i = 0; i < 32; i++)
        {
            var proxy = outer.Unwrap();
            Need(!ReferenceEquals(first, proxy));
            ManagedWorkRuntime.Unwrap(proxy, outer);
        }
        var overflow = outer.Unwrap();
        Refuses(() => ManagedWorkRuntime.Unwrap(overflow, outer), "managed-work-required-continuation-limit");
        Need(Count(0) == 2 && !outer.IsCompleted && !first.IsCompleted);
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
    }

    private static void SuccessfulUnwrapCapacityControl()
    {
        Limits[0] = 2;
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer);
        var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        var later = new Task(() => { });
        var rootContext = ExecutionContext.Capture() ?? throw new InvalidOperationException("missing-root-context");
        var rootToken = context;
        bool inlineObserved = false;
        _ = promise.ContinueWith(_ => {
            Refuses(() => ManagedWorkRuntime.Schedule(later), "managed-work-admission-refused");
            Refuses(() => Enqueue(outer), "managed-work-duplicate-enqueue");
            inlineObserved = true;
        }, TaskContinuationOptions.ExecuteSynchronously);
        Enqueue(outer);
        var queuedToken = ManagedWorkRuntime.QueuedTokenForControl(outer)!.Value;
        var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        Need(!Owners.ContainsKey(queuedToken.Id) && Count(3) == 0);
        Refuses(() => { ManagedWorkRuntime.BeginDispatch(outer); }, "managed-work-unregistered-dequeue");
        var previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        try
        {
            var dispatchToken = context;
            ExecutionContext.Run(rootContext, _ => Need(context == rootToken), null);
            Need(context == dispatchToken && context != rootToken);
            var invocation = ManagedWorkRuntime.Enter(outer);
            try { outer.RunSynchronously(); }
            finally { ManagedWorkRuntime.Exit(invocation); }
            ManagedWorkRuntime.Inner(promise, Task.CompletedTask);
            // The pinned success path calls FinishContinuations directly, so
            // FinishStageThree sees only the original outer Task.
            ManagedWorkRuntime.Completed(outer);
            Need(promise.IsCompletedSuccessfully && inlineObserved && Count(0) == 2);
            Refuses(() => ManagedWorkRuntime.Schedule(later), "managed-work-admission-refused");
        }
        finally
        {
            bool exitReentered = false;
            AfterContextFenceCallback = () => {
                Refuses(() => ManagedWorkRuntime.Schedule(later), "managed-work-reset-context-unavailable");
                exitReentered = true;
            };
            ManagedWorkRuntime.ResetStarting(ticket);
            ManagedWorkRuntime.Exit(previous);
            Need(exitReentered && Count(0) == 2);
            ManagedWorkRuntime.ResetReady(ticket);
            ManagedWorkRuntime.ResetFinished(ticket);
            ManagedWorkRuntime.DispatchReturned(ticket);
        }
        Need(Count(0) == 1);
        ManagedWorkRuntime.Schedule(later);
        later.RunSynchronously(); ManagedWorkRuntime.Completed(later); Finish();
    }

    private static void InlinePopRetainsUnwrapControl()
    {
        Limits[0] = 2;
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        Enqueue(outer); Need(ManagedWorkRuntime.Popped(true, outer));
        var previous = ManagedWorkRuntime.Enter(outer);
        try { outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, Task.CompletedTask); ManagedWorkRuntime.Completed(outer); }
        finally { ManagedWorkRuntime.Exit(previous); }
        Need(promise.IsCompletedSuccessfully && Count(0) == 2 && Count(3) == 0);
        Refuses(() => ManagedWorkRuntime.Schedule(new Task(() => { })), "managed-work-admission-refused");
        Finish(); // Inline pop has no dispatch-return witness; Join retains its old behavior.
    }

    // Model both placements around the host CLR's actual thread-pool context
    // reset. The pinned WASI dispatcher has the same reset call after Execute.
    private static void DispatchContextResetControl(bool early)
    {
        Limits[0] = 2;
        var originalContext = ExecutionContext.Capture() ?? throw new InvalidOperationException("missing-root-context");
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer);
        var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        var later = new Task(() => { });
        bool notified = false, admitted = false;
        string? refusal = null;
        var marker = new AsyncLocal<int>(change => {
            if (!change.ThreadContextChanged || change.PreviousValue != 1 || change.CurrentValue != 0) return;
            notified = true;
            try { ManagedWorkRuntime.Schedule(later); admitted = true; }
            catch (InvalidOperationException error) { refusal = error.Message; }
        });
        Enqueue(outer); var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        var previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, Task.CompletedTask);
        ManagedWorkRuntime.Completed(outer); marker.Value = 1;
        if (!early) ManagedWorkRuntime.ResetStarting(ticket);
        ManagedWorkRuntime.Exit(previous);
        if (!early) ManagedWorkRuntime.ResetReady(ticket);
        if (early) ManagedWorkRuntime.DispatchReturned(ticket);
        var reset = typeof(ExecutionContext).GetMethod("ResetThreadPoolThread",
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static,
            null, [typeof(Thread)], null) ?? throw new InvalidOperationException("missing-host-context-reset");
        reset.Invoke(null, [Thread.CurrentThread]);
        Need(notified && (early ? admitted && refusal is null
            : !admitted && refusal == "managed-work-reset-context-unavailable"));
        if (!early) { ManagedWorkRuntime.ResetFinished(ticket); ManagedWorkRuntime.DispatchReturned(ticket); }
        ExecutionContext.Run(originalContext, _ => {
            if (!early) ManagedWorkRuntime.Schedule(later);
            later.RunSynchronously(); ManagedWorkRuntime.Completed(later); Finish();
        }, null);
    }

    private static void DispatchNestedResetControl()
    {
        Limits[0] = 3; Limits[3] = 2;
        var originalContext = ExecutionContext.Capture() ?? throw new InvalidOperationException("missing-root-context");
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer);
        var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        var inner = new Task(() => { }); ManagedWorkRuntime.Schedule(inner);
        Enqueue(outer); Enqueue(inner);
        var reset = typeof(ExecutionContext).GetMethod("ResetThreadPoolThread",
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static,
            null, [typeof(Thread)], null) ?? throw new InvalidOperationException("missing-host-context-reset");
        bool outerSeen = false, innerSeen = false, outerRetained = false;
        object? ticket = null;
        Exception? notificationError = null;
        var innerMarker = new AsyncLocal<int>(change => {
            if (change.ThreadContextChanged && change.PreviousValue == 1 && change.CurrentValue == 0)
                innerSeen = Count(0) == 3;
        });
        var outerMarker = new AsyncLocal<int>(change => {
            if (!change.ThreadContextChanged || change.PreviousValue != 1 || change.CurrentValue != 0) return;
            try
            {
                outerSeen = Count(0) == 3;
                var innerTicket = ManagedWorkRuntime.BeginDispatch(inner);
                var innerPrevious = ManagedWorkRuntime.EnterDispatch(inner, innerTicket);
                inner.RunSynchronously(); ManagedWorkRuntime.Completed(inner); innerMarker.Value = 1;
                ManagedWorkRuntime.ResetStarting(innerTicket);
                ManagedWorkRuntime.Exit(innerPrevious);
                ManagedWorkRuntime.ResetReady(innerTicket);
                reset.Invoke(null, [Thread.CurrentThread]);
                Refuses(() => ManagedWorkRuntime.ResetFinished(ticket), "managed-work-reset-ticket");
                ManagedWorkRuntime.ResetFinished(innerTicket);
                ManagedWorkRuntime.DispatchReturned(innerTicket);
                outerRetained = Count(0) == 2 && context == (0UL, 1UL);
            }
            catch (Exception error) { notificationError = error; }
        });
        ticket = ManagedWorkRuntime.BeginDispatch(outer);
        var previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, Task.CompletedTask);
        ManagedWorkRuntime.Completed(outer); outerMarker.Value = 1;
        ManagedWorkRuntime.ResetStarting(ticket);
        ManagedWorkRuntime.Exit(previous);
        ManagedWorkRuntime.ResetReady(ticket);
        reset.Invoke(null, [Thread.CurrentThread]);
        Need(notificationError is null && outerSeen && innerSeen && outerRetained && Count(0) == 2);
        ManagedWorkRuntime.ResetFinished(ticket); ManagedWorkRuntime.DispatchReturned(ticket);
        ExecutionContext.Run(originalContext, _ => { Need(Count(0) == 1); Finish(); }, null);
    }

    private static void DispatchResetTransitionFenceControl()
    {
        Limits[0] = 3; Limits[3] = 2;
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        var inner = new Task(() => { }); ManagedWorkRuntime.Schedule(inner);
        Enqueue(outer); Enqueue(inner);
        var innerToken = ManagedWorkRuntime.QueuedTokenForControl(inner)!.Value;
        var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        var previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, Task.CompletedTask); ManagedWorkRuntime.Completed(outer);
        bool observed = false;
        AfterContextFenceCallback = () => {
            Refuses(() => { ManagedWorkRuntime.BeginDispatch(inner); }, "managed-work-reset-context-unavailable");
            Refuses(() => { ManagedWorkRuntime.Enter(inner); }, "managed-work-reset-context-unavailable");
            Need(Owners.ContainsKey(innerToken.Id) && ManagedWorkRuntime.QueuedTokenForControl(inner) == innerToken);
            observed = true;
        };
        ManagedWorkRuntime.ResetStarting(ticket); ManagedWorkRuntime.Exit(previous);
        ManagedWorkRuntime.ResetReady(ticket); ManagedWorkRuntime.ResetFinished(ticket); ManagedWorkRuntime.DispatchReturned(ticket);
        Need(observed && Count(0) == 2 && Count(3) == 1);
        var innerTicket = ManagedWorkRuntime.BeginDispatch(inner);
        previous = ManagedWorkRuntime.EnterDispatch(inner, innerTicket);
        inner.RunSynchronously(); ManagedWorkRuntime.Completed(inner);
        ManagedWorkRuntime.ResetStarting(innerTicket); ManagedWorkRuntime.Exit(previous);
        ManagedWorkRuntime.ResetReady(innerTicket); ManagedWorkRuntime.ResetFinished(innerTicket); ManagedWorkRuntime.DispatchReturned(innerTicket);
        Finish();
    }

    // A null reset context refuses; an explicitly restored root remains usable.
    private static void DispatchResetAttributionControl(bool explicitRoot)
    {
        Limits[0] = 3;
        var originalContext = ExecutionContext.Capture() ?? throw new InvalidOperationException("missing-root-context");
        var rootContext = context;
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer);
        var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        var later = new Task(() => { });
        bool notified = false, sawFence = false;
        Exception? notificationError = null;
        var marker = new AsyncLocal<int>(change => {
            if (!change.ThreadContextChanged || change.PreviousValue != 1 || change.CurrentValue != 0) return;
            try
            {
                sawFence = context == (0UL, 1UL);
                captureTaskParent = true;
                if (explicitRoot) ExecutionContext.Run(originalContext, _ => ManagedWorkRuntime.Schedule(later), null);
                else Refuses(() => ManagedWorkRuntime.Schedule(later), "managed-work-reset-context-unavailable");
                captureTaskParent = false; notified = true;
            }
            catch (Exception error) { notificationError = error; }
        });
        Enqueue(outer); var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        var previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        var dispatchContext = context;
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, Task.CompletedTask);
        ManagedWorkRuntime.Completed(outer); marker.Value = 1;
        ManagedWorkRuntime.ResetStarting(ticket);
        ManagedWorkRuntime.Exit(previous);
        ManagedWorkRuntime.ResetReady(ticket);
        var reset = typeof(ExecutionContext).GetMethod("ResetThreadPoolThread",
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static,
            null, [typeof(Thread)], null) ?? throw new InvalidOperationException("missing-host-context-reset");
        reset.Invoke(null, [Thread.CurrentThread]);
        Need(notified && sawFence && notificationError is null && dispatchContext != rootContext
            && capturedTaskParent == (explicitRoot ? rootContext : (0UL, 0UL)));
        ManagedWorkRuntime.ResetFinished(ticket); ManagedWorkRuntime.DispatchReturned(ticket);
        ExecutionContext.Run(originalContext, _ => {
            if (explicitRoot) { later.RunSynchronously(); ManagedWorkRuntime.Completed(later); }
            Finish();
        }, null);
    }

    private static void DispatchBoundaryExceptionControl(bool duringReset)
    {
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer);
        var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        Enqueue(outer); var token = ManagedWorkRuntime.QueuedTokenForControl(outer);
        var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        var previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        var failure = new InvalidOperationException("control-dispatch-boundary-failure");
        Exception? received = null;
        try
        {
            try
            {
                if (!duringReset) throw failure;
                outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, Task.CompletedTask);
                ManagedWorkRuntime.Completed(outer);
            }
            finally { ManagedWorkRuntime.ResetStarting(ticket); ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.ResetReady(ticket); }
            throw failure; // Models a reset that fails before the return hook.
        }
        catch (Exception error) { received = error; }
        Need(ReferenceEquals(received, failure) && Count(0) == 2 && Count(3) == 0
            && ManagedWorkRuntime.QueuedTokenForControl(outer) == token);
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
    }

    private static void DispatchThrowingResetChild()
    {
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer);
        var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        Enqueue(outer); var token = ManagedWorkRuntime.QueuedTokenForControl(outer);
        var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        var previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        var marker = new AsyncLocal<int>(change => {
            if (!change.ThreadContextChanged || change.PreviousValue != 1 || change.CurrentValue != 0) return;
            Console.WriteLine(Count(0) == 2 && Count(3) == 0 && context == (0UL, 1UL)
                && ManagedWorkRuntime.QueuedTokenForControl(outer) == token ? "reset-owner-retained" : "reset-owner-lost");
            Console.Out.Flush();
            throw new InvalidOperationException("control-reset-callback-threw");
        });
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, Task.CompletedTask);
        ManagedWorkRuntime.Completed(outer); marker.Value = 1;
        ManagedWorkRuntime.ResetStarting(ticket); ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.ResetReady(ticket);
        var reset = typeof(ExecutionContext).GetMethod("ResetThreadPoolThread",
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static,
            null, [typeof(Thread)], null) ?? throw new InvalidOperationException("missing-host-context-reset");
        reset.Invoke(null, [Thread.CurrentThread]);
        ManagedWorkRuntime.DispatchReturned(ticket);
        throw new InvalidOperationException("reset-notification-did-not-terminate");
    }

    private static void DispatchThrowingResetControl()
    {
        var executable = Environment.ProcessPath ?? throw new InvalidOperationException("missing-host-executable");
        var start = new System.Diagnostics.ProcessStartInfo {
            FileName = OperatingSystem.IsWindows() ? executable : "/bin/sh",
            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
        };
        if (!OperatingSystem.IsWindows())
        {
            start.ArgumentList.Add("-c"); start.ArgumentList.Add("ulimit -c 0; exec \"$@\"");
            start.ArgumentList.Add("managed-reset-control"); start.ArgumentList.Add(executable);
        }
        if (string.Equals(Path.GetFileNameWithoutExtension(executable), "dotnet", StringComparison.OrdinalIgnoreCase))
            start.ArgumentList.Add(typeof(StateControl).Assembly.Location);
        start.ArgumentList.Add("dispatch-reset-throwing-child");
        start.Environment["COMPlus_DbgEnableMiniDump"] = "0";
        start.Environment["DOTNET_DbgEnableMiniDump"] = "0";
        using var process = System.Diagnostics.Process.Start(start) ?? throw new InvalidOperationException("reset-child-start");
        var output = process.StandardOutput.ReadToEndAsync();
        var error = process.StandardError.ReadToEndAsync();
        if (!process.WaitForExit(15000)) { process.Kill(true); throw new InvalidOperationException("reset-child-timeout"); }
        Need(process.ExitCode != 0 && output.GetAwaiter().GetResult().Trim() == "reset-owner-retained"
            && error.GetAwaiter().GetResult().Contains("control-reset-callback-threw", StringComparison.Ordinal));
    }

    private static void DispatchQueueAckControl(bool unknown)
    {
        var task = Pending(); ManagedWorkRuntime.Schedule(task.Task); Enqueue(task.Task);
        var token = ManagedWorkRuntime.QueuedTokenForControl(task.Task)!.Value;
        settlementRefusal = token.Id; settlementUnknown = unknown;
        Refuses(() => { ManagedWorkRuntime.BeginDispatch(task.Task); }, "managed-work-settlement-refused");
        Refuses(() => { ManagedWorkRuntime.BeginDispatch(task.Task); }, "managed-work-queue-uncertain");
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
        Need(refusedSettlements == 1 && Count(3) == (unknown ? 0 : 1)
            && ManagedWorkRuntime.QueuedTokenForControl(task.Task) == token);
        settlementRefusal = 0; // Keep the exact uncertain custody; make no further attempt.
    }

    private static void DispatchOwnerAckControl(bool unknown)
    {
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        var previous = ManagedWorkRuntime.Enter(promise); settlementRefusal = context.Item2;
        settlementUnknown = unknown; ManagedWorkRuntime.Exit(previous);
        Enqueue(outer); var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        try { outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, Task.CompletedTask); ManagedWorkRuntime.Completed(outer); }
        finally { ManagedWorkRuntime.Exit(previous); }
        Refuses(() => ManagedWorkRuntime.DispatchReturned(ticket), "managed-work-settlement-refused");
        Refuses(() => ManagedWorkRuntime.DispatchReturned(ticket), "managed-work-dispatch-ticket");
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-double-settle");
        Need(refusedSettlements == 1 && Count(0) == (unknown ? 1 : 2) && Count(3) == 0);
        settlementRefusal = 0;
    }

    private static void DispatchIdentityChangeControl()
    {
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        Enqueue(outer); var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        var nestedOuter = new TaskCompletionSource<Task>(); var nestedPromise = Pending();
        ManagedWorkRuntime.Inner(promise, nestedOuter.Task);
        ManagedWorkRuntime.Unwrap(nestedPromise.Task, nestedOuter.Task);
        Refuses(() => { ManagedWorkRuntime.EnterDispatch(outer, ticket); }, "managed-work-running-owner-changed");
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!outer.IsCompleted && Count(0) == 2 && Count(3) == 0);
    }

    private static void DispatchExitFailureControl()
    {
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        Enqueue(outer); var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        var previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, Task.CompletedTask); ManagedWorkRuntime.Completed(outer);
        ManagedWorkRuntime.ResetStarting(ticket);
        refuseContextFence = true;
        Refuses(() => ManagedWorkRuntime.Exit(previous), "control-context-fence-failed");
        // The real dispatch finally does not call DispatchReturned after a
        // failed Exit; its exact acknowledged queue record remains retained.
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(Count(0) == 2 && Count(3) == 0);
    }

    private static void DispatchResetContextFailureControl(bool finish, bool after)
    {
        var outer = new Task<Task>(() => Task.CompletedTask);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        Enqueue(outer); var ticket = ManagedWorkRuntime.BeginDispatch(outer);
        var rootToken = context;
        var previous = ManagedWorkRuntime.EnterDispatch(outer, ticket);
        if (finish)
        {
            ManagedWorkRuntime.ResetStarting(ticket); ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.ResetReady(ticket);
            refuseContextRestore = rootToken.Item2; contextThrowsBeforeRestore = !after;
            Refuses(() => ManagedWorkRuntime.ResetFinished(ticket), "control-context-restore-failed");
            refuseContextRestore = 0;
            Refuses(() => ManagedWorkRuntime.ResetFinished(ticket), "managed-work-reset-ticket");
        }
        else
        {
            refuseContextFence = true; contextFenceThrowsAfter = after;
            Refuses(() => ManagedWorkRuntime.ResetStarting(ticket), "control-context-fence-failed");
            refuseContextFence = false;
            Refuses(() => ManagedWorkRuntime.ResetStarting(ticket), "managed-work-reset-context-unavailable");
        }
        Refuses(() => ManagedWorkRuntime.Schedule(new Task(() => { })), "managed-work-reset-context-unavailable");
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-unproven-quiescence");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(Count(0) == 2 && Count(3) == 0);
    }

    private static void DispatchDirectTaskControl(bool fault)
    {
        var failure = new ArgumentException("control-dispatch-task-fault");
        var task = new Task(() => { if (fault) throw failure; });
        ManagedWorkRuntime.Schedule(task); Enqueue(task);
        var ticket = ManagedWorkRuntime.BeginDispatch(task);
        var previous = ManagedWorkRuntime.EnterDispatch(task, ticket);
        try
        {
            task.RunSynchronously(); ManagedWorkRuntime.Completed(task);
            Need(task.IsCompleted && Count(0) == 2 && Count(6) == 0);
            if (fault) { _ = task.Exception; ManagedWorkRuntime.Observed(task); }
        }
        finally { ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.DispatchReturned(ticket); }
        Need(Count(0) == 1 && Count(6) == 0); Finish();
    }

    private static void DispatchQueuedSiblingControl()
    {
        var source = new TaskCompletionSource<int>(); var outer = new Task<Task>(() => source.Task);
        ManagedWorkRuntime.Schedule(outer); var promise = outer.Unwrap(); ManagedWorkRuntime.Unwrap(promise, outer);
        Enqueue(outer); var first = ManagedWorkRuntime.BeginDispatch(outer);
        var previous = ManagedWorkRuntime.EnterDispatch(outer, first);
        try
        {
            Enqueue(promise);
            outer.RunSynchronously(); ManagedWorkRuntime.Inner(promise, source.Task); ManagedWorkRuntime.Completed(outer);
            source.SetResult(1); Need(promise.IsCompletedSuccessfully);
        }
        finally { ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.DispatchReturned(first); }
        Need(Count(0) == 2 && Count(3) == 1);
        var second = ManagedWorkRuntime.BeginDispatch(promise);
        previous = ManagedWorkRuntime.EnterDispatch(promise, second);
        ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.DispatchReturned(second);
        Need(Count(0) == 1 && Count(3) == 0); Finish();
    }
    private static void RequiredResultSettlementFailureControl(bool unknown)
    {
        var (callback, pending) = RequiredFaultParent();
        ResultReservationCallback = () =>
        {
            ManagedWorkRuntime.Observed(pending.Task);
            settlementRefusal = Owners.Single(entry => entry.Value == 6).Key;
            settlementUnknown = unknown;
        };
        Refuses(() => ManagedWorkRuntime.CallbackCompleted(callback), "managed-work-settlement-refused");
        ManagedWorkRuntime.Observed(pending.Task); ManagedWorkRuntime.CallbackCompleted(pending.Task);
        Refuses(() => ManagedWorkRuntime.Completed(pending.Task), "managed-work-double-settle");
        Refuses(() => ManagedWorkRuntime.CallbackCompleted(callback), "managed-work-required-result-uncertain");
        Refuses(() => { ManagedWorkRuntime.JoinAcceptedWork(); rootJoinReturned = true; },
            "managed-work-required-result-uncertain");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
        Need(!rootJoinReturned && refusedSettlements == 1 && Count(0) == 2 && Count(6) == (unknown ? 0 : 1));
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
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-owners");
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
            Refuses(() => ManagedWorkRuntime.EnterDispatch(item, null), "managed-work-dispatch-ticket");
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
    private static void AssertSafeStartupFenced()
    {
        Refuses(Begin, "managed-work-installation");
        Refuses(() => ManagedWorkRuntime.Enqueue(new object()), "managed-work-installation-in-progress");
        Refuses(() => ManagedWorkRuntime.TimerChanging(new object()), "managed-work-installation-in-progress");
        Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-closing-state");
        Refuses(ManagedWorkRuntime.FinishedPhysicalDrain, "managed-work-finalization-state");
    }
    private static void AssertStartupFenced()
    {
        AssertSafeStartupFenced();
        Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-untracked-startup-work");
        Refuses(() => ManagedWorkRuntime.Continuation(Pending().Task), "managed-work-untracked-startup-work");
        Refuses(() => ManagedWorkRuntime.Unwrap(Pending().Task, Pending().Task), "managed-work-untracked-startup-work");
        Refuses(() => ManagedWorkRuntime.Inner(Pending().Task, Pending().Task), "managed-work-untracked-startup-work");
        Refuses(() => ManagedWorkRuntime.CreatedAsync(Pending().Task), "managed-work-untracked-startup-work");
        Refuses(() => ManagedWorkRuntime.RequiredTransport(Pending().Task), "managed-work-untracked-startup-work");
        ManagedWorkRuntime.ContinuationFailed(Pending().Task); ManagedWorkRuntime.Observed(Pending().Task);
    }
    private static void StartupPreinstallControl()
    {
        ManagedWorkRuntime.Schedule(Pending().Task); ManagedWorkRuntime.Continuation(Pending().Task);
        ManagedWorkRuntime.Unwrap(Pending().Task, Pending().Task); ManagedWorkRuntime.Inner(Pending().Task, Pending().Task);
        ManagedWorkRuntime.CreatedAsync(Pending().Task); ManagedWorkRuntime.RequiredTransport(Pending().Task);
        Need(ManagedWorkRuntime.Enqueue(new object()) is null); ManagedWorkRuntime.TimerChanging(new object());
        ManagedWorkRuntime.EnqueueFinalized(null, 0); ManagedWorkRuntime.Dequeue(new object());
        Need(ManagedWorkRuntime.Popped(true, new object()) && ManagedWorkRuntime.Enter(new object()) is null);
        ManagedWorkRuntime.Exit(null); ManagedWorkRuntime.CallbackCompleted(new object());
        ManagedWorkRuntime.Completed(Pending().Task); ManagedWorkRuntime.ContinuationFailed(Pending().Task);
        ManagedWorkRuntime.Observed(Pending().Task); Need(ManagedWorkRuntime.BindContext(null, new object()) is null);
        ManagedWorkRuntime.TimerAccepted(new object()); Need(ManagedWorkRuntime.TimerEnter(new object()) is null);
        ManagedWorkRuntime.TimerChanged(new object()); ManagedWorkRuntime.TimerDeleted(new object());
        ManagedWorkRuntime.TimerLeave(new object(), null); ManagedWorkRuntime.EnsureJoinReady();
        Need(Owners.Count == 0); Begin(); Finish();
    }
    private static void StartupBeforeRootAllocationFailureControl()
    {
        startupInspect = true; StartupAllocationCallback = () => throw StartupAllocationError;
        Exception? received = null; try { Begin(); } catch (Exception error) { received = error; }
        var state = ManagedWorkRuntime.StartupForControl();
        Need(ReferenceEquals(received, StartupAllocationError) && state.Root is null && !state.Installed
            && Owners.Count == 0 && startupRootAttempts == 0 && startupNativeAttempts == 0);
        AssertStartupFenced();
    }
    private static void StartupReadinessFailureControl(int at)
    {
        startupInspect = true; failReadinessAt = at;
        Exception? received = null; try { Begin(); } catch (Exception error) { received = error; }
        Need(ReferenceEquals(received, StartupReadinessError));
        if (at == 1)
        {
            Need(Owners.Count == 0); failReadinessAt = 0; Begin(); Finish(); return;
        }
        Need(Count(0) == (at >= 4 ? 1 : 0) && Count(7) == (at >= 5 ? 1 : 0)
            && startupRootAttempts == 0 && startupNativeAttempts == 0);
        AssertStartupFenced();
    }
    private static void StartupReadinessReentryControl(string stage)
    {
        startupInspect = true; void Ready() => Work.Enqueue(() => { });
        if (stage == "allocation") StartupAllocationCallback = Ready;
        else if (stage == "root-publication") StartupRootPublishedCallback = Ready;
        else if (stage == "root") StartupReserveCallback = Ready;
        else if (stage == "native") StartupReserveCallback = () => StartupReserveCallback = Ready;
        else if (stage == "context") StartupContextCallback = Ready;
        else throw new InvalidOperationException("unknown-startup-readiness-stage");
        Refuses(Begin, "managed-work-untracked-startup-work");
        Need(Work.Count == 1 && Count(0) == (stage is "allocation" or "root-publication" ? 0 : 1)
            && Count(7) == (stage is "native" or "context" ? 1 : 0)
            && startupRootAttempts == 0 && startupNativeAttempts == 0);
        AssertStartupFenced();
    }
    private static void StartupExecutionReentryControl(string stage, string action)
    {
        startupInspect = true; bool inspected = false;
        void Reenter()
        {
            inspected = true;
            switch (action)
            {
                case "schedule": Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-untracked-startup-work"); break;
                case "continuation": Refuses(() => ManagedWorkRuntime.Continuation(Pending().Task), "managed-work-untracked-startup-work"); break;
                case "unwrap": Refuses(() => ManagedWorkRuntime.Unwrap(Pending().Task, Pending().Task), "managed-work-untracked-startup-work"); break;
                case "inner": Refuses(() => ManagedWorkRuntime.Inner(Pending().Task, Pending().Task), "managed-work-untracked-startup-work"); break;
                case "created-async": Refuses(() => ManagedWorkRuntime.CreatedAsync(Pending().Task), "managed-work-untracked-startup-work"); break;
                case "required-transport": Refuses(() => ManagedWorkRuntime.RequiredTransport(Pending().Task), "managed-work-untracked-startup-work"); break;
                case "continuation-failed": ManagedWorkRuntime.ContinuationFailed(Pending().Task); break;
                case "observed": ManagedWorkRuntime.Observed(Pending().Task); break;
                case "ensure-join-ready": Refuses(ManagedWorkRuntime.EnsureJoinReady, "managed-work-untracked-startup-work"); break;
                case "enter": Refuses(() => ManagedWorkRuntime.Enter(new object()), "managed-work-untracked-startup-work"); break;
                case "dequeue": Refuses(() => ManagedWorkRuntime.Dequeue(new object()), "managed-work-untracked-startup-work"); break;
                case "pop": Refuses(() => ManagedWorkRuntime.Popped(true, new object()), "managed-work-untracked-startup-work"); break;
                case "bind": Refuses(() => ManagedWorkRuntime.BindContext(null, new object()), "managed-work-untracked-startup-work"); break;
                case "timer-accepted": Refuses(() => ManagedWorkRuntime.TimerAccepted(new object()), "managed-work-untracked-startup-work"); break;
                case "timer-enter": Refuses(() => ManagedWorkRuntime.TimerEnter(new object()), "managed-work-untracked-startup-work"); break;
                case "timer-deleted": Refuses(() => ManagedWorkRuntime.TimerDeleted(new object()), "managed-work-untracked-startup-work"); break;
                case "enqueue-success": Refuses(() => ManagedWorkRuntime.EnqueueFinalized(null, 2), "managed-work-untracked-startup-work"); break;
                case "enqueue-fault": ManagedWorkRuntime.EnqueueFinalized(null, 0); break;
                case "timer-changed": ManagedWorkRuntime.TimerChanged(new object()); break;
                case "timer-leave": ManagedWorkRuntime.TimerLeave(new object(), null); break;
                case "exit": ManagedWorkRuntime.Exit(null); break;
                case "callback-completed": ManagedWorkRuntime.CallbackCompleted(new object()); break;
                case "completed": ManagedWorkRuntime.Completed(Pending().Task); break;
                default: throw new InvalidOperationException("unknown-startup-execution-action");
            }
        }
        if (stage == "initial") StartupReadinessCallback = Reenter;
        else if (stage == "allocation") StartupAllocationCallback = Reenter;
        else if (stage == "root-publication") StartupRootPublishedCallback = Reenter;
        else if (stage == "root") StartupReserveCallback = Reenter;
        else if (stage == "native") StartupReserveCallback = () => StartupReserveCallback = Reenter;
        else if (stage == "context") StartupContextCallback = Reenter;
        else throw new InvalidOperationException("unknown-startup-execution-stage");
        Refuses(Begin, "managed-work-untracked-startup-work");
        Need(inspected && Count(0) == (stage is "initial" or "allocation" or "root-publication" ? 0 : 1)
            && Count(7) == (stage is "native" or "context" ? 1 : 0)
            && startupRootAttempts == 0 && startupNativeAttempts == 0);
        AssertStartupFenced();
    }
    private static void StartupInitialReadyControl(bool poison)
    {
        startupInspect = true;
        StartupReadinessCallback = () =>
        {
            if (poison) Refuses(() => ManagedWorkRuntime.Enter(new object()), "managed-work-untracked-startup-work");
            Work.Enqueue(() => { });
        };
        Refuses(Begin, "managed-work-untracked-startup-work");
        Need(Owners.Count == 0 && Work.Count == 1);
        Work.Dequeue();
        if (poison) AssertStartupFenced();
        else { Begin(); Finish(); }
    }
    private static void StartupInitialReadinessErrorAfterExecutionControl()
    {
        startupInspect = true;
        StartupReadinessCallback = () =>
        {
            Refuses(() => ManagedWorkRuntime.Enter(new object()), "managed-work-untracked-startup-work");
            throw StartupReadinessError;
        };
        Exception? received = null; try { Begin(); } catch (Exception error) { received = error; }
        Need(ReferenceEquals(received, StartupReadinessError) && Owners.Count == 0);
        AssertStartupFenced();
    }
    private static void StartupPoisonedCleanupPreservesPrimaryControl()
    {
        startupInspect = true;
        StartupAllocationCallback = () => StartupAllocationCallback = () =>
        {
            ManagedWorkRuntime.TimerChanged(new object());
            throw StartupAllocationError;
        };
        Exception? received = null; try { Begin(); } catch (Exception error) { received = error; }
        Need(ReferenceEquals(received, StartupAllocationError) && Count(0) == 1 && Count(7) == 1
            && startupRootAttempts == 0 && startupNativeAttempts == 0);
        AssertStartupFenced();
    }
    private static void StartupNativeRefusalControl(int mode)
    {
        startupInspect = true; Limits[7] = 0;
        StartupReserveCallback = () => StartupReserveCallback = AssertSafeStartupFenced;
        startupRootCleanupFailure = mode != 0; startupCleanupAfter = mode == 2;
        Refuses(Begin, "managed-work-admission-refused");
        var state = ManagedWorkRuntime.StartupForControl();
        Need(state.Root == (17UL, startupRoot) && !state.RootActive && !state.Installed
            && state.Native == (0UL, 0UL) && startupRootAttempts == 1 && startupNativeAttempts == 0
            && Count(0) == (mode == 1 ? 1 : 0) && Count(7) == 0);
        AssertStartupFenced(); Need(startupRootAttempts == 1 && startupNativeAttempts == 0);
    }
    private static void StartupNativeUnknownControl(string mode)
    {
        startupInspect = true;
        if (mode is "unknown" or "unknown-poison") unknownReservationKind = 7;
        else if (mode == "zero-both") bridgeZeroBothKind = 7;
        else { malformedReservationKind = 7; malformedGeneration = mode == "generation"; }
        if (mode == "unknown-poison")
            StartupReserveCallback = () => StartupReserveCallback = () =>
                Refuses(() => ManagedWorkRuntime.Enter(new object()), "managed-work-untracked-startup-work");
        Exception? received = null; try { Begin(); } catch (Exception error) { received = error; }
        Need(mode is "unknown" or "unknown-poison" ? ReferenceEquals(received, UnknownReservation)
            : received is InvalidOperationException && received.Message == "managed-work-reservation-token");
        var state = ManagedWorkRuntime.StartupForControl();
        Need(state.Root == (17UL, startupRoot) && !state.RootActive && !state.Installed
            && state.Native == (mode is "unknown" or "unknown-poison" or "zero-both" ? (0UL, 0UL)
                : mode == "generation" ? (0UL, startupNative) : (17UL, 0UL))
            && startupRootAttempts == 0 && startupNativeAttempts == 0
            && Count(0) == 1 && Count(7) == 1 && Owners.ContainsKey(startupNative));
        AssertStartupFenced(); Need(startupRootAttempts == 0 && startupNativeAttempts == 0);
    }
    private static void StartupNativeRefusalPoisonControl()
    {
        startupInspect = true; Limits[7] = 0;
        StartupReserveCallback = () => StartupReserveCallback = () =>
            Refuses(() => ManagedWorkRuntime.Enter(new object()), "managed-work-untracked-startup-work");
        Refuses(Begin, "managed-work-admission-refused");
        var state = ManagedWorkRuntime.StartupForControl();
        Need(state.Root == (17UL, startupRoot) && !state.RootActive && !state.Installed
            && Count(0) == 1 && Count(7) == 0 && startupRootAttempts == 0 && startupNativeAttempts == 0);
        AssertStartupFenced(); Need(startupRootAttempts == 0 && startupNativeAttempts == 0);
    }
    private static void StartupRootZeroBothControl()
    {
        startupInspect = true; bridgeZeroBothKind = 0;
        Refuses(Begin, "managed-work-reservation-token");
        var state = ManagedWorkRuntime.StartupForControl();
        Need(state.Root == (0UL, 0UL) && !state.RootActive && !state.Installed
            && Count(0) == 1 && Count(7) == 0 && Owners.ContainsKey(unknownReservationToken)
            && startupRootAttempts == 0 && startupNativeAttempts == 0);
        AssertStartupFenced();
    }
    private static void StartupAllocationFailureControl(int mode)
    {
        startupInspect = true;
        startupNativeCleanupFailure = mode is 1 or 2;
        startupRootCleanupFailure = mode is 3 or 4;
        startupCleanupAfter = mode is 2 or 4;
        StartupAllocationCallback = () => StartupAllocationCallback = () => throw StartupAllocationError;
        Exception? received = null; try { Begin(); } catch (Exception error) { received = error; }
        var state = ManagedWorkRuntime.StartupForControl();
        Need(ReferenceEquals(received, StartupAllocationError) && !state.RootActive && !state.Installed
            && state.Root == (17UL, startupRoot) && state.Native == (17UL, startupNative)
            && startupNativeAttempts == 1 && startupRootAttempts == (mode is 1 or 2 ? 0 : 1)
            && Count(7) == (mode == 1 ? 1 : 0) && Count(0) == (mode is 1 or 2 or 3 ? 1 : 0));
        AssertStartupFenced();
        Need(startupNativeAttempts == 1 && startupRootAttempts == (mode is 1 or 2 ? 0 : 1));
    }
    private static void StartupContextFailureControl(int mode)
    {
        var before = ExecutionContext.Capture() ?? throw new InvalidOperationException("control-startup-context");
        ExecutionContext? captured = null; startupInspect = true; startupContextFailure = true;
        startupContextBefore = mode == 0; startupClearFailure = mode == 2; startupClearBefore = true;
        if (mode == 3) Limits[7] = 2;
        StartupContextCallback = () =>
        {
            AssertStartupFenced(); captured = ExecutionContext.Capture();
            if (mode == 3)
            {
                var extra = Reserve(7, 17, startupRoot);
                Need(extra == (17UL, startupExtra) && startupExtra != 0);
            }
        };
        Exception? received = null; try { Begin(); } catch (Exception error) { received = error; }
        var state = ManagedWorkRuntime.StartupForControl();
        Need(ReferenceEquals(received, StartupContextError) && !state.RootActive && !state.Installed
            && state.Root == (17UL, startupRoot) && state.Native == (17UL, startupNative)
            && startupRootAttempts == 0 && startupNativeAttempts == 0
            && Count(0) == 1 && Count(7) == (mode == 3 ? 2 : 1)
            && context == (mode == 2 ? (17UL, startupRoot) : (0UL, 0UL)));
        AssertStartupFenced();
        startupContextFailure = false; startupClearFailure = false;
        if (captured is not null)
            ExecutionContext.Run(before, _ => ExecutionContext.Run(captured, _ =>
            {
                Need(context == (0UL, 0UL));
                Refuses(() => ManagedWorkRuntime.Schedule(Pending().Task), "managed-work-untracked-startup-work");
            }, null), null);
        Need(startupRootAttempts == 0 && startupNativeAttempts == 0 && Count(0) == 1);
    }
    private static void StartupContextReentryControl()
    {
        var before = ExecutionContext.Capture() ?? throw new InvalidOperationException("control-startup-context");
        startupInspect = true; bool invoked = false;
        StartupContextCallback = () =>
        {
            invoked = true; AssertSafeStartupFenced();
            ExecutionContext.Run(before, _ => Need(context == (0UL, 0UL)), null);
            Need(context == (17UL, startupRoot));
        };
        Begin(); Need(invoked && context == (17UL, startupRoot) && Count(0) == 1 && Count(7) == 1);
        Finish(); Need(startupRootAttempts == 1 && startupNativeAttempts == 1);
    }
    private static void StartupAllocationReentryControl()
    {
        startupInspect = true; int calls = 0;
        StartupAllocationCallback = () =>
        {
            calls++; AssertSafeStartupFenced();
            StartupAllocationCallback = () => { calls++; AssertSafeStartupFenced(); };
        };
        Begin(); Need(calls == 2); Finish();
    }
    private static void StartupReservationReentryControl()
    {
        startupInspect = true; int calls = 0;
        StartupReserveCallback = () =>
        {
            calls++; AssertSafeStartupFenced();
            StartupReserveCallback = () => { calls++; AssertSafeStartupFenced(); };
        };
        Begin(); Need(calls == 2); Finish();
    }
    private static void Run(string name)
    {
        if (name == "startup-preinstall-producers-unchanged") { StartupPreinstallControl(); return; }
        if (name == "startup-pre-root-allocation-failure") { StartupBeforeRootAllocationFailureControl(); return; }
        if (name == "startup-readiness-failure-before-install") { StartupReadinessFailureControl(1); return; }
        if (name == "startup-initial-ready-remains-retryable") { StartupInitialReadyControl(false); return; }
        if (name == "startup-initial-ready-after-execution-poisons") { StartupInitialReadyControl(true); return; }
        if (name == "startup-initial-readiness-error-after-execution") { StartupInitialReadinessErrorAfterExecutionControl(); return; }
        if (name == "startup-untracked-enter-initial-probe") { StartupExecutionReentryControl("initial", "enter"); return; }
        if (name == "startup-readiness-failure-before-root") { StartupReadinessFailureControl(2); return; }
        if (name == "startup-readiness-failure-after-root-publication") { StartupReadinessFailureControl(3); return; }
        if (name == "startup-readiness-failure-after-root") { StartupReadinessFailureControl(4); return; }
        if (name == "startup-readiness-failure-after-native") { StartupReadinessFailureControl(5); return; }
        if (name == "startup-readiness-failure-after-context") { StartupReadinessFailureControl(6); return; }
        if (name == "startup-ready-during-allocation") { StartupReadinessReentryControl("allocation"); return; }
        if (name == "startup-ready-during-root-publication") { StartupReadinessReentryControl("root-publication"); return; }
        if (name == "startup-ready-during-root-reservation") { StartupReadinessReentryControl("root"); return; }
        if (name == "startup-ready-during-native-reservation") { StartupReadinessReentryControl("native"); return; }
        if (name == "startup-ready-during-context") { StartupReadinessReentryControl("context"); return; }
        if (name == "startup-untracked-enter-root") { StartupExecutionReentryControl("root", "enter"); return; }
        if (name == "startup-untracked-enter-root-publication") { StartupExecutionReentryControl("root-publication", "enter"); return; }
        if (name == "startup-untracked-unwrap-root") { StartupExecutionReentryControl("root", "unwrap"); return; }
        if (name == "startup-untracked-inner-native") { StartupExecutionReentryControl("native", "inner"); return; }
        if (name == "startup-untracked-schedule-root") { StartupExecutionReentryControl("root", "schedule"); return; }
        if (name == "startup-untracked-continuation-native") { StartupExecutionReentryControl("native", "continuation"); return; }
        if (name == "startup-untracked-created-async-context") { StartupExecutionReentryControl("context", "created-async"); return; }
        if (name == "startup-untracked-required-transport-root") { StartupExecutionReentryControl("root", "required-transport"); return; }
        if (name == "startup-untracked-continuation-failed-native") { StartupExecutionReentryControl("native", "continuation-failed"); return; }
        if (name == "startup-untracked-observed-context") { StartupExecutionReentryControl("context", "observed"); return; }
        if (name == "startup-untracked-ensure-join-ready-native") { StartupExecutionReentryControl("native", "ensure-join-ready"); return; }
        if (name == "startup-untracked-dequeue-native") { StartupExecutionReentryControl("native", "dequeue"); return; }
        if (name == "startup-untracked-pop-context") { StartupExecutionReentryControl("context", "pop"); return; }
        if (name == "startup-untracked-bind-allocation") { StartupExecutionReentryControl("allocation", "bind"); return; }
        if (name == "startup-untracked-timer-accepted-root") { StartupExecutionReentryControl("root", "timer-accepted"); return; }
        if (name == "startup-untracked-timer-enter-native") { StartupExecutionReentryControl("native", "timer-enter"); return; }
        if (name == "startup-untracked-timer-deleted-context") { StartupExecutionReentryControl("context", "timer-deleted"); return; }
        if (name == "startup-untracked-enqueue-success-root") { StartupExecutionReentryControl("root", "enqueue-success"); return; }
        if (name == "startup-untracked-enqueue-fault-native") { StartupExecutionReentryControl("native", "enqueue-fault"); return; }
        if (name == "startup-untracked-timer-changed-context") { StartupExecutionReentryControl("context", "timer-changed"); return; }
        if (name == "startup-untracked-timer-leave-root") { StartupExecutionReentryControl("root", "timer-leave"); return; }
        if (name == "startup-untracked-exit-native") { StartupExecutionReentryControl("native", "exit"); return; }
        if (name == "startup-untracked-callback-completed-context") { StartupExecutionReentryControl("context", "callback-completed"); return; }
        if (name == "startup-untracked-completed-allocation") { StartupExecutionReentryControl("allocation", "completed"); return; }
        if (name == "startup-poisoned-cleanup-preserves-primary") { StartupPoisonedCleanupPreservesPrimaryControl(); return; }
        if (name == "startup-native-refusal-settles-root") { StartupNativeRefusalControl(0); return; }
        if (name == "startup-native-refusal-root-settlement-refused") { StartupNativeRefusalControl(1); return; }
        if (name == "startup-native-refusal-root-settlement-unknown") { StartupNativeRefusalControl(2); return; }
        if (name == "startup-native-reservation-unknown") { StartupNativeUnknownControl("unknown"); return; }
        if (name == "startup-native-reservation-unknown-after-untracked") { StartupNativeUnknownControl("unknown-poison"); return; }
        if (name == "startup-native-refusal-after-untracked-retains-root") { StartupNativeRefusalPoisonControl(); return; }
        if (name == "startup-native-reservation-malformed-zero-both") { StartupNativeUnknownControl("zero-both"); return; }
        if (name == "startup-root-reservation-malformed-zero-both") { StartupRootZeroBothControl(); return; }
        if (name == "startup-native-reservation-malformed-generation") { StartupNativeUnknownControl("generation"); return; }
        if (name == "startup-native-reservation-malformed-id") { StartupNativeUnknownControl("id"); return; }
        if (name == "startup-allocation-cleanup-succeeds") { StartupAllocationFailureControl(0); return; }
        if (name == "startup-allocation-native-settlement-refused") { StartupAllocationFailureControl(1); return; }
        if (name == "startup-allocation-native-settlement-unknown") { StartupAllocationFailureControl(2); return; }
        if (name == "startup-allocation-root-settlement-refused") { StartupAllocationFailureControl(3); return; }
        if (name == "startup-allocation-root-settlement-unknown") { StartupAllocationFailureControl(4); return; }
        if (name == "startup-context-failure-before-mutation") { StartupContextFailureControl(0); return; }
        if (name == "startup-context-failure-after-mutation") { StartupContextFailureControl(1); return; }
        if (name == "startup-context-and-clear-failure") { StartupContextFailureControl(2); return; }
        if (name == "startup-context-failure-retains-native-child") { StartupContextFailureControl(3); return; }
        if (name == "startup-context-reentry-fences-producers") { StartupContextReentryControl(); return; }
        if (name == "startup-allocation-reentry-fences-producers") { StartupAllocationReentryControl(); return; }
        if (name == "startup-reservation-reentry-fences-producers") { StartupReservationReentryControl(); return; }
        if (name == "untracked-startup-refused-before-admission")
        {
            Work.Enqueue(() => { }); Refuses(Begin, "managed-work-untracked-startup-work");
            Need(Owners.Count == 0); Work.Dequeue(); Begin(); Finish(); return;
        }
        if (name == "root-task-refusal-fences-reinstallation")
        {
            Limits[0] = 0;
            Refuses(Begin, "managed-work-admission-refused");
            var state = ManagedWorkRuntime.StartupForControl();
            Need(Owners.Count == 0 && Count(7) == 0 && state.Root == (0UL, 0UL) && !state.RootActive && !state.Installed);
            AssertStartupFenced();
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
            var state = ManagedWorkRuntime.StartupForControl();
            Need(state.Root == (0UL, 0UL) && !state.RootActive && !state.Installed);
            AssertStartupFenced();
            return;
        }
        if (name is "root-task-malformed-generation-fences-reinstallation" or "root-task-malformed-id-fences-reinstallation")
        {
            malformedReservationKind = 0;
            malformedGeneration = name.Contains("generation");
            Refuses(Begin, "managed-work-reservation-token");
            Need(unknownReservationToken != 0 && Owners.ContainsKey(unknownReservationToken) && Count(7) == 0);
            var state = ManagedWorkRuntime.StartupForControl();
            Need(state.Root == (malformedGeneration ? (0UL, unknownReservationToken) : (17UL, 0UL))
                && !state.RootActive && !state.Installed);
            AssertStartupFenced();
            return;
        }
        Begin();
        switch (name)
        {
            case "inline-pop-false-preserves-normal-dequeue": {
                var task = new Task(() => { });
                ManagedWorkRuntime.Schedule(task); Enqueue(task);
                var token = ManagedWorkRuntime.QueuedTokenForControl(task);
                var ticket = ManagedWorkRuntime.InlineQueued(task, true);
                Need(ticket is not null && !ManagedWorkRuntime.Popped(false, task));
                ManagedWorkRuntime.InlineQueueFinished(ticket, true);
                Need(ManagedWorkRuntime.QueuedTokenForControl(task) == token && Count(3) == 1);
                Need(ManagedWorkRuntime.Popped(true, task) && Count(3) == 0);
                var previous = ManagedWorkRuntime.Enter(task);
                task.RunSynchronously(); ManagedWorkRuntime.Completed(task);
                ManagedWorkRuntime.Exit(previous); Need(Count(0) == 1); Finish(); break;
            }
            case "inline-pop-exception-retains-frame": {
                var task = new Task(() => { }); ManagedWorkRuntime.Schedule(task); Enqueue(task);
                var ticket = ManagedWorkRuntime.InlineQueued(task, true);
                Need(ticket is not null && ManagedWorkRuntime.Popped(true, task));
                var previous = ManagedWorkRuntime.Enter(task);
                task.RunSynchronously(); ManagedWorkRuntime.Completed(task);
                ManagedWorkRuntime.Exit(previous);
                var original = new InvalidOperationException("inline-original-exception");
                try { try { throw original; } finally { ManagedWorkRuntime.InlineQueueFinished(ticket, false); } }
                catch (InvalidOperationException caught) when (ReferenceEquals(caught, original)) { }
                Work.Enqueue(() => throw new InvalidOperationException("must-not-dispatch-uncertain-inline"));
                Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-inline-uncertain");
                Need(Work.Count == 1 && controlDispatches == 0 && Count(0) == 2 && Count(3) == 0); break;
            }
            case "inline-pop-ack-refused":
            case "inline-pop-ack-unknown": {
                var task = new Task(() => { }); ManagedWorkRuntime.Schedule(task); Enqueue(task);
                var token = ManagedWorkRuntime.QueuedTokenForControl(task)!.Value;
                var ticket = ManagedWorkRuntime.InlineQueued(task, true); Need(ticket is not null);
                settlementRefusal = token.Id; settlementUnknown = name.EndsWith("unknown");
                Refuses(() => ManagedWorkRuntime.Popped(true, task), "managed-work-settlement-refused");
                ManagedWorkRuntime.InlineQueueFinished(ticket, false);
                Refuses(() => ManagedWorkRuntime.Popped(true, task), "managed-work-queue-uncertain");
                Need(refusedSettlements == 1 && Count(3) == (settlementUnknown ? 0 : 1)
                    && ManagedWorkRuntime.QueuedTokenForControl(task) == token);
                break;
            }
            case "inline-pop-owner-settlement-refused":
            case "inline-pop-owner-settlement-unknown": {
                var task = new Task(() => { }); ManagedWorkRuntime.Schedule(task); Enqueue(task);
                var ticket = ManagedWorkRuntime.InlineQueued(task, true); Need(ticket is not null);
                Need(ManagedWorkRuntime.Popped(true, task));
                var previous = ManagedWorkRuntime.Enter(task); settlementRefusal = context.Item2;
                settlementUnknown = name.EndsWith("unknown");
                task.RunSynchronously(); ManagedWorkRuntime.Completed(task); ManagedWorkRuntime.Exit(previous);
                Refuses(() => ManagedWorkRuntime.InlineQueueFinished(ticket, true), "managed-work-settlement-refused");
                Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-double-settle");
                Need(refusedSettlements == 1 && Count(0) == (settlementUnknown ? 1 : 2)); break;
            }
            case "inline-pop-reentrant-fences-same-task": {
                var task = new Task(() => { }); ManagedWorkRuntime.Schedule(task); Enqueue(task);
                var token = ManagedWorkRuntime.QueuedTokenForControl(task)!.Value;
                var ticket = ManagedWorkRuntime.InlineQueued(task, true); Need(ticket is not null);
                afterSettlementTarget = token.Id;
                AfterSettlementCallback = () => {
                    Need(ManagedWorkRuntime.InlineQueued(task, true) is null);
                    Refuses(() => ManagedWorkRuntime.Popped(true, task), "managed-work-queue-uncertain");
                };
                Need(ManagedWorkRuntime.Popped(true, task));
                var previous = ManagedWorkRuntime.Enter(task);
                task.RunSynchronously(); ManagedWorkRuntime.Completed(task); ManagedWorkRuntime.Exit(previous);
                Need(Count(0) == 2); ManagedWorkRuntime.InlineQueueFinished(ticket, true);
                Need(Count(0) == 1); Finish(); break;
            }
            case "inline-pop-reentrant-normal-dequeue": {
                var task = new Task(() => { }); ManagedWorkRuntime.Schedule(task); Enqueue(task);
                var ticket = ManagedWorkRuntime.InlineQueued(task, true); Need(ticket is not null);
                // A same-task ordinary dequeue reenters after claim, before the
                // scheduler's own pop returns false. Its exact record is held.
                Need(ManagedWorkRuntime.Popped(true, task));
                Need(!ManagedWorkRuntime.Popped(false, task));
                ManagedWorkRuntime.InlineQueueFinished(ticket, true);
                Need(Count(3) == 0 && Count(0) == 2 && !task.IsCompleted);
                var previous = ManagedWorkRuntime.Enter(task);
                task.RunSynchronously(); ManagedWorkRuntime.Completed(task); ManagedWorkRuntime.Exit(previous);
                Need(Count(0) == 1); Finish(); break;
            }
            case "inline-pop-reset-fenced-retains-uncertainty": {
                Limits[0] = 3; Limits[3] = 2;
                var outer = new Task(() => { }); var later = new Task(() => { });
                ManagedWorkRuntime.Schedule(outer); ManagedWorkRuntime.Schedule(later);
                Enqueue(outer); Enqueue(later);
                var dispatch = ManagedWorkRuntime.BeginDispatch(outer);
                var previous = ManagedWorkRuntime.EnterDispatch(outer, dispatch);
                ManagedWorkRuntime.ResetStarting(dispatch);
                Need(ManagedWorkRuntime.InlineQueued(later, true) is null);
                Need(!ManagedWorkRuntime.Popped(false, later) && Count(3) == 1);
                Refuses(() => ManagedWorkRuntime.Popped(true, later), "managed-work-reset-context-unavailable");
                Need(Count(3) == 1);
                Refuses(() => ManagedWorkRuntime.Popped(true, later), "managed-work-reset-context-unavailable");
                ManagedWorkRuntime.Exit(previous); ManagedWorkRuntime.ResetReady(dispatch);
                ManagedWorkRuntime.ResetFinished(dispatch); ManagedWorkRuntime.DispatchReturned(dispatch);
                Refuses(() => ManagedWorkRuntime.Popped(true, later), "managed-work-queue-uncertain");
                Work.Enqueue(() => throw new InvalidOperationException("must-not-dispatch-uncertain-pop"));
                Refuses(ManagedWorkRuntime.JoinAcceptedWork, "managed-work-inline-uncertain");
                Need(Work.Count == 1 && controlDispatches == 0 && Count(3) == 1); break;
            }
            case "inline-pop-required-continuation-keeps-parent-frame": {
                Limits[3] = 2;
                object callback = new(); Enqueue(callback);
                Need(ManagedWorkRuntime.Popped(true, callback));
                var parent = ManagedWorkRuntime.Enter(callback);
                var task = new Task(() => { });
                ManagedWorkRuntime.CreatedAsync(task); Enqueue(task);
                var ticket = ManagedWorkRuntime.InlineQueued(task, true);
                Need(ticket is not null && ManagedWorkRuntime.Popped(true, task));
                var previous = ManagedWorkRuntime.Enter(task);
                task.RunSynchronously(); ManagedWorkRuntime.Completed(task); ManagedWorkRuntime.Exit(previous);
                ManagedWorkRuntime.InlineQueueFinished(ticket, true);
                Need(Count(0) == 2 && !ManagedWorkRuntime.CallbackDoneForControl(callback));
                ManagedWorkRuntime.Exit(parent); ManagedWorkRuntime.CallbackCompleted(callback);
                Need(Count(0) == 1); Finish(); break;
            }
            case "inline-pop-original-owner-must-survive-frame": {
                Limits[0] = 2;
                var task = new Task(() => { });
                ManagedWorkRuntime.Schedule(task); Enqueue(task);
                var ticket = ManagedWorkRuntime.InlineQueued(task, true);
                Need(ticket is not null && ManagedWorkRuntime.Popped(true, task));
                var previous = ManagedWorkRuntime.Enter(task);
                task.RunSynchronously(); ManagedWorkRuntime.Completed(task);
                Need(Count(0) == 2 && Count(3) == 0);
                ManagedWorkRuntime.Exit(previous);
                ManagedWorkRuntime.InlineQueueFinished(ticket, true);
                Need(Count(0) == 1); Finish(); break;
            }
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
            case "required-result-observed-during-allocation": RequiredResultObservationControl("allocation"); break;
            case "required-result-observed-after-publication": RequiredResultObservationControl("published"); break;
            case "required-result-observed-during-reservation": RequiredResultObservationControl("reserve"); break;
            case "required-result-observed-after-return": RequiredResultObservationControl("returned"); break;
            case "required-result-observed-during-settlement": RequiredResultObservationControl("settle"); break;
            case "required-result-unknown-retains-custody": RequiredResultUnknownControl("unknown"); break;
            case "required-result-malformed-generation-retains-custody": RequiredResultUnknownControl("generation"); break;
            case "required-result-malformed-id-retains-custody": RequiredResultUnknownControl("id"); break;
            case "required-result-refusal-restores-pending": RequiredResultRefusalControl(); break;
            case "required-result-transport-after-publication": RequiredResultTransportControl(false); break;
            case "required-result-transport-during-reservation": RequiredResultTransportControl(true); break;
            case "required-result-allocation-failure-preserves-parent": RequiredResultAllocationFailureControl(); break;
            case "required-result-slot-reentry-preserves-owner": RequiredResultSlotReentryControl(); break;
            case "required-result-active-alias-observation": RequiredResultActiveAliasControl(); break;
            case "required-result-uncertain-alias-fences-entry": RequiredResultUncertainAliasControl(); break;
            case "required-result-ordinary-alias-preserves-parent": RequiredResultOrdinaryAliasControl(); break;
            case "independent-inner-observed-fault": IndependentInnerFaultControl(); break;
            case "inner-scheduled-after-alias": InnerScheduledAfterAliasControl(); break;
            case "independent-inner-releases-capacity": IndependentInnerCapacityControl(); break;
            case "shared-inner-scheduled-before-alias": SharedIndependentInnerControl(false); break;
            case "shared-inner-scheduled-after-alias": SharedIndependentInnerControl(true); break;
            case "independent-inner-reentrant-admission": IndependentInnerReentryControl(); break;
            case "independent-inner-admission-refusal": IndependentInnerRefusalControl(false); break;
            case "independent-inner-admission-unknown": IndependentInnerRefusalControl(true); break;
            case "inner-and-outer-alias-no-duplicate": InnerAndOuterAliasControl(false); break;
            case "inner-and-outer-alias-reentrant-no-duplicate": InnerAndOuterAliasControl(true); break;
            case "inner-and-inactive-outer-alias-fenced": InnerAndInactiveOuterAliasControl(); break;
            case "inactive-inner-alias-fences-primary": InactiveInnerAliasWithPrimaryControl(false); break;
            case "inactive-inner-result-transition-fences-primary": InactiveInnerAliasWithPrimaryControl(true); break;
            case "multiple-unwrap-first-unobserved": MultipleUnwrapFaultControl("second"); break;
            case "multiple-unwrap-second-unobserved": MultipleUnwrapFaultControl("first"); break;
            case "multiple-unwrap-both-observed": MultipleUnwrapFaultControl("both"); break;
            case "multiple-unwrap-neither-observed": MultipleUnwrapFaultControl("neither"); break;
            case "multiple-unwrap-first-completes-before-pending": MultipleUnwrapPendingControl(true); break;
            case "multiple-unwrap-second-completes-before-pending": MultipleUnwrapPendingControl(false); break;
            case "multiple-unwrap-required-capacity": MultipleUnwrapCapacityControl(); break;
            case "successful-unwrap-releases-capacity": SuccessfulUnwrapCapacityControl(); break;
            case "inline-pop-retains-unwrap-owner": InlinePopRetainsUnwrapControl(); break;
            case "dispatch-reset-early-exposes-capacity": DispatchContextResetControl(true); break;
            case "dispatch-reset-retains-owner": DispatchContextResetControl(false); break;
            case "dispatch-reset-nested-frame-identity": DispatchNestedResetControl(); break;
            case "dispatch-reset-transition-preserves-queued-work": DispatchResetTransitionFenceControl(); break;
            case "dispatch-reset-null-context-refused": DispatchResetAttributionControl(false); break;
            case "dispatch-reset-explicit-root-context": DispatchResetAttributionControl(true); break;
            case "dispatch-execute-throw-retains-owner": DispatchBoundaryExceptionControl(false); break;
            case "dispatch-reset-throw-retains-owner": DispatchBoundaryExceptionControl(true); break;
            case "dispatch-reset-throwing-notification": DispatchThrowingResetControl(); break;
            case "dispatch-reset-throwing-child": DispatchThrowingResetChild(); break;
            case "dispatch-queue-ack-refused": DispatchQueueAckControl(false); break;
            case "dispatch-queue-ack-unknown": DispatchQueueAckControl(true); break;
            case "dispatch-owner-ack-refused": DispatchOwnerAckControl(false); break;
            case "dispatch-owner-ack-unknown": DispatchOwnerAckControl(true); break;
            case "dispatch-identity-change-fences-frame": DispatchIdentityChangeControl(); break;
            case "dispatch-exit-failure-retains-frame": DispatchExitFailureControl(); break;
            case "dispatch-reset-entry-failure-before": DispatchResetContextFailureControl(false, false); break;
            case "dispatch-reset-entry-failure-after": DispatchResetContextFailureControl(false, true); break;
            case "dispatch-reset-return-failure-before": DispatchResetContextFailureControl(true, false); break;
            case "dispatch-reset-return-failure-after": DispatchResetContextFailureControl(true, true); break;
            case "dispatch-direct-task-success": DispatchDirectTaskControl(false); break;
            case "dispatch-direct-task-observed-fault": DispatchDirectTaskControl(true); break;
            case "dispatch-queued-sibling-retains-owner": DispatchQueuedSiblingControl(); break;
            case "required-result-settlement-refusal-retains-custody": RequiredResultSettlementFailureControl(false); break;
            case "required-result-settlement-unknown-retains-custody": RequiredResultSettlementFailureControl(true); break;
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
