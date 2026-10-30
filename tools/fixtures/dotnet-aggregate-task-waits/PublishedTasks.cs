using System;
using System.Threading;
using System.Threading.Tasks;
using Polly;

public static class PublishedTasks {
    public static string Stage { get; private set; } = "entry";
    private static int calls;
    private static readonly AsyncLocal<string?> context = new();
    private static TaskCompletionSource<int> Gate() => new(TaskCreationOptions.RunContinuationsAsynchronously);
    private static Timer After(Action action, int milliseconds) => new(_ => action(), null, milliseconds, Timeout.Infinite);
    private static void Check(bool value) { if (!value) throw new InvalidOperationException("aggregate oracle failed"); }
    private static void Incomplete(Task a, Task b) { Check(!a.IsCompleted && !b.IsCompleted); }

    public static string Run(string mode) {
        Stage = mode;
        Check(++calls == 1 && SynchronizationContext.Current == null);
        switch (mode) {
        case "waitall-two-incomplete":
        case "waitall-reverse-completion": {
            var a = Gate(); var b = Gate(); int order = 0;
            bool reverse = mode == "waitall-reverse-completion";
            using var second = new Timer(_ => { order = order * 10 + (reverse ? 1 : 2); if (reverse) a.SetResult(11); else b.SetResult(22); }, null, Timeout.Infinite, Timeout.Infinite);
            using var first = After(() => { order = order * 10 + (reverse ? 2 : 1); if (reverse) b.SetResult(22); else a.SetResult(11); Check(second.Change(1, Timeout.Infinite)); }, 1);
            Incomplete(a.Task, b.Task);
            Task.WaitAll(a.Task, b.Task);
            Check(a.Task.Result == 11 && b.Task.Result == 22 && order == (reverse ? 21 : 12));
            break;
        }
        case "waitall-polly-multiple-errors": {
            var first = new InvalidOperationException("original first");
            var second = new InvalidOperationException("original second");
            int attemptsA = 0, attemptsB = 0, callbacksA = 0, callbacksB = 0;
            var pa = Policy.Handle<InvalidOperationException>().WaitAndRetryAsync(1, _ => TimeSpan.FromMilliseconds(1), (_, _, _, _) => ++callbacksA);
            var pb = Policy.Handle<InvalidOperationException>().WaitAndRetryAsync(1, _ => TimeSpan.FromMilliseconds(1), (_, _, _, _) => ++callbacksB);
            Task<int> a = pa.ExecuteAsync<int>(() => { ++attemptsA; return Task.FromException<int>(first); });
            Task<int> b = pb.ExecuteAsync<int>(() => { ++attemptsB; return Task.FromException<int>(second); });
            Incomplete(a, b);
            try { Task.WaitAll(a, b); throw new Exception("aggregate missing"); }
            catch (AggregateException error) {
                Check(error.InnerExceptions.Count == 2 && ReferenceEquals(error.InnerExceptions[0], first)
                    && ReferenceEquals(error.InnerExceptions[1], second));
            }
            Check(attemptsA == 2 && attemptsB == 2 && callbacksA == 1 && callbacksB == 1);
            break;
        }
        case "waitall-task-own-cancellation": {
            using var source = new CancellationTokenSource();
            var a = Gate(); var b = Gate();
            using var first = After(() => { source.Cancel(); a.SetCanceled(source.Token); }, 5);
            using var second = After(() => b.SetResult(22), 30);
            Incomplete(a.Task, b.Task);
            try { Task.WaitAll(a.Task, b.Task); throw new Exception("aggregate missing"); }
            catch (AggregateException error) {
                Check(error.InnerExceptions.Count == 1 && error.InnerExceptions[0] is TaskCanceledException cancelled
                    && cancelled.CancellationToken == source.Token && b.Task.IsCompletedSuccessfully);
            }
            break;
        }
        case "waitall-entry-token-precedence": {
            using var source = new CancellationTokenSource(); source.Cancel();
            try { Task.WaitAll(new[] { Task.CompletedTask }, 0, source.Token); throw new Exception("cancel missing"); }
            catch (OperationCanceledException error) { Check(error.CancellationToken == source.Token); }
            break;
        }
        case "waitall-later-wait-cancel": {
            using var source = new CancellationTokenSource();
            var a = Gate(); var b = Gate();
            using var timer = After(source.Cancel, 5);
            Incomplete(a.Task, b.Task);
            try { Task.WaitAll(new Task[] { a.Task, b.Task }, Timeout.Infinite, source.Token); throw new Exception("cancel missing"); }
            catch (OperationCanceledException error) { Check(error.CancellationToken == source.Token); }
            Incomplete(a.Task, b.Task);
            a.SetResult(11); b.SetResult(22); Task.WaitAll(a.Task, b.Task);
            break;
        }
        case "waitall-one-finite-deadline": {
            var a = Gate(); var b = Gate();
            using var timer = After(() => a.SetResult(11), 1);
            Incomplete(a.Task, b.Task);
            Check(!Task.WaitAll(new Task[] { a.Task, b.Task }, 250));
            Check(a.Task.IsCompletedSuccessfully && !b.Task.IsCompleted);
            b.SetResult(22); Task.WaitAll(a.Task, b.Task);
            Check(a.Task.Result == 11 && b.Task.Result == 22);
            break;
        }
        case "waitall-zero-query": {
            var pending = Gate();
            Check(Task.WaitAll(Array.Empty<Task>(), 0));
            Check(!Task.WaitAll(new Task[] { pending.Task }, 0));
            try { Task.WaitAll((Task[])null!); throw new Exception("null accepted"); }
            catch (ArgumentNullException error) { Check(error.ParamName == "tasks"); }
            try { Task.WaitAll(Array.Empty<Task>(), -2); throw new Exception("timeout accepted"); }
            catch (ArgumentOutOfRangeException error) { Check(error.ParamName == "millisecondsTimeout"); }
            Check(!pending.Task.IsCompleted); pending.SetResult(11); Task.WaitAll(pending.Task);
            break;
        }
        case "waitall-nested-single": {
            context.Value = "outer"; var a = Gate(); var b = Gate(); var nested = Gate();
            using var outer = After(() => {
                Check(context.Value == "outer"); context.Value = "inner";
                using var inner = After(() => nested.SetResult(33), 1);
                Check(!nested.Task.IsCompleted); nested.Task.Wait(); Check(nested.Task.Result == 33); a.SetResult(11);
            }, 1);
            using var sibling = After(() => b.SetResult(22), 50);
            Incomplete(a.Task, b.Task); Task.WaitAll(a.Task, b.Task);
            Check(context.Value == "outer" && a.Task.Result == 11 && b.Task.Result == 22);
            break;
        }
        case "waitall-nested-aggregate": {
            context.Value = "outer"; var root = Gate(); var a = Gate(); var b = Gate();
            using var outer = After(() => {
                Check(context.Value == "outer"); context.Value = "inner";
                using var first = After(() => a.SetResult(11), 1);
                using var second = After(() => b.SetResult(22), 1);
                Incomplete(a.Task, b.Task); Task.WaitAll(a.Task, b.Task); root.SetResult(33);
            }, 1);
            Check(!root.Task.IsCompleted); root.Task.Wait();
            Check(context.Value == "outer" && root.Task.Result == 33 && a.Task.Result == 11 && b.Task.Result == 22);
            break;
        }
        case "pending-root": {
            var a = Gate(); var b = Gate();
            using var first = After(() => a.SetResult(11), 10000);
            using var second = After(() => b.SetResult(22), 10000);
            Incomplete(a.Task, b.Task); Task.WaitAll(a.Task, b.Task);
            throw new Exception("held root unexpectedly completed");
        }
        default: throw new Exception("unknown aggregate case");
        }
        Stage = "completed";
        return "aggregate-task-wait:" + mode + "|original-results-observed";
    }
}
