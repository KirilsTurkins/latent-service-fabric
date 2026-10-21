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
        internal bool Active;
        internal bool Root;
        internal bool Result;
        internal bool Observed;
        internal bool CallbackDone;
    }

    private sealed class Queued
    {
        internal object Item = null!;
        internal Record Owner = null!;
        internal (ulong Generation, ulong Id) Token;
    }

    private sealed class Required
    {
        internal Task Task = null!;
        internal Record Owner = null!;
        internal bool Observed;
        internal bool Transport;
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

    public static void Install(
        Func<int, ulong, ulong, (ulong Generation, ulong Id)> register,
        Action<ulong, ulong> release, Action beginClosing, Action<ulong, ulong> setContext)
    {
        if (installed || reserve is not null || register is null || release is null
            || beginClosing is null || setContext is null)
            throw new InvalidOperationException("managed-work-installation");
        if (ReadySource()) throw new InvalidOperationException("managed-work-untracked-startup-work");
        reserve = register; settle = release; close = beginClosing; adapterContext = setContext;
        var rootToken = register(TaskKind, 0, 0);
        try
        {
            storage = register(NativeKind, rootToken.Generation, rootToken.Id);
            try
            {
                records = new Record?[MaximumRecords];
                queued = new Queued?[MaximumQueued];
                required = new Required?[MaximumRecords];
                root = new Record { Primary = new object(), Token = rootToken, Active = true, Root = true };
                records[0] = root;
                current = new AsyncLocal<Record?>(ContextChanged);
                installed = true;
                current.Value = root;
            }
            catch
            {
                release(storage.Generation, storage.Id);
                throw;
            }
        }
        catch
        {
            release(rootToken.Generation, rootToken.Id);
            throw;
        }
    }

    private static void ContextChanged(AsyncLocalValueChangedArgs<Record?> change)
    {
        var owner = change.CurrentValue;
        if (owner is not null && owner.Active && !owner.Result)
            adapterContext!(owner.Token.Generation, owner.Token.Id);
        else
            adapterContext!(0, 0);
    }

    private static Record? Find(object item)
    {
        if (records is null) return null;
        foreach (var owner in records)
            if (owner is not null && (ReferenceEquals(owner.Primary, item)
                || ReferenceEquals(owner.Outer, item) || ReferenceEquals(owner.Inner, item))) return owner;
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
        return reserve!(kind, token.Generation, token.Id);
    }

    private static int FreeRecord()
    {
        for (int i = 1; i < MaximumRecords; i++) if (records![i] is null) return i;
        throw new InvalidOperationException("managed-work-record-limit");
    }

    private static Record Admit(object item, Task? completion, Record? parent)
    {
        int index = FreeRecord();
        var token = Reserve(TaskKind, parent);
        try
        {
            var owner = new Record { Primary = item, Completion = completion, Token = token, Active = true };
            records![index] = owner;
            return owner;
        }
        catch
        {
            settle!(token.Generation, token.Id);
            throw;
        }
    }

    public static void Schedule(Task task)
    {
        if (!installed || Find(task) is not null || task.IsCompleted) return;
        Admit(task, task, Parent());
    }

    public static void Continuation(Task task)
    {
        Schedule(task);
    }

    public static void ContinuationFailed(Task task)
    {
        if (!installed) return;
        var owner = Find(task);
        if (owner is null || owner.Root || owner.Result || task.IsCompleted || !ReferenceEquals(owner.Completion, task)) return;
        foreach (var item in queued!) if (item is not null && ReferenceEquals(item.Owner, owner)) return;
        if (!HasRequired(owner)) Release(owner);
    }

    public static void Unwrap(Task promise, Task outer)
    {
        if (!installed || promise.IsCompleted) return;
        var owner = Find(outer);
        if (owner is null) owner = Admit(promise, promise, Parent());
        else
        {
            owner.Outer = outer;
            owner.Primary = promise;
            owner.Completion = promise;
        }
    }

    public static void Inner(Task promise, Task? inner)
    {
        if (!installed || inner is null) return;
        var owner = Find(promise);
        if (owner is not null) owner.Inner = inner;
    }

    // Exact producer-bound internal content work must finish, but its error is
    // still reported by the original request future. This adds no success path.
    public static void RequiredTransport(Task task)
    {
        Remember(task, true);
    }

    // A state-machine box is an actual required continuation of its current
    // logical flow, including direct async calls and async-void callbacks.
    // The scheduled Task.Run owner is not charged a second time for its inner
    // builder task. Every retained box shares the same finite metadata lease.
    public static void CreatedAsync(Task task)
    {
        if (!installed || task.IsCompleted) return;
        Remember(task, false);
        BindAsyncContext(task);
    }

    private static void Remember(Task task, bool transport)
    {
        if (!installed) return;
        for (int i = 0; i < MaximumRecords; i++)
            if (required![i] is { } existing && ReferenceEquals(existing.Task, task))
            {
                existing.Transport |= transport;
                return;
            }
        if (task.IsCompleted) return;
        var owner = current!.Value;
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

    public static void Enqueue(object item)
    {
        if (!installed) return;
        int index = -1;
        for (int i = 0; i < MaximumQueued; i++)
        {
            if (queued![i] is not null && ReferenceEquals(queued[i]!.Item, item))
                throw new InvalidOperationException("managed-work-duplicate-enqueue");
            if (index < 0 && queued[i] is null) index = i;
        }
        if (index < 0) throw new InvalidOperationException("managed-work-queue-record-limit");
        var owner = Find(item);
        bool created = false;
        if (owner is null)
        {
            var captured = WorkContext(item) as Record;
            if (captured is not null && (!captured.Active || captured.Result))
                throw new InvalidOperationException("managed-work-captured-parent-retired");
            if (Maintenance(item)) owner = root!;
            else if (RequiredContinuation(item) && captured is not null) owner = captured;
            else
            {
                var parent = captured ?? Parent();
                if (closing && (parent is null || parent.Root))
                    throw new InvalidOperationException("managed-work-independent-admission-closed");
                owner = Admit(item, null, parent);
                created = true;
            }
        }
        try
        {
            var token = Reserve(QueuedKind, owner);
            try { queued![index] = new Queued { Item = item, Owner = owner, Token = token }; }
            catch { settle!(token.Generation, token.Id); throw; }
        }
        catch
        {
            if (created) Release(owner);
            throw;
        }
    }

    public static void EnqueueFailed(object item)
    {
        if (!installed) return;
        for (int i = 0; i < MaximumQueued; i++)
            if (queued![i] is { } pending && ReferenceEquals(pending.Item, item))
            {
                queued[i] = null;
                settle!(pending.Token.Generation, pending.Token.Id);
                if (pending.Owner.Completion is null && !pending.Owner.Root) Release(pending.Owner);
                return;
            }
    }

    public static void Dequeue(object item)
    {
        if (!installed) return;
        for (int i = 0; i < MaximumQueued; i++)
            if (queued![i] is { } pending && ReferenceEquals(pending.Item, item))
            {
                queued[i] = null;
                settle!(pending.Token.Generation, pending.Token.Id);
                return;
            }
        throw new InvalidOperationException("managed-work-unregistered-dequeue");
    }

    public static bool Popped(bool found, object item)
    {
        if (installed && found) Dequeue(item);
        return found;
    }

    public static object? Enter(object item)
    {
        if (!installed) return null;
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
        if (installed && item is Task task && task.IsCompleted) return current!.Value;
        return Enter(item);
    }

    public static void Exit(object? previous)
    {
        if (installed) current!.Value = (Record?)previous;
    }

    public static void CallbackCompleted(object item)
    {
        if (!installed) return;
        var owner = Find(item);
        if (owner is not null && owner.Completion is null && !owner.Root)
        {
            owner.CallbackDone = true;
            if (!HasRequired(owner)) Release(owner);
        }
    }

    public static void Completed(Task task)
    {
        if (!installed) return;
        var owner = Find(task);
        if (owner is null || owner.Root || owner.Result || !ReferenceEquals(owner.Completion, task)) return;
        if (HasRequired(owner)) return;
        Finish(owner);
    }

    public static void Observed(Task task)
    {
        if (!installed) return;
        foreach (var pending in required!)
            if (pending is not null && ReferenceEquals(pending.Task, task)) pending.Observed = true;
        var owner = Find(task);
        if (owner is not null && ReferenceEquals(owner.Completion, task))
        {
            owner.Observed = true;
            if (owner.Result) Release(owner);
        }
    }

    private static bool HasRequired(Record owner)
    {
        bool found = false;
        for (int i = 0; i < MaximumRecords; i++)
        {
            var pending = required![i];
            if (pending is null || !ReferenceEquals(pending.Owner, owner)) continue;
            if (pending.Task.IsCompleted) CompletedRequired(i);
            else found = true;
        }
        return found;
    }

    private static void CompletedRequired(int index)
    {
        var pending = required![index]!;
        if (pending.Task.IsFaulted && !pending.Observed && !pending.Transport)
        {
            int slot = FreeRecord();
            var token = Reserve(ResultKind, pending.Owner);
            try
            {
                records![slot] = new Record { Primary = pending.Task, Completion = pending.Task,
                    Token = token, Active = true, Result = true };
            }
            catch { settle!(token.Generation, token.Id); throw; }
        }
        required[index] = null;
    }

    private static void Finish(Record owner)
    {
        if (owner.Completion is { } task && task.IsFaulted && !owner.Observed)
        {
            var result = Reserve(ResultKind, owner);
            settle!(owner.Token.Generation, owner.Token.Id);
            owner.Token = result;
            owner.Result = true;
        }
        else Release(owner);
    }

    private static void Release(Record owner)
    {
        if (!owner.Active) throw new InvalidOperationException("managed-work-double-settle");
        settle!(owner.Token.Generation, owner.Token.Id);
        owner.Active = false;
        for (int i = 1; i < MaximumRecords; i++)
            if (ReferenceEquals(records![i], owner)) { records[i] = null; return; }
        if (!owner.Root) throw new InvalidOperationException("managed-work-missing-record");
    }

    public static void JoinAcceptedWork()
    {
        if (!installed || closing) throw new InvalidOperationException("managed-work-closing-state");
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
                if (owner is null || owner.Root || owner.Result) continue;
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
        if (installed && closing && !ReadySource())
            throw new InvalidOperationException("managed-work-unproven-quiescence");
    }

    public static void FinishedPhysicalDrain()
    {
        if (!installed || !closing) throw new InvalidOperationException("managed-work-finalization-state");
        foreach (var owner in records!) if (owner is not null && !owner.Root)
            throw new InvalidOperationException("managed-work-finalization-owners");
        foreach (var item in queued!) if (item is not null)
            throw new InvalidOperationException("managed-work-finalization-queue");
        foreach (var item in required!) if (item is not null)
            throw new InvalidOperationException("managed-work-finalization-continuations");
        settle!(storage.Generation, storage.Id);
        Release(root!);
        current!.Value = null;
        installed = false;
        records = null; queued = null; required = null; current = null; root = null;
        reserve = null; settle = null; close = null; adapterContext = null;
        storage = default; closing = false;
    }

    private static object? WorkContext(object item) => item is ContextSource source
        ? ContextValue(source.CapturedContext()) : null;

    public static ExecutionContext? BindContext(ExecutionContext? original, object item)
    {
        if (!installed) return original;
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
