using System.Reflection;

// CLR reference and source projection only; this is not a WASI component.
internal static class Program
{
    private static readonly ExecutionContext Default = (ExecutionContext)typeof(ExecutionContext)
        .GetField("Default", BindingFlags.Static | BindingFlags.NonPublic)!.GetValue(null)!;

    private static void Require(bool condition, string reason)
    {
        if (!condition) throw new InvalidOperationException(reason);
    }

    private static bool Project(Task task, int milliseconds, CancellationToken cancellation, bool snapshot)
    {
        if (task.IsCompleted) return true;
        if (milliseconds == 0) return false;
        cancellation.ThrowIfCancellationRequested();
        using var source = CancellationTokenSource.CreateLinkedTokenSource(cancellation);
        try
        {
            Task wake = Task.WhenAny(task, Task.Delay(milliseconds, source.Token));
            bool result = false;
            ExecutionContext.Run(Default, _ => {
                wake.GetAwaiter().GetResult();
                if (snapshot)
                {
                    result = task.IsCompleted;
                    if (!result) cancellation.ThrowIfCancellationRequested();
                }
            }, null);
            if (!snapshot)
            {
                result = task.IsCompleted;
                if (!result) cancellation.ThrowIfCancellationRequested();
            }
            return result;
        }
        finally { source.Cancel(); }
    }

    private static (string result, bool completed, bool cancelled, int restored) RestoreCase(string mode, bool cancelOnRestore)
    {
        var task = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var cancellation = new CancellationTokenSource();
        int restored = 0;
        var local = new AsyncLocal<string?>(change => {
            if (change.ThreadContextChanged && change.CurrentValue == "caller")
            {
                restored++;
                if (cancelOnRestore) cancellation.Cancel();
                else task.TrySetResult(42);
            }
        });
        local.Value = "caller";
        string outcome;
        try
        {
            bool value = mode == "reference" ? task.Task.Wait(30, cancellation.Token)
                : Project(task.Task, 30, cancellation.Token, mode == "snapshot");
            outcome = value ? "true" : "false";
        }
        catch (OperationCanceledException error)
        {
            Require(error.CancellationToken == cancellation.Token, "original-cancellation-token");
            outcome = "cancel";
        }
        bool complete = task.Task.IsCompleted, cancelled = cancellation.IsCancellationRequested;
        local.Value = null;
        return (outcome, complete, cancelled, restored);
    }

    private static void RestoreControls()
    {
        var taskReference = RestoreCase("reference", false);
        var taskOld = RestoreCase("old", false);
        var taskFixed = RestoreCase("snapshot", false);
        Require(taskReference == ("false", false, false, 0), "reference-task-timeout");
        Require(taskOld == ("true", true, false, 1), "old-task-false-positive");
        Require(taskFixed == ("false", true, false, 1), "snapshot-task-timeout");

        var cancelReference = RestoreCase("reference", true);
        var cancelOld = RestoreCase("old", true);
        var cancelFixed = RestoreCase("snapshot", true);
        Require(cancelReference == ("false", false, false, 0), "reference-cancel-timeout");
        Require(cancelOld == ("cancel", false, true, 1), "old-late-cancellation");
        Require(cancelFixed == ("false", false, true, 1), "snapshot-late-cancellation");
    }

    private static void PrecedenceControls()
    {
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        var done = Task.FromResult(42);
        Require(done.Wait(0, cancellation.Token) && Project(done, 0, cancellation.Token, true), "completed-before-token");
        var pending = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        Require(!pending.Task.Wait(0, cancellation.Token) && !Project(pending.Task, 0, cancellation.Token, true), "zero-before-token");
        foreach (bool reference in new[] { true, false })
        {
            try
            {
                if (reference) pending.Task.Wait(10, cancellation.Token);
                else Project(pending.Task, 10, cancellation.Token, true);
                throw new InvalidOperationException("cancelled-wait-returned");
            }
            catch (OperationCanceledException error) { Require(error.CancellationToken == cancellation.Token, "token-identity"); }
        }
    }

    private static void OutcomeControls()
    {
        foreach (string outcome in new[] { "success", "fault", "cancel" })
        foreach (bool reference in new[] { true, false })
        {
            var source = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
            ThreadPool.QueueUserWorkItem(_ => {
                Thread.Sleep(10);
                if (outcome == "success") source.TrySetResult(42);
                else if (outcome == "fault") source.TrySetException(new ArgumentException("expected"));
                else source.TrySetCanceled();
            });
            try
            {
                bool result = reference ? source.Task.Wait(1000) : Project(source.Task, 1000, CancellationToken.None, true);
                if (!reference && result) source.Task.Wait(0); // Original public Wait remainder.
                Require(result && outcome == "success", "successful-result");
            }
            catch (AggregateException error)
            {
                Require(outcome == "fault" && error.InnerException is ArgumentException
                    || outcome == "cancel" && error.InnerException is TaskCanceledException, "original-aggregate-exception");
            }
        }
    }

    private static void Main()
    {
        RestoreControls();
        PrecedenceControls();
        OutcomeControls();
        Console.WriteLine("FINITE_WAIT_CLR_REFERENCE PASS restore-task;restore-token;precedence;success;fault;cancel");
    }
}
