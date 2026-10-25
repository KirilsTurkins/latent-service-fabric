using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;

internal static class Reference
{
    private const string TaskType = "System.Threading.Tasks.Task";
    private const string LoopType = "System.Threading.WasiEventLoop";
    private const string MresType = "System.Threading.ManualResetEventSlim";
    private const string TokenType = "System.Threading.CancellationToken";
    private delegate void SpanWait(ReadOnlySpan<Task> tasks);
    private static ActualCil cil = null!;
    private static string Method(string result, string owner, string name, params string[] arguments) =>
        result + " " + owner + "::" + name + "(" + string.Join(',', arguments) + ")";
    private static Func<Task[], int, CancellationToken, bool> All => cil.Delegate<Func<Task[], int, CancellationToken, bool>>(
        Method("System.Boolean", TaskType, "WaitAll", TaskType + "[]", "System.Int32", TokenType));
    private static Func<ManualResetEventSlim, int, CancellationToken, bool> Mres =>
        cil.Delegate<Func<ManualResetEventSlim, int, CancellationToken, bool>>(
            Method("System.Boolean", MresType, "LsfAggregateWait", "System.Int32", TokenType));
    private static Func<Task, bool> Single => cil.Delegate<Func<Task, bool>>(
        Method("System.Boolean", LoopType, "LsfWaitForActualTaskCompletion", TaskType));
    private static TaskCompletionSource<int> Pending() => new();
    private static void Need(bool value, string code) => ActualCil.Need(value, code);
    private static void Schedule(Action work) => Ports.Work.Enqueue(work);

    private sealed record State(Task? Main, int Depth, ManualResetEventSlim? Target,
        CancellationToken Token, long Start, int Timeout, bool Completed);
    private static State StateNow() => new(Ports.s_mainTask, Ports.s_lsfTaskWaitDepth, Ports.s_lsfAggregateTarget,
        Ports.s_lsfAggregateToken, Ports.s_lsfAggregateStart, Ports.s_lsfAggregateTimeout, Ports.s_lsfAggregateCompleted);
    private static void Cancelled(Action work, CancellationToken token)
    {
        try { work(); }
        catch (OperationCanceledException error) { Need(error.CancellationToken == token, "original-wait-token"); return; }
        throw new InvalidOperationException("aggregate-reference:missing-cancellation");
    }
    private static void SameFailure(Action work, Exception original)
    {
        try { work(); }
        catch (Exception error) { Need(ReferenceEquals(error, original), "original-failure-object"); return; }
        throw new InvalidOperationException("aggregate-reference:missing-original-failure");
    }
    private static bool ContainsCountdown(Task task, ManualResetEventSlim countdown)
    {
        var field = typeof(Task).GetField("m_continuationObject", BindingFlags.Instance | BindingFlags.NonPublic);
        Need(field is not null && field.FieldType == typeof(object), "host-continuation-field-shape");
        var value = field!.GetValue(task);
        if (ReferenceEquals(value, countdown)) return true;
        if (value is System.Collections.IList list)
        {
            Need(list.Count <= 16, "bounded-host-continuation-list");
            return list.Cast<object?>().Any(item => ReferenceEquals(item, countdown));
        }
        return false;
    }

    private static void Run(string name)
    {
        switch (name)
        {
            case "entry-cancellation-before-set": {
                using var signal = new ManualResetEventSlim(true); using var token = new CancellationTokenSource(); token.Cancel();
                Cancelled(() => Mres(signal, -1, token.Token), token.Token);
                Need(Ports.StartReads == 0 && Ports.WakeCalls == 0, "entry-no-clock-or-wake"); break;
            }
            case "disposal-before-cancellation": {
                var signal = new ManualResetEventSlim(false); signal.Dispose(); using var token = new CancellationTokenSource(); token.Cancel();
                try { Mres(signal, -1, token.Token); }
                catch (ObjectDisposedException) { break; }
                throw new InvalidOperationException("aggregate-reference:missing-disposal-precedence");
            }
            case "zero-and-already-set-no-clock": {
                using var signal = new ManualResetEventSlim(false);
                Need(!Mres(signal, 0, default), "zero-unset"); signal.Set();
                Need(Mres(signal, 0, default) && Mres(signal, -1, default), "already-set");
                Need(Ports.StartReads == 0 && Ports.RemainingReads == 0 && Ports.WakeCalls == 0, "fast-no-clock-or-wake"); break;
            }
            case "all-seven-public-overloads": {
                Task[] done = [Task.CompletedTask, Task.CompletedTask];
                cil.Delegate<Action<Task[]>>(Method("System.Void", TaskType, "WaitAll", TaskType + "[]"))(done);
                cil.Delegate<SpanWait>(Method("System.Void", TaskType, "WaitAll", "System.ReadOnlySpan`1<" + TaskType + ">"))(done);
                Need(cil.Delegate<Func<Task[], TimeSpan, bool>>(Method("System.Boolean", TaskType, "WaitAll", TaskType + "[]", "System.TimeSpan"))(done, TimeSpan.Zero), "timespan-overload");
                Need(cil.Delegate<Func<Task[], int, bool>>(Method("System.Boolean", TaskType, "WaitAll", TaskType + "[]", "System.Int32"))(done, 0), "integer-overload");
                cil.Delegate<Action<Task[], CancellationToken>>(Method("System.Void", TaskType, "WaitAll", TaskType + "[]", TokenType))(done, default);
                Need(All(done, 0, default), "timeout-token-overload");
                cil.Delegate<Action<IEnumerable<Task>, CancellationToken>>(Method("System.Void", TaskType, "WaitAll", "System.Collections.Generic.IEnumerable`1<" + TaskType + ">", TokenType))(done, default);
                Need(Ports.Dispatches == 0 && Ports.WakeCalls == 0, "completed-overloads-no-work"); break;
            }
            case "original-validation-precedence": {
                Need(All([], 0, default), "empty-all");
                bool nullArray = false, badTimeout = false, nullElement = false;
                try { All(null!, -2, default); }
                catch (ArgumentNullException error) when (error.ParamName == "tasks") { nullArray = true; }
                try { All([Task.CompletedTask], -2, default); }
                catch (ArgumentOutOfRangeException error) when (error.ParamName == "millisecondsTimeout") { badTimeout = true; }
                try { All([null!], 0, default); }
                catch (ArgumentException error) when (error.ParamName == "tasks") { nullElement = true; }
                Need(nullArray && badTimeout && nullElement, "validation-precedence");
                using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
                Cancelled(() => All([null!], 0, cancelled.Token), cancelled.Token);
                break;
            }
            case "pending-first-order":
            case "pending-reverse-order": {
                var a = Pending(); var b = Pending(); Need(!a.Task.IsCompleted && !b.Task.IsCompleted, "actual-incomplete-tasks");
                Schedule(() => (name == "pending-first-order" ? a : b).SetResult(1));
                Schedule(() => (name == "pending-first-order" ? b : a).SetResult(2));
                Need(All([a.Task, b.Task], -1, default) && Ports.Dispatches == 2, "real-countdown-both-tasks");
                Need(Ports.StartReads == 0 && Ports.RemainingReads == 0 && Ports.WakeCalls == 0, "infinite-no-added-clock"); break;
            }
            case "original-multiple-fault-identity": {
                var a = Pending(); var b = Pending(); var first = new ArgumentException("controlled-first"); var second = new FormatException("controlled-second");
                Schedule(() => b.SetException(second)); Schedule(() => a.SetException(first));
                try { All([a.Task, b.Task], -1, default); }
                catch (AggregateException error) {
                    Need(error.InnerExceptions.Count == 2 && ReferenceEquals(error.InnerExceptions[0], first)
                        && ReferenceEquals(error.InnerExceptions[1], second), "original-aggregate-input-order"); break;
                }
                throw new InvalidOperationException("aggregate-reference:missing-original-aggregate");
            }
            case "original-task-cancellation-token": {
                var a = Pending(); using var own = new CancellationTokenSource(); own.Cancel();
                Schedule(() => a.SetCanceled(own.Token));
                try { All([a.Task], -1, default); }
                catch (AggregateException error) {
                    Need(error.InnerException is TaskCanceledException cancelled && cancelled.CancellationToken == own.Token, "original-task-token"); break;
                }
                throw new InvalidOperationException("aggregate-reference:missing-task-aggregate");
            }
            case "single-overall-deadline": {
                var a = Pending(); var b = Pending();
                Schedule(() => { Ports.Now = 400; a.SetResult(1); });
                Schedule(() => Ports.Now = 700);
                Need(!All([a.Task, b.Task], 600, default) && a.Task.IsCompleted && !b.Task.IsCompleted, "one-overall-deadline");
                Need(Ports.StartReads == 1 && Ports.RemainingReads > 0 && Ports.WakeCalls == 1, "one-finite-start-wake");
                Need(Ports.ObservedTarget is { } && !ContainsCountdown(b.Task, Ports.ObservedTarget), "timeout-original-detach"); b.SetResult(2); break;
            }
            case "late-completion-before-cancellation": {
                var a = Pending(); var b = Pending(); using var token = new CancellationTokenSource();
                Schedule(() => { a.SetResult(1); b.SetResult(2); token.Cancel(); });
                Need(All([a.Task, b.Task], -1, token.Token), "later-completion-wins");
                Need(Ports.StartReads == 0 && Ports.RemainingReads == 0, "infinite-cancellable-no-clock"); break;
            }
            case "later-cancellation-detaches-original": {
                var a = Pending(); var b = Pending(); using var token = new CancellationTokenSource(); Schedule(token.Cancel);
                Cancelled(() => All([a.Task, b.Task], -1, token.Token), token.Token);
                Need(!a.Task.IsCompleted && !b.Task.IsCompleted && Ports.ObservedTarget is { }, "cancel-does-not-complete-tasks");
                Need(!ContainsCountdown(a.Task, Ports.ObservedTarget!) && !ContainsCountdown(b.Task, Ports.ObservedTarget!), "cancel-original-detach");
                Need(Ports.StartReads == 0 && Ports.RemainingReads == 0, "infinite-cancel-no-clock");
                a.SetResult(1); b.SetResult(2); break;
            }
            case "ready-ignores-completed-old-main": {
                var a = Pending(); var b = Pending(); int checks = 0;
                Ports.BeforeDispatch = () => { Need(!Ports.Ready(), "old-main-not-aggregate-ready"); checks++; };
                Schedule(() => a.SetResult(1)); Schedule(() => b.SetResult(2));
                Need(All([a.Task, b.Task], -1, default) && checks == 2, "aggregate-target-precedence"); break;
            }
            case "ready-after-countdown-before-poll": {
                var a = Pending(); bool readyWithUnrelatedPending = false;
                Schedule(() => a.SetResult(1)); Ports.AfterDispatch = () => readyWithUnrelatedPending = Ports.Ready();
                Need(All([a.Task], -1, default) && readyWithUnrelatedPending, "completion-nonblocking-predicate"); break;
            }
            case "nested-single-inside-aggregate": {
                var outer = Pending(); var inner = Pending();
                Schedule(() => {
                    var aggregate = StateNow(); Schedule(() => inner.SetResult(1));
                    Need(Single(inner.Task) && StateNow() == aggregate, "single-restores-aggregate"); outer.SetResult(2);
                });
                Need(All([outer.Task], -1, default), "outer-aggregate-completion"); break;
            }
            case "nested-aggregate-inside-single": {
                var outer = Pending(); var inner = Pending();
                Schedule(() => {
                    var single = StateNow(); Schedule(() => inner.SetResult(1));
                    Need(All([inner.Task], -1, default) && StateNow() == single, "aggregate-restores-single"); outer.SetResult(2);
                }); Need(Single(outer.Task), "outer-single-completion"); break;
            }
            case "dispatch-fault-restores-state": {
                var pending = Pending(); var fault = new ArgumentException("controlled-dispatch-fault"); Schedule(() => throw fault);
                SameFailure(() => All([pending.Task], 600, default), fault); pending.SetResult(1); break;
            }
            case "late-context-restoration-keeps-timeout":
            case "late-restoration-nested-decision": {
                var pending = Pending(); bool armed = false, restored = false, nested = false;
                var local = new AsyncLocal<string?>(change => {
                    if (!armed || !change.ThreadContextChanged || change.CurrentValue != "caller" || restored) return;
                    restored = true;
                    if (name == "late-restoration-nested-decision") {
                        var other = Pending(); Schedule(() => other.SetResult(2));
                        nested = All([other.Task], -1, default);
                    }
                    pending.SetResult(1);
                });
                local.Value = "caller"; armed = true; Schedule(() => Ports.Now = 700);
                Need(!All([pending.Task], 600, default) && restored && pending.Task.IsCompleted, "recorded-timeout-before-context-restore");
                Need(name != "late-restoration-nested-decision" || nested, "nested-restoration-decision");
                armed = false; local.Value = null; break;
            }
            case "wake-admission-refusal-restores-state": {
                var pending = Pending(); var error = new ArgumentException("controlled-wake-refusal"); Ports.DelayFailure = error;
                SameFailure(() => All([pending.Task], 600, default), error); Ports.DelayFailure = null; pending.SetResult(1); break;
            }
            case "cleanup-cancel-refusal-restores-state":
            case "cleanup-dispose-refusal-restores-state": {
                var pending = Pending(); var error = new ArgumentException("controlled-cleanup-refusal");
                if (name == "cleanup-cancel-refusal-restores-state") OwnedSource.CancelFailure = error; else OwnedSource.DisposeFailure = error;
                Schedule(() => pending.SetResult(1)); SameFailure(() => All([pending.Task], 600, default), error);
                Need(OwnedSource.Cancels == 1 && OwnedSource.Disposals == 1, "both-cleanup-paths-on-refusal"); break;
            }
            case "non-wasi-original-entry-once": {
                Ports.Platform = false; using var signal = new ManualResetEventSlim(true);
                Need(Mres(signal, 0, default) && Ports.Dispatches == 0 && Ports.StartReads == 0
                    && OwnedSource.Births == 0 && Ports.CopiedValidationCalls == 0,
                    "original-non-wasi-path"); break;
            }
            default: throw new InvalidOperationException("aggregate-reference:unknown-case");
        }
    }

    private static int Main(string[] args)
    {
        try
        {
            Need(args.Length == 2 && args.All(arg => arg.Length is > 0 and < 4096), "fixed-arguments");
            using var input = new ActualCil(args[0]); cil = input;
            Ports.AggregateBody = cil.Delegate<Action<object?>>(Method("System.Void", LoopType, "LsfAggregateDispatch", "System.Object"));
            Ports.SingleBody = cil.Delegate<Action<object?>>(Method("System.Void", LoopType, "LsfDispatchUntilActualTaskCompletion", "System.Object"));
            Ports.Ready = cil.Delegate<Func<bool>>(Method("System.Boolean", LoopType, "LsfAggregateReady"));
            Ports.s_mainTask = Task.CompletedTask; Ports.s_lsfAggregateStart = 37;
            Ports.s_lsfAggregateTimeout = 414; Ports.s_lsfAggregateCompleted = true;
            var before = StateNow(); Run(args[1]); Need(StateNow() == before, "exact-original-target-state-restored");
            Need(Ports.Work.Count == 0, "no-undispatched-control-work");
            var host = typeof(Task).Assembly.Location;
            Console.WriteLine(JsonSerializer.Serialize(new {
                control = args[1], passed = true, scope = "actual-generated-IL-with-closed-host-reference-ports",
                sourceQualified = false, nativeAotExecuted = false, signedComponentExecuted = false,
                wholeWaitAllCoreGuestQualified = false, runtime = RuntimeInformation.FrameworkDescription,
                runtimeVersion = Environment.Version.ToString(), hostCoreLibSha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(host))).ToLowerInvariant(),
                originalTargetStateRestored = true, startClockReads = Ports.StartReads,
                remainingClockReads = Ports.RemainingReads, wakeCalls = Ports.WakeCalls,
                copiedValidationCalls = Ports.CopiedValidationCalls,
                dispatches = Ports.Dispatches, linkedSources = OwnedSource.Births,
                cancels = OwnedSource.Cancels, disposals = OwnedSource.Disposals, cil = cil.Observation(),
            })); return 0;
        }
        catch (Exception error)
        {
            var text = error.Message.StartsWith("aggregate-reference:", StringComparison.Ordinal)
                ? error.Message : error.GetType().FullName ?? "unknown";
            Console.Error.WriteLine(text.Length <= 2048 ? text : "aggregate-reference:bounded-failure"); return 1;
        }
    }
}
