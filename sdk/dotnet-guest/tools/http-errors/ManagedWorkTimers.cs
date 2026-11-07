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
    // Erased by the compiler unless the source-control fixture supplies it.
    static partial void TimerAllocationControl();

    private static TimerOwner? FindTimer(object item)
    {
        if (timers is not null)
            foreach (var timer in timers)
                if (timer is not null && ReferenceEquals(timer.Timer, item)) return timer;
        return null;
    }

    public static void TimerChanging(object item)
    {
        if (!installed)
        {
            if (reserve is not null) throw new InvalidOperationException("managed-work-installation-in-progress");
            return;
        }
        var existing = FindTimer(item);
        if (existing is not null)
        {
            if (existing.Mutation < 0) throw new InvalidOperationException("managed-timer-settlement-uncertain");
            if (existing.Mutation == int.MaxValue) throw new InvalidOperationException("managed-timer-mutation-limit");
            existing.Mutation++;
            return;
        }
        var activation = root;
        if (activation is null || !activation.Active)
            throw new InvalidOperationException("managed-work-finalization-uncertain");
        if (admissions == int.MaxValue) throw new InvalidOperationException("managed-work-admission-in-progress");
        admissions++;
        try
        {
            var parent = Parent();
            TimerAllocationControl();
            var owner = new Record { Primary = item, Timer = true };
            TimerAllocationControl();
            // -2 is a provisional or uncertain admission; -1 is a settlement
            // attempt. Neither can be used or retired as an ordinary timer.
            var timer = new TimerOwner { Timer = item, Owner = owner, Mutation = -2 };
            if (!installed || !ReferenceEquals(root, activation) || !activation.Active)
                throw new InvalidOperationException("managed-work-activation-changed");
            if (!ReferenceEquals(current!.Value, parent))
                throw new InvalidOperationException("managed-timer-parent-changed");
            if (closing && (parent is null || !parent.Active || parent.Root || parent.Result))
                throw new InvalidOperationException("managed-work-independent-admission-closed");
            if (parent is not null && (!parent.Active || parent.Result))
                throw new InvalidOperationException("managed-work-parent-retired");
            // Allocation may have admitted the same item or occupied a slot.
            existing = FindTimer(item);
            if (existing is not null)
            {
                if (existing.Mutation < 0) throw new InvalidOperationException("managed-timer-settlement-uncertain");
                if (existing.Mutation == int.MaxValue) throw new InvalidOperationException("managed-timer-mutation-limit");
                existing.Mutation++;
                return;
            }
            int slot = -1;
            for (int i = 0; i < MaximumRecords; i++)
                if (timers![i] is null) { slot = i; break; }
            if (slot < 0) throw new InvalidOperationException("managed-timer-record-limit");
            timers![slot] = timer;
            var parentToken = parent?.Token ?? default;
            var token = reserve!(TimerKind, parentToken.Generation, parentToken.Id);
            owner.Token = token;
            if (token == default)
            {
                timers[slot] = null; // The selected bridge returned a definite WIT refusal.
                throw new InvalidOperationException("managed-work-admission-refused");
            }
            if (token.Generation == 0 || token.Id == 0)
                throw new InvalidOperationException("managed-work-reservation-token");
            timer.Mutation = 1;
            owner.Active = true;
        }
        finally { admissions--; }
    }

    public static void TimerChanged(object item)
    {
        if (!installed) { if (reserve is not null) admissions = -1; return; }
        var timer = FindTimer(item) ?? throw new InvalidOperationException("managed-timer-change-owner");
        if (timer.Mutation < 0) throw new InvalidOperationException("managed-timer-settlement-uncertain");
        if (timer.Mutation == 0) throw new InvalidOperationException("managed-timer-change-state");
        timer.Mutation--;
        TryRetireTimer(timer);
    }

    public static void TimerDeleted(object item)
    {
        if (!installed && reserve is not null)
        { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
        if (installed && FindTimer(item) is { } timer) TryRetireTimer(timer);
    }

    public static void TimerAccepted(object item)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return;
        }
        var timer = FindTimer(item) ?? throw new InvalidOperationException("managed-timer-accepted-owner");
        if (timer.Mutation < 0) throw new InvalidOperationException("managed-timer-settlement-uncertain");
        if (timer.Accepted == int.MaxValue) throw new InvalidOperationException("managed-timer-callback-limit");
        // The exact producer calls this before its one-shot DeleteTimer and
        // before either the inline Fire or original ThreadPool queue insertion.
        timer.Accepted++;
    }

    public static object? TimerEnter(object item)
    {
        if (!installed)
        {
            if (reserve is not null) { admissions = -1; throw new InvalidOperationException("managed-work-untracked-startup-work"); }
            return null;
        }
        var timer = FindTimer(item) ?? throw new InvalidOperationException("managed-timer-dispatch-owner");
        if (timer.Mutation < 0) throw new InvalidOperationException("managed-timer-settlement-uncertain");
        if (timer.Accepted == 0 || timer.Running == int.MaxValue)
            throw new InvalidOperationException("managed-timer-dispatch-state");
        timer.Accepted--; timer.Running++;
        var previous = current!.Value;
        current.Value = timer.Owner;
        return previous;
    }

    public static void TimerLeave(object item, object? previous)
    {
        if (!installed) { if (reserve is not null) admissions = -1; return; }
        try
        {
            var timer = FindTimer(item) ?? throw new InvalidOperationException("managed-timer-return-owner");
            if (timer.Mutation < 0) throw new InvalidOperationException("managed-timer-settlement-uncertain");
            if (timer.Running == 0) throw new InvalidOperationException("managed-timer-return-state");
            timer.Running--;
            // The original callback-running field remains nonzero if an original
            // callback threw before its decrement. That failure never becomes an
            // apparently successful timer return or a refunded owner here.
            TryRetireTimer(timer);
        }
        finally { current!.Value = (Record?)previous; }
    }

    private static void TryRetireTimer(TimerOwner timer)
    {
        if (timer.Mutation < 0) throw new InvalidOperationException("managed-timer-settlement-uncertain");
        if (timer.Mutation != 0 || timer.Accepted != 0 || timer.Running != 0
            || TimerScheduled(timer.Timer) || TimerCallbacks(timer.Timer) != 0
            || HasRequired(timer.Owner)) return;
        foreach (var work in queued!) if (work is not null && ReferenceEquals(work.Owner, timer.Owner)) return;
        // Mutation counts are nonnegative during normal operation. Reserve
        // -1 for an attempted settlement: a trap can occur after the host
        // settled, so retain the owner but never submit its token again.
        timer.Mutation = -1;
        // Captured execution contexts must no longer admit descendants using
        // this token; the timer record still retains its physical custody.
        timer.Owner.Active = false;
        settle!(timer.Owner.Token.Generation, timer.Owner.Token.Id);
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
