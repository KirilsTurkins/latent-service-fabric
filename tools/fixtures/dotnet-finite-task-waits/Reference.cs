using System.Runtime.InteropServices;
using System.Text.Json;

public static class WaitCandidate {
    public static bool Wait(Task task, int milliseconds, CancellationToken token) => throw new PlatformNotSupportedException("uninjected-reference-control");
    public static bool Pump(Task task) { task.GetAwaiter().GetResult(); return true; }
}

public static class Program {
    private static void Require(bool value, string code) { if (!value) throw new Exception(code); }
    private static bool Candidate(Task task, int milliseconds, CancellationToken token) {
        if (milliseconds < -1) throw new ArgumentOutOfRangeException("millisecondsTimeout");
        if (task.Status == TaskStatus.RanToCompletion) return true;
        if (!WaitCandidate.Wait(task, milliseconds, token)) return false;
        if (task.IsCanceled) token.ThrowIfCancellationRequested();
        return task.Wait(0, CancellationToken.None);
    }
    private static string Case(string name, Func<Task, int, CancellationToken, bool> wait) {
        using var cancellation = new CancellationTokenSource();
        var pending = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        switch (name) {
        case "completed-success-precancel":
            cancellation.Cancel(); Require(wait(Task.CompletedTask, 100, cancellation.Token), name); return "true";
        case "zero-incomplete-precancel":
            cancellation.Cancel(); Require(!wait(pending.Task, 0, cancellation.Token) && !pending.Task.IsCompleted, name); return "false-incomplete";
        case "invalid-timeout-before-complete":
            try { wait(Task.CompletedTask, -2, cancellation.Token); }
            catch (ArgumentOutOfRangeException error) { Require(error.ParamName == "millisecondsTimeout", name); return "ArgumentOutOfRangeException:millisecondsTimeout"; }
            throw new Exception(name);
        case "finite-success":
        case "finite-cancellable-success": {
            using var timer = new Timer(_ => pending.TrySetResult(true), null, Timeout.Infinite, Timeout.Infinite);
            Require(!pending.Task.IsCompleted, name); timer.Change(10, Timeout.Infinite);
            var token = name == "finite-success" ? CancellationToken.None : cancellation.Token;
            Require(wait(pending.Task, 1000, token) && pending.Task.IsCompletedSuccessfully && !cancellation.IsCancellationRequested, name);
            timer.DisposeAsync().AsTask().GetAwaiter().GetResult(); return "true-original-task";
        }
        case "timeout-false-then-fresh":
            Require(!wait(pending.Task, 5, cancellation.Token) && !pending.Task.IsCompleted && !cancellation.IsCancellationRequested, name);
            pending.SetResult(true); Require(wait(pending.Task, 0, cancellation.Token), name); return "false-then-true-original-token-live";
        case "infinite-cancel":
        case "finite-cancel":
            cancellation.CancelAfter(5);
            try { wait(pending.Task, name == "infinite-cancel" ? Timeout.Infinite : 1000, cancellation.Token); }
            catch (OperationCanceledException error) {
                Require(error.CancellationToken == cancellation.Token && !pending.Task.IsCompleted, name);
                pending.SetResult(true); Require(wait(pending.Task, 0, cancellation.Token), name); return "OperationCanceledException:original-token;task-preserved";
            }
            throw new Exception(name);
        case "incomplete-precancel":
            cancellation.Cancel();
            try { wait(pending.Task, 100, cancellation.Token); }
            catch (OperationCanceledException error) { Require(error.CancellationToken == cancellation.Token && !pending.Task.IsCompleted, name); return "OperationCanceledException:original-token"; }
            throw new Exception(name);
        case "completed-fault-over-precancel": {
            var original = new InvalidOperationException("controlled-fault"); pending.SetException(original); cancellation.Cancel();
            try { wait(pending.Task, 100, cancellation.Token); }
            catch (AggregateException error) { Require(error.InnerExceptions.Count == 1 && ReferenceEquals(error.InnerException, original), name); return "AggregateException:original-fault"; }
            throw new Exception(name);
        }
        case "pending-fault": {
            var original = new InvalidOperationException("controlled-fault");
            using var timer = new Timer(_ => pending.TrySetException(original), null, Timeout.Infinite, Timeout.Infinite);
            Require(!pending.Task.IsCompleted, name); timer.Change(5, Timeout.Infinite);
            try { wait(pending.Task, 1000, cancellation.Token); }
            catch (AggregateException error) { Require(error.InnerExceptions.Count == 1 && ReferenceEquals(error.InnerException, original), name); return "AggregateException:original-fault"; }
            throw new Exception(name);
        }
        case "own-cancel-aggregate": {
            using var taskSource = new CancellationTokenSource(); taskSource.Cancel(); pending.SetCanceled(taskSource.Token);
            try { wait(pending.Task, 100, cancellation.Token); }
            catch (AggregateException error) { Require(error.InnerExceptions.Count == 1 && error.InnerException is TaskCanceledException cancelled && cancelled.CancellationToken == taskSource.Token, name); return "AggregateException:original-task-token"; }
            throw new Exception(name);
        }
        case "own-cancel-wait-token-precedence":
            cancellation.Cancel(); pending.SetCanceled();
            try { wait(pending.Task, 100, cancellation.Token); }
            catch (OperationCanceledException error) { Require(error.CancellationToken == cancellation.Token, name); return "OperationCanceledException:original-wait-token"; }
            throw new Exception(name);
        default: throw new Exception("unknown-controlled-case");
        }
    }
    public static void Main() {
        string[] names = ["completed-success-precancel", "zero-incomplete-precancel", "invalid-timeout-before-complete", "finite-success", "finite-cancellable-success", "timeout-false-then-fresh", "infinite-cancel", "finite-cancel", "incomplete-precancel", "completed-fault-over-precancel", "pending-fault", "own-cancel-aggregate", "own-cancel-wait-token-precedence"];
        var rows = new List<object>();
        foreach (var name in names) {
            var original = Case(name, (task, time, token) => task.Wait(time, token));
            var derived = Case(name, Candidate);
            Require(original == derived, "reference-result-changed:" + name);
            rows.Add(new { name, original, derived, passed = true });
        }
        Console.WriteLine(JsonSerializer.Serialize(new { framework = RuntimeInformation.FrameworkDescription, cases = rows, wasmExecution = false, originalQueuePumpExecuted = false, helperIlExecuted = true }));
    }
}
