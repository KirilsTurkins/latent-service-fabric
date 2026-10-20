using System;
using System.Threading;
using System.Threading.Tasks;
namespace OutsideFiniteWaits;
public static class Library {
    private static int calls;
    private static void Require(bool value,string code) { if (!value) throw new InvalidOperationException(code); }
    private static bool Wait(Task task,int milliseconds,CancellationToken token) => task.Wait(milliseconds,token);
    public static string Run(string mode) {
        if (++calls!=1 || SynchronizationContext.Current!=null) throw new InvalidOperationException("request state changed");
        return "finite-task-wait:"+mode+"|"+Case(mode);
    }
    private static string Case(string name) {
        using var cancellation = new CancellationTokenSource();
        var pending = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        switch (name) {
        case "infinite-join-regression": {
            var task = Task.Run(() => 73);
            Require(Wait(task, Timeout.Infinite, CancellationToken.None) && task.Result == 73, name);
            return "true-original-infinite-join";
        }
        case "pending-root":
            Require(!pending.Task.IsCompleted, name);
            Wait(pending.Task, 60000, CancellationToken.None);
            throw new Exception("root wait unexpectedly returned");
        case "completed-success-precancel":
            cancellation.Cancel(); Require(Wait(Task.CompletedTask, 100, cancellation.Token), name); return "true";
        case "zero-incomplete-precancel":
            cancellation.Cancel(); Require(!Wait(pending.Task, 0, cancellation.Token) && !pending.Task.IsCompleted, name); return "false-incomplete";
        case "invalid-timeout-before-complete":
            try { Wait(Task.CompletedTask, -2, cancellation.Token); }
            catch (ArgumentOutOfRangeException error) { Require(error.ParamName == "millisecondsTimeout", name); return "ArgumentOutOfRangeException:millisecondsTimeout"; }
            throw new Exception(name);
        case "finite-success":
        case "finite-cancellable-success": {
            using var timer = new Timer(_ => pending.TrySetResult(true), null, Timeout.Infinite, Timeout.Infinite);
            Require(!pending.Task.IsCompleted, name); timer.Change(10, Timeout.Infinite);
            var token = name == "finite-success" ? CancellationToken.None : cancellation.Token;
            Require(Wait(pending.Task, 1000, token) && pending.Task.IsCompletedSuccessfully && !cancellation.IsCancellationRequested, name);
            timer.DisposeAsync().AsTask().GetAwaiter().GetResult(); return "true-original-task";
        }
        case "timeout-false-then-fresh":
            Require(!Wait(pending.Task, 5, cancellation.Token) && !pending.Task.IsCompleted && !cancellation.IsCancellationRequested, name);
            pending.SetResult(true); Require(Wait(pending.Task, 0, cancellation.Token), name); return "false-then-true-original-token-live";
        case "infinite-cancel":
        case "finite-cancel":
            cancellation.CancelAfter(5);
            try { Wait(pending.Task, name == "infinite-cancel" ? Timeout.Infinite : 1000, cancellation.Token); }
            catch (OperationCanceledException error) {
                Require(error.CancellationToken == cancellation.Token && !pending.Task.IsCompleted, name);
                pending.SetResult(true); Require(Wait(pending.Task, 0, cancellation.Token), name); return "OperationCanceledException:original-token;task-preserved";
            }
            throw new Exception(name);
        case "incomplete-precancel":
            cancellation.Cancel();
            try { Wait(pending.Task, 100, cancellation.Token); }
            catch (OperationCanceledException error) { Require(error.CancellationToken == cancellation.Token && !pending.Task.IsCompleted, name); return "OperationCanceledException:original-token"; }
            throw new Exception(name);
        case "completed-fault-over-precancel": {
            var original = new InvalidOperationException("controlled-fault"); pending.SetException(original); cancellation.Cancel();
            try { Wait(pending.Task, 100, cancellation.Token); }
            catch (AggregateException error) { Require(error.InnerExceptions.Count == 1 && ReferenceEquals(error.InnerException, original), name); return "AggregateException:original-fault"; }
            throw new Exception(name);
        }
        case "pending-fault": {
            var original = new InvalidOperationException("controlled-fault");
            using var timer = new Timer(_ => pending.TrySetException(original), null, Timeout.Infinite, Timeout.Infinite);
            Require(!pending.Task.IsCompleted, name); timer.Change(5, Timeout.Infinite);
            try { Wait(pending.Task, 1000, cancellation.Token); }
            catch (AggregateException error) { Require(error.InnerExceptions.Count == 1 && ReferenceEquals(error.InnerException, original), name); return "AggregateException:original-fault"; }
            throw new Exception(name);
        }
        case "own-cancel-aggregate": {
            using var taskSource = new CancellationTokenSource(); taskSource.Cancel(); pending.SetCanceled(taskSource.Token);
            try { Wait(pending.Task, 100, cancellation.Token); }
            catch (AggregateException error) { Require(error.InnerExceptions.Count == 1 && error.InnerException is TaskCanceledException cancelled && cancelled.CancellationToken == taskSource.Token, name); return "AggregateException:original-task-token"; }
            throw new Exception(name);
        }
        case "own-cancel-wait-token-precedence":
            cancellation.Cancel(); pending.SetCanceled();
            try { Wait(pending.Task, 100, cancellation.Token); }
            catch (OperationCanceledException error) { Require(error.CancellationToken == cancellation.Token, name); return "OperationCanceledException:original-wait-token"; }
            throw new Exception(name);
        default: throw new Exception("unknown-controlled-case");
        }
    }
}
