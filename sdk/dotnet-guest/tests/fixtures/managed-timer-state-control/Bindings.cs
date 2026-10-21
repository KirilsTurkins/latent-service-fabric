using System.Threading;
using System.Threading.Tasks;
namespace Lsf.CompilerOwned;
// The registry is production source. These are explicit test ports, not a
// replacement or qualification of the original CoreLib producer/native ledger.
public static partial class ManagedWorkRuntime
{
    private static partial bool TimerScheduled(object item) => ((TimerControl.State)item).Scheduled;
    private static partial int TimerCallbacks(object item) => ((TimerControl.State)item).Callbacks;
    private static partial object? ContextValue(ExecutionContext? context) => null;
    private static partial ExecutionContext ContextWithOwner(ExecutionContext? context, object owner) =>
        context ?? ExecutionContext.Capture() ?? throw new InvalidOperationException("timer-control-context");
    private static partial void BindAsyncContext(Task task) { }
    private static partial bool Maintenance(object item) => false;
    private static partial bool RequiredContinuation(object item) => false;
    private static partial bool ReadySource() => global::TimerControl.Work.Count != 0;
    private static partial void WaitForCompletion(Task task)
    { while (!task.IsCompleted) global::TimerControl.Step(); }
    private static partial void DispatchOnce() => global::TimerControl.Step();
}
