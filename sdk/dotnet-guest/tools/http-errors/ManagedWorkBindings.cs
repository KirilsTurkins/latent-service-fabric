using System;
using System.Threading;
using System.Threading.Tasks;

namespace Lsf.CompilerOwned;

// Production tool inputs. ManagedWorkContext/Hooks replace exactly these
// ten bodies with authenticated CoreLib accessors before issuing a receipt.
// State-machine controls supply separate ports while compiling the same core.
public static partial class ManagedWorkRuntime
{
    private static partial bool TimerScheduled(object item) => throw new PlatformNotSupportedException("unbound original TimerQueueTimer state");
    private static partial int TimerCallbacks(object item) => throw new PlatformNotSupportedException("unbound original TimerQueueTimer callbacks");
    private static partial object? ContextValue(ExecutionContext? context) => throw new PlatformNotSupportedException("unbound-managed-work-context-read");
    private static partial ExecutionContext ContextWithOwner(ExecutionContext? context, object owner) => throw new PlatformNotSupportedException("unbound-managed-work-context-write");
    private static partial void BindAsyncContext(Task task) => throw new PlatformNotSupportedException("unbound-managed-work-async-context");
    private static partial bool Maintenance(object item) => throw new PlatformNotSupportedException("unbound-managed-work-producer");
    private static partial bool RequiredContinuation(object item) => throw new PlatformNotSupportedException("unbound-managed-work-continuation");
    private static partial bool ReadySource() => throw new PlatformNotSupportedException("unbound-managed-work-readiness");
    private static partial void WaitForCompletion(Task task) => throw new PlatformNotSupportedException("unbound-managed-work-join");
    private static partial void DispatchOnce() => throw new PlatformNotSupportedException("unbound-managed-work-dispatch");
}
