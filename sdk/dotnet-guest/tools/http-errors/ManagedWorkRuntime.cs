using System;
using System.Threading;
using System.Threading.Tasks;

namespace Lsf.CompilerOwned;

// Copied into the authenticated CoreLib only by the selected compiler port.
// The metadata accessors are bound to exact original CoreLib members;
// their source bodies deliberately refuse execution before that derivation.
public static partial class ManagedWorkRuntime
{
    public interface ContextSource
    {
        ExecutionContext? CapturedContext();
    }

    private const int MaximumRecords = 32;
    private const int MaximumQueued = 64;
    private const int TaskKind = 0;
    private const int QueuedKind = 3;
    private const int ResultKind = 6;
    private const int NativeKind = 7;

    private sealed class Record
    {
        internal object Primary = null!;
        internal Task? Completion;
        internal Task? Outer;
        internal Task? Inner;
        internal (ulong Generation, ulong Id) Token;
        internal (ulong Generation, ulong Id) PendingResult;
        internal bool Active;
        internal bool Root;
        internal bool Timer;
        internal bool Result;
        internal bool Observed;
        internal bool CallbackDone;
        // 1: conversion in flight; 2: uncertain; 3: restoring adapter context.
        internal byte ResultTransition;
    }

    private sealed class Queued
    {
        internal object Item = null!;
        internal Record Owner = null!;
        internal (ulong Generation, ulong Id) Token;
        // Bit 0 fences uncertainty and bit 2 marks an unfinished enqueue.
        internal byte State;
    }

    private sealed class Required
    {
        internal Task Task = null!;
        internal Record Owner = null!;
        internal bool Observed;
        internal bool Transport;
        // 1: Result admission in flight; 2: unknown or failed acknowledgement.
        internal byte ResultTransition;
    }

    private static Func<int, ulong, ulong, (ulong Generation, ulong Id)>? reserve;
    private static Action<ulong, ulong>? settle;
    private static Action? close;
    private static Action<ulong, ulong>? adapterContext;
    private static Record?[]? records;
    private static Queued?[]? queued;
    private static Required?[]? required;
    private static AsyncLocal<Record?>? current;
    private static Record? root;
    private static (ulong Generation, ulong Id) storage;
    private static bool closing;
    private static bool installed;
    // Nonnegative in-flight count; -1 records untracked startup activity.
    private static int admissions;
    // Erased by the compiler unless the source-control fixture supplies it.
    static partial void QueueAllocationControl();
    static partial void RecordAllocationControl();
    static partial void RequiredResultPublishedControl();
    static partial void RequiredResultReservedControl();
    static partial void StartupAllocationControl();
    static partial void StartupRootPublishedControl();

    public static void Install(
        Func<int, ulong, ulong, (ulong Generation, ulong Id)> register,
        Action<ulong, ulong> release, Action beginClosing, Action<ulong, ulong> setContext)
    {
        if (installed || reserve is not null || admissions != 0 || register is null || release is null
            || beginClosing is null || setContext is null)
            throw new InvalidOperationException("managed-work-installation");
        reserve = register; settle = release; close = beginClosing; adapterContext = setContext;
        bool startupReady;
        try { startupReady = ReadySource(); }
        catch
        {
            // No host registration has been attempted. A clean probe failure
            // may retain the original pre-install retry behavior.
            if (admissions == 0) { reserve = null; settle = null; close = null; adapterContext = null; }
            throw;
        }
        if (startupReady)
        {
            if (admissions == 0) { reserve = null; settle = null; close = null; adapterContext = null; }
            throw new InvalidOperationException("managed-work-untracked-startup-work");
        }
        if (admissions != 0) throw new InvalidOperationException("managed-work-untracked-startup-work");
        StartupAllocationControl();
        try { startupReady = ReadySource(); } catch { admissions = -1; throw; }
        if (startupReady || admissions != 0)
        { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
        // Publish dormant custody before either host registration. The root
        // cannot admit managed descendants until context installation returns.
        var startupRoot = new Record { Primary = new object(), Root = true };
        root = startupRoot;
        StartupRootPublishedControl();
        try { startupReady = ReadySource(); } catch { admissions = -1; throw; }
        if (startupReady || admissions != 0)
        { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
        var rootToken = register(TaskKind, 0, 0);
        startupRoot.Token = rootToken;
        if (rootToken == default) throw new InvalidOperationException("managed-work-admission-refused");
        if (rootToken.Generation == 0 || rootToken.Id == 0)
            throw new InvalidOperationException("managed-work-reservation-token");
        try { startupReady = ReadySource(); } catch { admissions = -1; throw; }
        if (startupReady || admissions != 0)
        { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
        bool nativeAbsent = false, nativeKnown = false, contextAttempted = false;
        try
        {
            storage = register(NativeKind, rootToken.Generation, rootToken.Id);
            if (storage == default)
            {
                nativeAbsent = true; // The selected bridge returned the explicit WIT refusal.
                throw new InvalidOperationException("managed-work-admission-refused");
            }
            if (storage.Generation == 0 || storage.Id == 0)
                throw new InvalidOperationException("managed-work-reservation-token");
            nativeKnown = true;
            if (admissions != 0) throw new InvalidOperationException("managed-work-untracked-startup-work");
            StartupAllocationControl();
            records = new Record?[MaximumRecords];
            queued = new Queued?[MaximumQueued];
            required = new Required?[MaximumRecords];
            timers = new TimerOwner?[MaximumRecords];
            records[0] = startupRoot;
            current = new AsyncLocal<Record?>(ContextChanged);
            try { startupReady = ReadySource(); } catch { admissions = -1; throw; }
            if (startupReady || admissions != 0)
            { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            // Reentrant ExecutionContext notifications may restore this token,
            // but managed producers remain fenced while the root is dormant.
            startupRoot.ResultTransition = 3;
            contextAttempted = true;
            current.Value = startupRoot;
            try { startupReady = ReadySource(); } catch { admissions = -1; throw; }
            if (startupReady || admissions != 0)
            { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            startupRoot.ResultTransition = 0;
            startupRoot.Active = true;
            installed = true;
        }
        catch
        {
            startupRoot.ResultTransition = 0;
            if (contextAttempted)
            {
                // Native work may have escaped under the adapter token. Retain
                // both owners; an uncertain clear is not a retirement proof.
                try { adapterContext!(0, 0); } catch { }
            }
            else if (admissions != 0)
            {
                // An original dispatch or Timer mutation already crossed the
                // startup boundary. Its physical outcome cannot be inferred.
            }
            else if (nativeKnown)
            {
                // Root settlement is allowed only after Native acknowledgement.
                try
                {
                    release(storage.Generation, storage.Id);
                    release(rootToken.Generation, rootToken.Id);
                }
                catch { } // Preserve the original startup exception; never retry.
            }
            else if (nativeAbsent)
            {
                try { release(rootToken.Generation, rootToken.Id); } catch { }
            }
            throw;
        }
    }

    private static void ContextChanged(AsyncLocalValueChangedArgs<Record?> change)
    {
        var owner = change.CurrentValue;
        if (owner is not null && ((owner.Active && !owner.Result) || owner.ResultTransition == 3))
            adapterContext!(owner.Token.Generation, owner.Token.Id);
        else
            adapterContext!(0, 0);
    }

    private static Record? Find(object item)
    {
        if (records is null) return null;
        Record? match = null;
        Record? taskPrimary = null;
        Record? inactiveTaskAlias = null;
        foreach (var owner in records)
            if (owner is not null && (ReferenceEquals(owner.Primary, item)
                || ReferenceEquals(owner.Outer, item) || ReferenceEquals(owner.Inner, item)))
            {
                // A completed fault can also be an alias of its live parent.
                // Its exact Result owner must govern observation and admission.
                if (owner.Result && ReferenceEquals(owner.Primary, item)) return owner;
                // An independently scheduled Task can also be another
                // Unwrap owner's Inner. Its own original owner takes priority
                // for dispatch, completion and observation, subject to the
                // inactive-alias fence below.
                if (item is Task && ReferenceEquals(owner.Primary, item)) taskPrimary ??= owner;
                if (item is Task && !owner.Active && !ReferenceEquals(owner.Primary, item))
                    inactiveTaskAlias ??= owner;
                match ??= owner;
            }
        // An unresolved alias is still physical custody of the same Task.
        // Keep it fenced even when another active Task owner also exists.
        if (inactiveTaskAlias is not null) return inactiveTaskAlias;
        if (taskPrimary is not null) return taskPrimary;
        if (match is not null) return match;
        if (FindTimer(item) is { } timer) return timer.Owner;
        if (required is not null)
            foreach (var pending in required)
                if (pending is not null && ReferenceEquals(pending.Task, item)) return pending.Owner;
        return null;
    }

    private static Record? Parent()
    {
        var owner = current!.Value;
        if (closing && (owner is null || !owner.Active || owner.Root || owner.Result))
            throw new InvalidOperationException("managed-work-independent-admission-closed");
        if (owner is not null && (!owner.Active || owner.Result))
            throw new InvalidOperationException("managed-work-parent-retired");
        return owner;
    }

    private static (ulong Generation, ulong Id) Reserve(int kind, Record? parent)
    {
        var token = parent?.Token ?? default;
        var result = reserve!(kind, token.Generation, token.Id);
        if (result == default) throw new InvalidOperationException("managed-work-admission-refused");
        if (result.Generation == 0 || result.Id == 0)
            throw new InvalidOperationException("managed-work-reservation-token");
        return result;
    }

    private static int FreeRecord()
    {
        for (int i = 1; i < MaximumRecords; i++) if (records![i] is null) return i;
        throw new InvalidOperationException("managed-work-record-limit");
    }

    private static Record Admit(object item, Task? completion, Record? parent,
        out bool created, bool activate, Queued? admission, bool independentInner)
    {
        var activation = root;
        if (!installed || activation is null || !activation.Active)
            throw new InvalidOperationException("managed-work-finalization-uncertain");
        if (admissions == int.MaxValue) throw new InvalidOperationException("managed-work-admission-in-progress");
        admissions++;
        try
        {
            created = false;
            // Allocation may reenter and fill a slot or admit this same item.
            RecordAllocationControl();
            var owner = new Record { Primary = item, Completion = completion };
            if (!installed || !ReferenceEquals(root, activation) || !activation.Active)
                throw new InvalidOperationException("managed-work-activation-changed");
            var existing = Find(item);
            if (existing is { Active: false } or { Result: true })
                throw new InvalidOperationException("managed-work-owner-retired");
            if (independentInner && existing is not null && ReferenceEquals(existing.Inner, item)
                && !ReferenceEquals(existing.Primary, item) && !ReferenceEquals(existing.Outer, item))
            {
                // Allocation can reenter and publish a separate Primary or
                // Outer after an earlier Inner alias. Check every match before
                // treating the item as independently unowned.
                Record? alreadyAdmitted = null;
                foreach (var candidate in records!)
                {
                    if (candidate is null || (!ReferenceEquals(candidate.Primary, item)
                        && !ReferenceEquals(candidate.Outer, item) && !ReferenceEquals(candidate.Inner, item))) continue;
                    if (!candidate.Active || candidate.Result)
                        throw new InvalidOperationException("managed-work-owner-retired");
                    if (ReferenceEquals(candidate.Primary, item) || ReferenceEquals(candidate.Outer, item))
                        alreadyAdmitted ??= candidate;
                }
                existing = alreadyAdmitted;
            }
            if (existing is not null) return existing;
            // The allocation may also have closed the root or retired/converted
            // the originally captured parent before registration begins.
            if (closing && (parent is null || !parent.Active || parent.Root || parent.Result))
                throw new InvalidOperationException("managed-work-independent-admission-closed");
            if (parent is not null && (!parent.Active || parent.Result))
                throw new InvalidOperationException("managed-work-parent-retired");
            int index = FreeRecord();
            // The existing bounded table retains a provisional inactive owner
            // even if registration mutated the host and then failed to return.
            records![index] = owner;
            if (admission is not null) admission.Owner = owner;
            var parentToken = parent?.Token ?? default;
            var token = reserve!(TaskKind, parentToken.Generation, parentToken.Id);
            owner.Token = token;
            if (token == default)
            {
                records[index] = null; // The selected bridge returned a definite WIT refusal.
                if (admission is not null) admission.Owner = null!;
                throw new InvalidOperationException("managed-work-admission-refused");
            }
            if (token.Generation == 0 || token.Id == 0)
                throw new InvalidOperationException("managed-work-reservation-token");
            owner.Active = activate;
            created = true;
            return owner;
        }
        finally { admissions--; }
    }

    public static void Schedule(Task task)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return;
        }
        var existing = Find(task);
        if (existing is { Active: false }) throw new InvalidOperationException("managed-work-owner-retired");
        bool innerOnly = existing is { Result: false } && ReferenceEquals(existing.Inner, task)
            && !ReferenceEquals(existing.Primary, task) && !ReferenceEquals(existing.Outer, task);
        if (innerOnly)
            foreach (var candidate in records!)
            {
                if (candidate is null || (!ReferenceEquals(candidate.Primary, task)
                    && !ReferenceEquals(candidate.Outer, task) && !ReferenceEquals(candidate.Inner, task))) continue;
                if (!candidate.Active) throw new InvalidOperationException("managed-work-owner-retired");
                if (candidate.Result || ReferenceEquals(candidate.Primary, task) || ReferenceEquals(candidate.Outer, task))
                    innerOnly = false;
            }
        if (task.IsCompleted) return;
        if (existing is not null && !innerOnly) return;
        // An Inner-only alias is not an admission for this independently
        // scheduled Task. Recheck after allocation in case of reentry.
        Admit(task, task, Parent(), out _, true, null, independentInner: true);
    }

    public static void Continuation(Task task)
    {
        Schedule(task);
    }

    public static void ContinuationFailed(Task task)
    {
        if (!installed) { if (reserve is not null) admissions = -1; return; }
        var owner = Find(task);
        if (owner is { Active: false }) throw new InvalidOperationException("managed-work-double-settle");
        if (owner is null || owner.Root || owner.Result || task.IsCompleted || !ReferenceEquals(owner.Completion, task)) return;
        foreach (var item in queued!) if (item is not null && ReferenceEquals(item.Owner, owner)) return;
        if (!HasRequired(owner)) Release(owner);
    }

    public static void Unwrap(Task promise, Task outer)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return;
        }
        if (Find(promise) is { Active: false }) throw new InvalidOperationException("managed-work-owner-retired");
        if (promise.IsCompleted) return;
        var owner = Find(outer);
        if (owner is { Active: false } or { Result: true }) throw new InvalidOperationException("managed-work-owner-retired");
        if (owner is null) owner = Admit(promise, promise, Parent(), out _, true, null, false);
        else if (ReferenceEquals(owner.Outer, outer) && !ReferenceEquals(owner.Primary, outer))
        {
            // A second proxy over the same original outer is a distinct
            // required continuation, not a replacement for the first.
            Remember(promise, false, owner);
        }
        else
        {
            owner.Outer = outer;
            owner.Primary = promise;
            owner.Completion = promise;
        }
    }

    public static void Inner(Task promise, Task? inner)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return;
        }
        if (inner is null) return;
        var owner = Find(promise);
        if (owner is { Active: false } or { Result: true }) throw new InvalidOperationException("managed-work-owner-retired");
        if (owner is not null) owner.Inner = inner;
    }

    // Exact producer-bound internal content work must finish, but its error is
    // still reported by the original request future. This adds no success path.
    public static void RequiredTransport(Task task)
    {
        Remember(task, true, null);
    }

    // A state-machine box is an actual required continuation of its current
    // logical flow, including direct async calls and async-void callbacks.
    // The scheduled Task.Run owner is not charged a second time for its inner
    // builder task. Every retained box shares the same finite metadata lease.
    public static void CreatedAsync(Task task)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return;
        }
        if (task.IsCompleted) return;
        Remember(task, false, null);
        BindAsyncContext(task);
    }

    private static void Remember(Task task, bool transport, Record? ownerOverride)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return;
        }
        for (int i = 0; i < MaximumRecords; i++)
            if (required![i] is { } existing && ReferenceEquals(existing.Task, task))
            {
                existing.Transport |= transport;
                return;
            }
        if (task.IsCompleted) return;
        var owner = ownerOverride ?? current!.Value;
        if (owner is null || !owner.Active || owner.Result)
            throw new InvalidOperationException("managed-work-transport-parent");
        if (ReferenceEquals(owner.Completion, task)) return;
        for (int i = 0; i < MaximumRecords; i++)
        {
            if (required![i] is null)
            {
                required[i] = new Required { Task = task, Owner = owner, Transport = transport };
                return;
            }
        }
        throw new InvalidOperationException("managed-work-required-continuation-limit");
    }

    public static object? Enqueue(object item)
    {
        if (!installed)
        {
            if (reserve is not null) throw new InvalidOperationException("managed-work-installation-in-progress");
            return null;
        }
        var activation = root;
        if (activation is null || !activation.Active)
            throw new InvalidOperationException("managed-work-finalization-uncertain");
        if (admissions == int.MaxValue) throw new InvalidOperationException("managed-work-admission-in-progress");
        admissions++;
        try
        {
            // Allocation can run finalizers. Scan only after it, then reserve the
            // selected slot before any user-supplied captured-context accessor.
            QueueAllocationControl();
            var pending = new Queued { Item = item, State = 5 };
            if (!installed || !ReferenceEquals(root, activation) || !activation.Active)
                throw new InvalidOperationException("managed-work-activation-changed");
            int index = -1;
            for (int i = 0; i < MaximumQueued; i++)
            {
                if (queued![i] is { } existing && ReferenceEquals(existing.Item, item))
                {
                    if ((existing.State & 1) != 0)
                        throw new InvalidOperationException("managed-work-queue-uncertain");
                    if (FindTimer(item) is null) throw new InvalidOperationException("managed-work-duplicate-enqueue");
                }
                if (index < 0 && queued[i] is null) index = i;
            }
            if (index < 0) throw new InvalidOperationException("managed-work-queue-record-limit");
            queued![index] = pending;
            try
            {
                var owner = Find(item);
                if (owner is { Active: false } or { Result: true })
                    throw new InvalidOperationException(owner.Timer
                        ? "managed-timer-settlement-uncertain" : "managed-work-owner-retired");
                bool created = false;
                if (owner is null)
                {
                    var captured = WorkContext(item) as Record;
                    if (captured is not null && (!captured.Active || captured.Result))
                        throw new InvalidOperationException("managed-work-captured-parent-retired");
                    // The captured-context accessor can reenter Schedule/Unwrap
                    // without using this queue, so its result invalidates Find.
                    owner = Find(item);
                    if (owner is { Active: false } or { Result: true })
                        throw new InvalidOperationException(owner.Timer
                            ? "managed-timer-settlement-uncertain" : "managed-work-owner-retired");
                    if (owner is null)
                    {
                        if (Maintenance(item)) owner = root!;
                        else if (RequiredContinuation(item) && captured is not null) owner = captured;
                        else
                        {
                            var parent = captured ?? Parent();
                            if (closing && (parent is null || parent.Root))
                                throw new InvalidOperationException("managed-work-independent-admission-closed");
                            owner = Admit(item, null, parent, out created, false, pending, false);
                        }
                    }
                }
                if (!created && (!owner.Active || owner.Result))
                    throw new InvalidOperationException(owner.Timer
                        ? "managed-timer-settlement-uncertain" : "managed-work-owner-retired");
                pending.Owner = owner;
                var queueToken = reserve!(QueuedKind, owner.Token.Generation, owner.Token.Id);
                pending.Token = queueToken;
                if (queueToken == default)
                {
                    var timer = owner.Timer ? FindTimer(item) : null;
                    if (timer is not null && timer.Mutation >= 0 && timer.Accepted > 0)
                    {
                        timer.Accepted--; queued[index] = null;
                    }
                    else if (!owner.Timer && !created) queued[index] = null;
                    else if (created && !owner.Active)
                    {
                        // This owner has never been logically active. Settle it
                        // once; keep both records if that outcome is uncertain.
                        int slot = -1;
                        for (int i = 1; i < MaximumRecords; i++)
                            if (ReferenceEquals(records![i], owner)) { slot = i; break; }
                        if (slot >= 0)
                            try
                            {
                                settle!(owner.Token.Generation, owner.Token.Id);
                                if (ReferenceEquals(records![slot], owner) && ReferenceEquals(queued[index], pending))
                                { records[slot] = null; queued[index] = null; }
                            }
                            catch { } // Retain the inactive owner and original refusal.
                    }
                    throw new InvalidOperationException("managed-work-admission-refused");
                }
                if (queueToken.Generation == 0 || queueToken.Id == 0)
                    throw new InvalidOperationException("managed-work-reservation-token");
                if (created) owner.Active = true;
                pending.State = 4;
                return pending;
            }
            catch
            {
                if (pending.Owner is null && ReferenceEquals(queued[index], pending)) queued[index] = null;
                throw;
            }
        }
        finally { admissions--; }
    }

    public static void EnqueueFinalized(object? ticket, int outcome)
    {
        if (!installed)
        {
            if (reserve is not null)
            {
                admissions = -1;
                if (outcome == 2) throw new InvalidOperationException("managed-work-untracked-startup-work");
            }
            return; // A fault handler must preserve its original exception.
        }
        var pending = ticket as Queued ?? throw new InvalidOperationException("managed-work-queue-ticket");
        if (outcome == 1)
        {
            // The insertion call may already have published this item, and
            // duplicate physical occurrences cannot be distinguished.
            foreach (var existing in queued!)
                if (existing is not null && ReferenceEquals(existing.Item, pending.Item))
                    existing.State |= 1;
            return;
        }
        int index = -1;
        for (int i = 0; i < MaximumQueued; i++)
            if (ReferenceEquals(queued![i], pending)) { index = i; break; }
        if (index < 0) throw new InvalidOperationException("managed-work-queue-ticket");
        if (outcome == 2)
        {
            foreach (var existing in queued!)
                if (existing is not null && ReferenceEquals(existing.Item, pending.Item) && (existing.State & 1) != 0)
                    throw new InvalidOperationException("managed-work-queue-uncertain");
            if ((pending.State & 4) == 0) throw new InvalidOperationException("managed-work-queue-ticket");
            pending.State = (byte)(pending.State & ~4);
            return;
        }
        if (outcome != 0) throw new InvalidOperationException("managed-work-queue-ticket");
        if ((pending.State & 1) != 0) return;
        if ((pending.State & 4) == 0) throw new InvalidOperationException("managed-work-queue-ticket");
        var timer = pending.Owner.Timer ? FindTimer(pending.Item) : null;
        if (pending.Owner.Timer && (timer is null || timer.Mutation < 0 || timer.Accepted == 0))
        {
            pending.State |= 1;
            return;
        }
        pending.State |= 1;
        try { settle!(pending.Token.Generation, pending.Token.Id); }
        catch { return; } // Keep the exact owner and preserve the original queue error.
        queued![index] = null;
        if (timer is not null)
        {
            // Its producer can still be unwinding. Remove only the failed
            // callback admission; retirement is checked after that boundary.
            timer.Accepted--;
        }
        // The original logging path can invoke user code before insertion.
        // Even a newly created Task owner may have escaped to that reentrant
        // code, so retain it rather than guessing that no context or work uses it.
    }

    public static void Dequeue(object item)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return;
        }
        foreach (var existing in queued!)
            if (existing is not null && ReferenceEquals(existing.Item, item) && (existing.State & 1) != 0)
                throw new InvalidOperationException("managed-work-queue-uncertain");
        for (int i = 0; i < MaximumQueued; i++)
            if (queued![i] is { } pending && ReferenceEquals(pending.Item, item)
                && (pending.State & 4) == 0)
            {
                // The host may have settled before trapping; retain this
                // exact queue record but never submit its token again.
                pending.State |= 1;
                settle!(pending.Token.Generation, pending.Token.Id);
                queued[i] = null;
                return;
            }
        foreach (var pending in queued!)
            if (pending is not null && ReferenceEquals(pending.Item, item) && (pending.State & 4) != 0)
                throw new InvalidOperationException("managed-work-queue-admission-pending");
        throw new InvalidOperationException("managed-work-unregistered-dequeue");
    }

    public static bool Popped(bool found, object item)
    {
        if (!installed && reserve is not null && found)
        { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
        if (installed && found) Dequeue(item);
        return found;
    }

    public static object? Enter(object item)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return null;
        }
        var previous = current!.Value;
        var owner = Find(item) ?? WorkContext(item) as Record;
        if (owner is null && Maintenance(item)) owner = root;
        if (owner is null || !owner.Active || owner.Result)
            throw new InvalidOperationException("managed-work-execution-parent");
        current.Value = owner;
        return previous;
    }

    public static object? EnterDispatch(object item)
    {
        if (installed && item is Task task && task.IsCompleted)
        {
            if (Find(item) is { Active: false }) throw new InvalidOperationException("managed-work-execution-parent");
            return current!.Value;
        }
        return Enter(item);
    }

    public static void Exit(object? previous)
    {
        if (!installed && reserve is not null) admissions = -1;
        if (installed) current!.Value = (Record?)previous;
    }

    public static void CallbackCompleted(object item)
    {
        if (!installed) { if (reserve is not null) admissions = -1; return; }
        var owner = Find(item);
        if (owner is { Timer: true }) { TryRetireTimer(FindTimer(owner.Primary)!); return; }
        // Task completion is handled by Completed, including a failed conversion.
        // A dormant queue-created owner has no Completion and stays fenced below.
        if (owner is { Completion: not null }) return;
        if (owner is { Active: false }) throw new InvalidOperationException("managed-work-double-settle");
        if (owner is not null && owner.Completion is null && !owner.Root)
        {
            owner.CallbackDone = true;
            if (!HasRequired(owner)) Release(owner);
        }
    }

    public static void Completed(Task task)
    {
        if (!installed) { if (reserve is not null) admissions = -1; return; }
        var owner = Find(task);
        if (owner is { Active: false }) throw new InvalidOperationException("managed-work-double-settle");
        if (owner is null || owner.Root || owner.Result || !ReferenceEquals(owner.Completion, task)) return;
        if (HasRequired(owner)) return;
        Finish(owner);
    }

    public static void Observed(Task task)
    {
        if (!installed) { if (reserve is not null) admissions = -1; return; }
        var owner = Find(task);
        if (owner is { Active: false } && (owner.ResultTransition == 0 || !ReferenceEquals(owner.Completion, task)))
            throw new InvalidOperationException("managed-work-double-settle");
        foreach (var pending in required!)
            if (pending is not null && ReferenceEquals(pending.Task, task)) pending.Observed = true;
        if (owner is not null && ReferenceEquals(owner.Completion, task))
        {
            owner.Observed = true;
            if (owner.Result && owner.ResultTransition == 0) Release(owner);
        }
    }

    private static bool HasRequired(Record owner)
    {
        bool found = false;
        for (int i = 0; i < MaximumRecords; i++)
        {
            var pending = required![i];
            if (pending is null || !ReferenceEquals(pending.Owner, owner)) continue;
            if (pending.ResultTransition == 2)
                throw new InvalidOperationException("managed-work-required-result-uncertain");
            if (pending.ResultTransition == 1) { found = true; continue; }
            if (pending.Task.IsCompleted) CompletedRequired(i);
            else found = true;
        }
        return found;
    }

    private static void CompletedRequired(int index)
    {
        var pending = required![index]!;
        if (pending.ResultTransition != 0)
            throw new InvalidOperationException("managed-work-required-result-uncertain");
        if (!pending.Task.IsFaulted || pending.Observed || pending.Transport)
        {
            required[index] = null;
            return;
        }
        var activation = root;
        if (!installed || activation is null || !activation.Active)
            throw new InvalidOperationException("managed-work-finalization-uncertain");
        if (admissions == int.MaxValue) throw new InvalidOperationException("managed-work-admission-in-progress");
        admissions++;
        pending.ResultTransition = 1;
        Record? result = null;
        int slot = -1;
        bool dispatched = false;
        try
        {
            RecordAllocationControl();
            result = new Record { Primary = pending.Task, Completion = pending.Task,
                Result = true, ResultTransition = 1 };
            if (!installed || !ReferenceEquals(root, activation) || !activation.Active
                || !ReferenceEquals(required![index], pending))
                throw new InvalidOperationException("managed-work-activation-changed");
            if (!pending.Owner.Active || pending.Owner.Result)
                throw new InvalidOperationException("managed-work-required-parent-retired");
            if (pending.Observed || pending.Transport) { required[index] = null; return; }
            slot = FreeRecord();
            records![slot] = result;
            RequiredResultPublishedControl();
            if (!ReferenceEquals(records[slot], result) || !ReferenceEquals(required[index], pending))
                throw new InvalidOperationException("managed-work-activation-changed");
            if (!pending.Owner.Active || pending.Owner.Result)
                throw new InvalidOperationException("managed-work-required-parent-retired");
            if (pending.Observed || pending.Transport)
            { records[slot] = null; required[index] = null; return; }
            dispatched = true;
            var token = reserve!(ResultKind, pending.Owner.Token.Generation, pending.Owner.Token.Id);
            result.Token = token;
            if (token == default)
            {
                // The selected bridge returned the explicit WIT refusal.
                dispatched = false;
                throw new InvalidOperationException("managed-work-admission-refused");
            }
            if (token.Generation == 0 || token.Id == 0)
                throw new InvalidOperationException("managed-work-reservation-token");
            RequiredResultReservedControl();
            if (pending.Observed || pending.Transport)
            {
                settle!(token.Generation, token.Id);
                records[slot] = null; required[index] = null;
                return;
            }
            required[index] = null;
            result.ResultTransition = 0;
            result.Active = true;
        }
        catch
        {
            if (dispatched)
            {
                pending.ResultTransition = 2;
                if (result is not null) result.ResultTransition = 2;
            }
            else
            {
                if (slot >= 0 && ReferenceEquals(records![slot], result)) records[slot] = null;
                pending.ResultTransition = 0;
            }
            throw;
        }
        finally { admissions--; }
    }

    private static void Finish(Record owner)
    {
        if (!owner.Active) throw new InvalidOperationException("managed-work-double-settle");
        if (owner.Result) return;
        if (owner.Completion is { } task && task.IsFaulted && !owner.Observed)
        {
            if (admissions == int.MaxValue) throw new InvalidOperationException("managed-work-admission-in-progress");
            admissions++;
            owner.ResultTransition = 1;
            owner.Active = false;
            try
            {
                // Do not leave the native adapter authorized by a logically
                // retired owner. Keep the managed AsyncLocal so Exit restores
                // the previous dispatch context in the usual way.
                if (ReferenceEquals(current!.Value, owner)) adapterContext!(0, 0);
                if (!owner.Observed)
                {
                    var result = reserve!(ResultKind, owner.Token.Generation, owner.Token.Id);
                    if (result == default)
                    {
                        // A typed WIT refusal proves no Result was registered.
                        // Restore authority only if its adapter update succeeds.
                        var refusal = new InvalidOperationException("managed-work-admission-refused");
                        try
                        {
                            // Context switches inside the adapter call must
                            // restore this token even though admission is still
                            // fenced by the inactive owner.
                            owner.ResultTransition = 3;
                            if (ReferenceEquals(current!.Value, owner))
                                adapterContext!(owner.Token.Generation, owner.Token.Id);
                            owner.ResultTransition = 0;
                            owner.Active = true;
                        }
                        catch
                        {
                            owner.ResultTransition = 2;
                            try { adapterContext!(0, 0); } catch { }
                        }
                        throw refusal;
                    }
                    if (result.Generation == 0 || result.Id == 0)
                        throw new InvalidOperationException("managed-work-reservation-token");
                    // Keep both tokens reachable until Task settlement is confirmed.
                    owner.PendingResult = result;
                }
                settle!(owner.Token.Generation, owner.Token.Id);
                if (owner.PendingResult != default)
                {
                    owner.Token = owner.PendingResult;
                    owner.PendingResult = default;
                    owner.Result = true;
                    if (!owner.Observed)
                    {
                        owner.ResultTransition = 0;
                        owner.Active = true;
                        return;
                    }
                    settle!(owner.Token.Generation, owner.Token.Id);
                }
                for (int i = 1; i < MaximumRecords; i++)
                    if (ReferenceEquals(records![i], owner)) { records[i] = null; return; }
                throw new InvalidOperationException("managed-work-missing-record");
            }
            catch
            {
                if (owner.ResultTransition is 1 or 3) owner.ResultTransition = 2;
                throw;
            }
            finally { admissions--; }
        }
        else Release(owner);
    }

    private static void Release(Record owner)
    {
        if (!owner.Active) throw new InvalidOperationException("managed-work-double-settle");
        if (owner.Timer) { TryRetireTimer(FindTimer(owner.Primary)!); return; }
        // For non-root owners, revoke logical use before settlement. The host
        // may settle and then trap, so retain the record and token on failure.
        if (!owner.Root) owner.Active = false;
        settle!(owner.Token.Generation, owner.Token.Id);
        owner.Active = false;
        for (int i = 1; i < MaximumRecords; i++)
            if (ReferenceEquals(records![i], owner)) { records[i] = null; return; }
        if (!owner.Root) throw new InvalidOperationException("managed-work-missing-record");
    }

    public static void JoinAcceptedWork()
    {
        if (!installed) throw new InvalidOperationException("managed-work-closing-state");
        if (admissions != 0) throw new InvalidOperationException("managed-work-admission-in-progress");
        if (closing) throw new InvalidOperationException("managed-work-closing-state");
        closing = true;
        close!();
        for (;;)
        {
            Task? pending = null;
            bool active = false;
            for (int i = 0; i < MaximumRecords; i++)
            {
                var work = required![i];
                if (work is not null)
                {
                    if (work.Task.IsCompleted) CompletedRequired(i);
                    else { active = true; pending ??= work.Task; }
                }
                var owner = records![i];
                if (owner is null || owner.Root) continue;
                if (owner.ResultTransition != 0) throw new InvalidOperationException("managed-work-double-settle");
                if (owner.Result) continue;
                if (owner.Completion is { } task)
                {
                    if (task.IsCompleted && !HasRequired(owner)) Finish(owner);
                    else { active = true; if (!task.IsCompleted) pending ??= task; }
                }
                else if (owner.CallbackDone && !HasRequired(owner)) Release(owner);
                else active = true;
            }
            bool queuedWork = false;
            foreach (var item in queued!) if (item is not null) { queuedWork = true; break; }
            active |= PendingTimers();
            if (!active && !queuedWork) break;
            if (!ReadySource()) throw new InvalidOperationException("managed-work-unproven-quiescence");
            if (pending is not null) WaitForCompletion(pending);
            else DispatchOnce();
        }
        AggregateException? failure = null;
        for (int i = 1; i < MaximumRecords; i++)
            if (records![i] is { Result: true, Completion: { } task } owner)
            {
                var original = task.Exception;
                if (original is not null) failure = failure is null ? original : new AggregateException(failure, original);
                if (owner.Active) Release(owner);
            }
        if (failure is not null) throw failure;
        current!.Value = root;
    }

    public static void EnsureJoinReady()
    {
        if (!installed && reserve is not null)
        { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
        if (installed && closing && !ReadySource())
            throw new InvalidOperationException("managed-work-unproven-quiescence");
    }

    public static void FinishedPhysicalDrain()
    {
        if (!installed) throw new InvalidOperationException("managed-work-finalization-state");
        if (admissions != 0) throw new InvalidOperationException("managed-work-admission-in-progress");
        if (!closing) throw new InvalidOperationException("managed-work-finalization-state");
        var finalRoot = root ?? throw new InvalidOperationException("managed-work-finalization-state");
        if (!finalRoot.Active) throw new InvalidOperationException("managed-work-finalization-uncertain");
        foreach (var owner in records!) if (owner is not null && !owner.Root)
            throw new InvalidOperationException("managed-work-finalization-owners");
        foreach (var item in queued!) if (item is not null)
            throw new InvalidOperationException("managed-work-finalization-queue");
        foreach (var timer in timers!) if (timer is not null)
            throw new InvalidOperationException("managed-work-finalization-timers");
        foreach (var item in required!) if (item is not null)
            throw new InvalidOperationException("managed-work-finalization-continuations");
        // Fence the entire terminal sequence before either host call: an
        // exception may follow settlement of storage, the root, or both.
        finalRoot.Active = false;
        try
        {
            settle!(storage.Generation, storage.Id);
            settle!(finalRoot.Token.Generation, finalRoot.Token.Id);
        }
        catch
        {
            // Clearing the adapter context must not replace the settlement
            // failure; the inactive root still fences any later finalization.
            try { current!.Value = null; } catch { }
            throw;
        }
        current!.Value = null;
        installed = false;
        records = null; queued = null; required = null; timers = null; current = null; root = null;
        reserve = null; settle = null; close = null; adapterContext = null;
        storage = default; closing = false;
    }

    private static object? WorkContext(object item) => item is ContextSource source
        ? ContextValue(source.CapturedContext()) : null;

    public static ExecutionContext? BindContext(ExecutionContext? original, object item)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return original;
        }
        var owner = Find(item) ?? ContextValue(original) as Record;
        if (owner is null && Maintenance(item)) owner = root;
        if (owner is null || !owner.Active || owner.Result)
            throw new InvalidOperationException("managed-work-context-owner");
        return ContextWithOwner(original, owner);
    }

    private static partial object? ContextValue(ExecutionContext? context);
    private static partial ExecutionContext ContextWithOwner(ExecutionContext? context, object owner);
    private static partial void BindAsyncContext(Task task);
    private static partial bool Maintenance(object item);
    private static partial bool RequiredContinuation(object item);
    private static partial bool ReadySource();
    private static partial void WaitForCompletion(Task task);
    private static partial void DispatchOnce();
}
