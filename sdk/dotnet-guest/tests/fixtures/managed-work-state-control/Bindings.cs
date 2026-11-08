using System.Threading;
using System.Threading.Tasks;

namespace Lsf.CompilerOwned;

// State controls use the actual registry core with explicit test ports. These
// ports do NOT qualify the production context lowering, dispatcher or native
// ledger. Those have separate exact metadata and signed-execution gates.
public static partial class ManagedWorkRuntime
{
    static partial void StartupAllocationControl()
    {
        if (global::StateControl.StartupAllocationCallback is { } callback)
        { global::StateControl.StartupAllocationCallback = null; callback(); }
    }
    static partial void StartupRootPublishedControl()
    {
        if (global::StateControl.StartupRootPublishedCallback is { } callback)
        { global::StateControl.StartupRootPublishedCallback = null; callback(); }
    }
    static partial void RequiredResultPublishedControl()
    {
        if (global::StateControl.RequiredPublishedCallback is { } callback)
        { global::StateControl.RequiredPublishedCallback = null; callback(); }
    }
    static partial void RequiredResultReservedControl()
    {
        if (global::StateControl.RequiredReservedCallback is { } callback)
        { global::StateControl.RequiredReservedCallback = null; callback(); }
    }
    static partial void QueueAllocationControl()
    {
        if (global::StateControl.QueueAllocationCallback is { } callback)
        { global::StateControl.QueueAllocationCallback = null; callback(); }
        if (global::StateControl.FailQueueAllocation) throw global::StateControl.QueueAllocationFailure;
    }
    static partial void RecordAllocationControl()
    {
        if (global::StateControl.RecordAllocationCallback is { } callback)
        { global::StateControl.RecordAllocationCallback = null; callback(); }
    }

    // Read-only test-port observation; this member is never copied into CoreLib.
    internal static (ulong Generation, ulong Id)? QueuedTokenForControl(object item)
    {
        foreach (var pending in queued!)
            if (pending is not null && ReferenceEquals(pending.Item, item)) return pending.Token;
        return null;
    }

    internal static (ulong Generation, ulong Id)? QueuedOwnerForControl(object item)
    {
        foreach (var pending in queued!)
            if (pending is not null && ReferenceEquals(pending.Item, item)) return pending.Owner.Token;
        return null;
    }

    internal static (ulong Generation, ulong Id)? PendingResultForControl(object item) =>
        Find(item)?.PendingResult;
    internal static ((ulong Generation, ulong Id)? Root, bool RootActive,
        (ulong Generation, ulong Id) Native, bool Installed) StartupForControl() =>
        (root?.Token, root?.Active ?? false, storage, installed);

    private static partial bool TimerScheduled(object item) => throw new InvalidOperationException("unexpected-control-timer");
    private static partial int TimerCallbacks(object item) => throw new InvalidOperationException("unexpected-control-timer");
    private static partial object? ContextValue(ExecutionContext? context) => null;
    private static partial ExecutionContext ContextWithOwner(ExecutionContext? context, object owner) =>
        context ?? ExecutionContext.Capture() ?? throw new InvalidOperationException("control-context");
    private static partial void BindAsyncContext(Task task) { }
    private static partial bool Maintenance(object item) => false;
    private static partial bool RequiredContinuation(object item) => false;
    private static partial bool ReadySource() => global::StateControl.ReadyForControl();
    private static partial void WaitForCompletion(Task task)
    {
        while (!task.IsCompleted) global::StateControl.Step();
    }
    private static partial void DispatchOnce() => global::StateControl.Step();
}
