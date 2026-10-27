using System;
using System.Diagnostics.CodeAnalysis;
using System.Threading;
using System.Threading.Tasks;

namespace OutsideRootDrain;

// SOURCE DRAFT ONLY. The ordinary generated bridge performs the root drain.
public static class Library
{
    private const int DelayMillis = 1000;
    private static int entries;
    private static bool rootReturning;
    private static int callbacks;
    private static int completions;
    private static readonly AsyncLocal<string?> context = new();

    private sealed class FaultIdentity
    {
        internal readonly Exception Original = new InvalidOperationException("original-unobserved-child-fault");
    }
    private static FaultIdentity? faultIdentity;
    public static Exception? OriginalFault => faultIdentity?.Original;

    [DynamicDependency(DynamicallyAccessedMemberTypes.PublicProperties, typeof(Library))]
    public static uint Run(uint mode)
    {
        if (++entries != 1 || rootReturning || callbacks != 0 || completions != 0 || faultIdentity is not null)
            throw new InvalidOperationException("root-drain-request-state-leaked");
        if (SynchronizationContext.Current is not null || context.Value is not null)
            throw new InvalidOperationException("root-drain-initial-context");
        context.Value = "original-root";
        switch (mode)
        {
            case 1: Pending(Task.Run(AcceptedTask)); break;
            case 2: AcceptTimer(); break;
            case 3: AcceptHandledFault(); break;
            case 4: AcceptHandledCancellation(); break;
            case 5: SettledIdle(); break;
            case 6: break; // Fresh activation: the entry guards are the oracle.
            case 7: Pending(Task.Run(DeadlineChild)); break;
            case 8: Pending(UnknownReadySource()); break;
            case 9:
                faultIdentity = new FaultIdentity(); // BEFORE child admission; accessor never observes Task.Exception.
                Pending(Task.Run(UnobservedFault));
                break;
            default: throw new ArgumentOutOfRangeException(nameof(mode));
        }
        if (SynchronizationContext.Current is not null || context.Value != "original-root")
            throw new InvalidOperationException("root-drain-caller-context");
        rootReturning = true;
        // A fixed flat result, NOT a mutable post-drain sentinel. The exact
        // generated async-u32 TaskReturn must be retained by the normal build.
        return 0xAC700000u | mode;
    }

    private static void Pending(Task task)
    {
        if (task.IsCompleted)
            throw new InvalidOperationException("accepted-work-was-not-pending");
    }

    private static void ChildEntry()
    {
        if (!rootReturning || SynchronizationContext.Current is not null
            || context.Value != "original-root")
            throw new InvalidOperationException("accepted-child-context-or-order");
    }

    private static async Task AcceptedTask()
    {
        await Task.Delay(DelayMillis);
        ChildEntry();
        await Task.Run(() =>
        {
            ChildEntry();
            if (Interlocked.Increment(ref completions) != 1)
                throw new InvalidOperationException("accepted-descendant-duplicate");
        });
        if (completions != 1)
            throw new InvalidOperationException("accepted-descendant-lost");
    }

    private static void AcceptTimer()
    {
        Timer? timer = null;
        timer = new Timer(_ =>
        {
            ChildEntry();
            if (Interlocked.Increment(ref callbacks) != 1)
                throw new InvalidOperationException("one-shot-callback-duplicate");
            var disposal = timer!.DisposeAsync();
            if (disposal.IsCompleted)
                throw new InvalidOperationException("live-callback-marked-retired");
            Pending(CompleteTimer(disposal.AsTask()));
        }, null, Timeout.Infinite, Timeout.Infinite);
        if (!timer.Change(DelayMillis, Timeout.Infinite))
            throw new InvalidOperationException("one-shot-change-refused");
    }

    private static async Task CompleteTimer(Task disposal)
    {
        await Task.Delay(DelayMillis);
        ChildEntry();
        await disposal;
        if (callbacks != 1 || Interlocked.Increment(ref completions) != 1)
            throw new InvalidOperationException("callback-required-continuation-lost");
    }

    private static void AcceptHandledFault()
    {
        var original = new InvalidOperationException("original-accepted-child-fault");
        var child = Task.Run(async () =>
        {
            await Task.Delay(DelayMillis);
            ChildEntry();
            throw original;
        });
        Pending(child);
        Pending(ObserveFault(child, original));
    }

    private static async Task ObserveFault(Task child, Exception original)
    {
        try
        {
            await child;
            throw new InvalidOperationException("accepted-child-fault-was-swallowed");
        }
        catch (InvalidOperationException error) when (ReferenceEquals(error, original))
        {
            ChildEntry();
            if (Interlocked.Increment(ref completions) != 1)
                throw new InvalidOperationException("accepted-child-fault-observed-twice");
        }
    }

    private static void AcceptHandledCancellation()
    {
        var source = new CancellationTokenSource();
        var original = source.Token;
        var child = Task.Delay(Timeout.Infinite, original);
        Pending(child);
        Pending(ObserveCancellation(source, original, child));
    }

    private static async Task ObserveCancellation(CancellationTokenSource source,
        CancellationToken original, Task child)
    {
        try
        {
            await Task.Delay(DelayMillis);
            ChildEntry();
            source.Cancel();
            try
            {
                await child;
                throw new InvalidOperationException("accepted-child-cancel-was-swallowed");
            }
            catch (OperationCanceledException error) when (error.CancellationToken == original)
            {
                if (Interlocked.Increment(ref completions) != 1)
                    throw new InvalidOperationException("accepted-child-cancel-observed-twice");
            }
        }
        finally { source.Dispose(); }
    }

    private static void SettledIdle()
    {
        // ONLY this control joins in application code. It leaves no pending
        // application work; ordinary maintenance must not count as unknown work.
        Task.Run(async () =>
        {
            await Task.Delay(DelayMillis);
            if (Interlocked.Increment(ref completions) != 1)
                throw new InvalidOperationException("settled-idle-duplicate");
        }).GetAwaiter().GetResult();
        if (completions != 1)
            throw new InvalidOperationException("settled-idle-work-not-settled");
    }

    private static async Task DeadlineChild()
    {
        await Task.Delay(DelayMillis);
        ChildEntry();
        Interlocked.Increment(ref callbacks);
    }

    private static async Task UnknownReadySource()
    {
        // No cancellation, timer, queue producer or externally fulfillable handle.
        // This is an explicit negative; a generic trap alone is not cause proof.
        await new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously).Task;
        throw new InvalidOperationException("unknown-source-was-invented-ready");
    }

    private static async Task UnobservedFault()
    {
        await Task.Delay(DelayMillis);
        ChildEntry();
        throw faultIdentity!.Original;
    }
}
