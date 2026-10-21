using System;

namespace Lsf.CompilerOwned;

public static partial class ManagedWorkRuntime
{
    private const int TimerKind = 5;

    private sealed class TimerOwner
    {
        internal object Timer = null!;
        internal Record Owner = null!;
        internal int Mutation;
        internal int Accepted;
        internal int Running;
    }

    // Allocated once beneath the existing native-owned bounded metadata table.
    // Original TimerQueueTimer instances remain owned by their original BCL.
    private static TimerOwner?[]? timers;

    private static TimerOwner? FindTimer(object item)
    {
        if (timers is not null)
            foreach (var timer in timers)
                if (timer is not null && ReferenceEquals(timer.Timer, item)) return timer;
        return null;
    }

    public static void TimerChanging(object item)
    {
        if (!installed) return;
        var existing = FindTimer(item);
        if (existing is not null)
        {
            if (existing.Mutation == int.MaxValue) throw new InvalidOperationException("managed-timer-mutation-limit");
            existing.Mutation++;
            return;
        }
        int slot = -1;
        for (int i = 0; i < MaximumRecords; i++)
            if (timers![i] is null) { slot = i; break; }
        if (slot < 0) throw new InvalidOperationException("managed-timer-record-limit");
        var token = Reserve(TimerKind, Parent());
        try
        {
            timers![slot] = new TimerOwner { Timer = item, Mutation = 1,
                Owner = new Record { Primary = item, Token = token, Active = true, Timer = true } };
        }
        catch { settle!(token.Generation, token.Id); throw; }
    }

    public static void TimerChanged(object item)
    {
        if (!installed) return;
        var timer = FindTimer(item) ?? throw new InvalidOperationException("managed-timer-change-owner");
        if (timer.Mutation == 0) throw new InvalidOperationException("managed-timer-change-state");
        timer.Mutation--;
        TryRetireTimer(timer);
    }

    public static void TimerDeleted(object item)
    {
        if (installed && FindTimer(item) is { } timer) TryRetireTimer(timer);
    }

    public static void TimerAccepted(object item)
    {
        if (!installed) return;
        var timer = FindTimer(item) ?? throw new InvalidOperationException("managed-timer-accepted-owner");
        if (timer.Accepted == int.MaxValue) throw new InvalidOperationException("managed-timer-callback-limit");
        // The exact producer calls this before its one-shot DeleteTimer and
        // before either the inline Fire or original ThreadPool queue insertion.
        timer.Accepted++;
    }

    public static object? TimerEnter(object item)
    {
        if (!installed) return null;
        var timer = FindTimer(item) ?? throw new InvalidOperationException("managed-timer-dispatch-owner");
        if (timer.Accepted == 0 || timer.Running == int.MaxValue)
            throw new InvalidOperationException("managed-timer-dispatch-state");
        timer.Accepted--; timer.Running++;
        var previous = current!.Value;
        current.Value = timer.Owner;
        return previous;
    }

    public static void TimerLeave(object item, object? previous)
    {
        if (!installed) return;
        var timer = FindTimer(item) ?? throw new InvalidOperationException("managed-timer-return-owner");
        if (timer.Running == 0) throw new InvalidOperationException("managed-timer-return-state");
        timer.Running--;
        // The original callback-running field remains nonzero if an original
        // callback threw before its decrement. That failure never becomes an
        // apparently successful timer return or a refunded owner here.
        TryRetireTimer(timer);
        current!.Value = (Record?)previous;
    }

    private static void TryRetireTimer(TimerOwner timer)
    {
        if (timer.Mutation != 0 || timer.Accepted != 0 || timer.Running != 0
            || TimerScheduled(timer.Timer) || TimerCallbacks(timer.Timer) != 0
            || HasRequired(timer.Owner)) return;
        foreach (var work in queued!) if (work is not null && ReferenceEquals(work.Owner, timer.Owner)) return;
        settle!(timer.Owner.Token.Generation, timer.Owner.Token.Id);
        timer.Owner.Active = false;
        for (int i = 0; i < MaximumRecords; i++)
            if (ReferenceEquals(timers![i], timer)) { timers[i] = null; return; }
        throw new InvalidOperationException("managed-timer-missing-record");
    }

    private static bool PendingTimers()
    {
        bool pending = false;
        foreach (var timer in timers!)
            if (timer is not null)
            {
                TryRetireTimer(timer);
                if (timer.Owner.Active) pending = true;
            }
        return pending;
    }

    private static partial bool TimerScheduled(object item);
    private static partial int TimerCallbacks(object item);
}
