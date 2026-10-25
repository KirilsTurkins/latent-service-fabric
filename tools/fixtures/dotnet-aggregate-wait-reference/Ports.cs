using System.Threading;

// Explicit HOST-REFERENCE ports. These are never copied into a guest/CoreLib.
// Real CLR Tasks, MRES, tokens and ExecutionContext remain in use; this queue
// does not qualify the WASI dispatcher, readiness provider or native ledger.
internal static class Ports
{
    public static Task? s_mainTask;
    public static int s_lsfTaskWaitDepth;
    public static ManualResetEventSlim? s_lsfAggregateTarget;
    public static CancellationToken s_lsfAggregateToken;
    public static long s_lsfAggregateStart;
    public static int s_lsfAggregateTimeout;
    public static bool s_lsfAggregateCompleted;
    internal static readonly Queue<Action> Work = new();
    internal static Action<object?> AggregateBody = null!;
    internal static Action<object?> SingleBody = null!;
    internal static Func<bool> Ready = null!;
    internal static Action? BeforeDispatch;
    internal static Action? AfterDispatch;
    internal static long Now;
    internal static int StartReads;
    internal static int RemainingReads;
    internal static int Dispatches;
    internal static int WakeCalls;
    internal static int LastWakeDuration;
    internal static int CopiedValidationCalls;
    internal static bool Platform = true;
    internal static Exception? DelayFailure;
    internal static ManualResetEventSlim? ObservedTarget;

    public static bool IsWasi() => Platform;
    public static bool CopiedDisposed(ManualResetEventSlim value)
    {
        var getter = typeof(ManualResetEventSlim).GetMethod("get_IsDisposed",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
        ActualCil.Need(getter is not null && !getter.IsStatic && getter.ReturnType == typeof(bool)
            && getter.GetParameters().Length == 0, "host-disposal-getter-shape");
        CopiedValidationCalls++;
        return getter!.CreateDelegate<Func<ManualResetEventSlim, bool>>()(value);
    }
    public static long StartClock() { StartReads++; return Now; }
    public static long RemainingClock() { RemainingReads++; return Now; }
    public static bool Dispatch()
    {
        BeforeDispatch?.Invoke();
        ActualCil.Need(Work.Count != 0, "host-dispatch-no-ready-work");
        Dispatches++; ObservedTarget ??= s_lsfAggregateTarget;
        Work.Dequeue()(); AfterDispatch?.Invoke(); return true;
    }
    public static void EnsureReady() { }
    public static Task Delay(int duration, CancellationToken token)
    {
        WakeCalls++; LastWakeDuration = duration;
        if (DelayFailure is { } error) throw error;
        return Task.Delay(duration, token);
    }
    public static void AggregateBridge(object? state) => AggregateBody(state);
    public static void SingleBridge(object? state) => SingleBody(state);
}

// Closed cleanup-fault port around a REAL CLR linked CTS, not a fake token or
// completion Task. Source instance-call shape stays unchanged in copied IL.
internal sealed class OwnedSource : IDisposable
{
    private readonly CancellationTokenSource source;
    internal static int Births, Cancels, Disposals;
    internal static Exception? CancelFailure, DisposeFailure;
    private OwnedSource(CancellationTokenSource value) { source = value; Births++; }
    public static OwnedSource CreateLinkedTokenSource(CancellationToken token) =>
        new(CancellationTokenSource.CreateLinkedTokenSource(token));
    public CancellationToken Token => source.Token;
    public void Cancel()
    {
        Cancels++; source.Cancel();
        if (CancelFailure is { } error) throw error;
    }
    public void Dispose()
    {
        Disposals++; source.Dispose();
        if (DisposeFailure is { } error) throw error;
    }
}
