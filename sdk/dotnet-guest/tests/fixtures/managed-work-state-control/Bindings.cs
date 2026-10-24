using System.Threading;
using System.Threading.Tasks;

namespace Lsf.CompilerOwned;

// State controls use the actual registry core with explicit test ports. These
// ports do NOT qualify the production context lowering, dispatcher or native
// ledger. Those have separate exact metadata and signed-execution gates.
public static partial class ManagedWorkRuntime
{
    // Read-only test-port observation; this member is never copied into CoreLib.
    internal static (ulong Generation, ulong Id)? QueuedTokenForControl(object item)
    {
        foreach (var pending in queued!)
            if (pending is not null && ReferenceEquals(pending.Item, item)) return pending.Token;
        return null;
    }

    private static partial bool TimerScheduled(object item) => throw new InvalidOperationException("unexpected-control-timer");
    private static partial int TimerCallbacks(object item) => throw new InvalidOperationException("unexpected-control-timer");
    private static partial object? ContextValue(ExecutionContext? context) => null;
    private static partial ExecutionContext ContextWithOwner(ExecutionContext? context, object owner) =>
        context ?? ExecutionContext.Capture() ?? throw new InvalidOperationException("control-context");
    private static partial void BindAsyncContext(Task task) { }
    private static partial bool Maintenance(object item) => false;
    private static partial bool RequiredContinuation(object item) => false;
    private static partial bool ReadySource() => global::StateControl.Work.Count != 0;
    private static partial void WaitForCompletion(Task task)
    {
        while (!task.IsCompleted) global::StateControl.Step();
    }
    private static partial void DispatchOnce() => global::StateControl.Step();
}
