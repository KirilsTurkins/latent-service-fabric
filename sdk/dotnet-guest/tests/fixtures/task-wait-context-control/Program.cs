using System.Globalization;
using System.Reflection;
using System.Text.Json;

// A host CoreLib reference control, never a WASI component qualification.
internal static class Program
{
    private const BindingFlags Flags = BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Instance;
    private static readonly ExecutionContext Default = (ExecutionContext)typeof(ExecutionContext).GetField("Default", Flags)!.GetValue(null)!;
    private static readonly Action<ExecutionContext, ContextCallback, object?> Run =
        typeof(ExecutionContext).GetMethod("RunInternal", Flags)!.CreateDelegate<Action<ExecutionContext, ContextCallback, object?>>();
    private static readonly FieldInfo Execution = typeof(Thread).GetField("_executionContext", Flags)!;
    private static readonly FieldInfo Synchronization = typeof(Thread).GetField("_synchronizationContext", Flags)!;

    private sealed class ProbeException : Exception { }
    private sealed class ProbeContext : SynchronizationContext { }

    private static void Require(bool condition, string reason)
    {
        if (!condition) throw new InvalidOperationException(reason);
    }

    // Exact entry contract of the pinned Dispatch: it clears both fields.
    private static void DispatchEntry()
    {
        Execution.SetValue(Thread.CurrentThread, null);
        Synchronization.SetValue(Thread.CurrentThread, null);
    }

    private static object Case(string outcome, bool suppressed, bool wrapped)
    {
        var changes = new List<(string? Previous, string? Current, bool Transition)>();
        var local = new AsyncLocal<string?>(args => changes.Add((args.PreviousValue, args.CurrentValue, args.ThreadContextChanged)));
        local.Value = "caller";
        var caller = new ProbeContext();
        SynchronizationContext.SetSynchronizationContext(caller);
        CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("de-DE");
        CultureInfo.CurrentUICulture = CultureInfo.GetCultureInfo("ja-JP");
        if (suppressed) ExecutionContext.SuppressFlow();
        var original = Execution.GetValue(Thread.CurrentThread);
        var task = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        Require(!task.Task.IsCompleted, "task-must-start-incomplete");
        ContextCallback dispatch = _ => {
            if (wrapped) Require(!ExecutionContext.IsFlowSuppressed() && local.Value is null, "default-context-entry");
            DispatchEntry();
            local.Value = "callback";
            CultureInfo.CurrentCulture = CultureInfo.GetCultureInfo("fr-FR");
            CultureInfo.CurrentUICulture = CultureInfo.GetCultureInfo("en-US");
            if (outcome == "reentrant")
            {
                var innerContext = new ProbeContext();
                SynchronizationContext.SetSynchronizationContext(innerContext);
                ExecutionContext.SuppressFlow();
                var innerOriginal = Execution.GetValue(Thread.CurrentThread);
                try
                {
                    Run(Default, _ => {
                        Require(local.Value is null && !ExecutionContext.IsFlowSuppressed(), "nested-default-entry");
                        DispatchEntry();
                        local.Value = "nested";
                    }, null);
                    Require(ReferenceEquals(Execution.GetValue(Thread.CurrentThread), innerOriginal) &&
                        local.Value == "callback" && ExecutionContext.IsFlowSuppressed() &&
                        ReferenceEquals(SynchronizationContext.Current, innerContext) &&
                        CultureInfo.CurrentCulture.Name == "fr-FR" && CultureInfo.CurrentUICulture.Name == "en-US",
                        "nested-context-restore");
                }
                finally
                {
                    if (ExecutionContext.IsFlowSuppressed()) ExecutionContext.RestoreFlow();
                }
                Require(changes.Contains(("callback", null, true)) && changes.Contains(("nested", "callback", true)),
                    "nested-asynclocal-notifications");
            }
            if (outcome == "callback-throw") throw new ProbeException();
            if (outcome == "fault") task.SetException(new ProbeException());
            else if (outcome == "cancel") task.SetCanceled(new CancellationToken(true));
            else task.SetResult(7);
        };
        var callbackThrew = false;
        try
        {
            if (wrapped) Run(Default, dispatch, null);
            else dispatch(null);
        }
        catch (ProbeException) { callbackThrew = true; }
        var preserved = ReferenceEquals(Execution.GetValue(Thread.CurrentThread), original) &&
            local.Value == "caller" && ExecutionContext.IsFlowSuppressed() == suppressed &&
            ReferenceEquals(SynchronizationContext.Current, caller) &&
            CultureInfo.CurrentCulture.Name == "de-DE" && CultureInfo.CurrentUICulture.Name == "ja-JP";
        if (!wrapped)
        {
            Require(!preserved && !ReferenceEquals(SynchronizationContext.Current, caller) && local.Value != "caller",
                "old-unwrapped-path-must-fail-context-contract");
            return new { outcome, suppressed, wrapped, oldPathRejected = true };
        }
        Require(preserved, "caller-context-restore");
        Require(changes.Contains(("caller", null, true)) && changes.Contains(("callback", "caller", true)),
            "caller-asynclocal-notifications");
        Require(callbackThrew == (outcome == "callback-throw"), "callback-exception-shape");
        if (!callbackThrew)
        {
            try
            {
                Require(task.Task.GetAwaiter().GetResult() == 7 && outcome is "normal" or "reentrant", "actual-task-result");
            }
            catch (ProbeException) { Require(outcome == "fault", "original-fault-propagation"); }
            catch (OperationCanceledException) { Require(outcome == "cancel" && task.Task.IsCanceled, "original-cancel-propagation"); }
            Require(ReferenceEquals(Execution.GetValue(Thread.CurrentThread), original) && local.Value == "caller" &&
                ReferenceEquals(SynchronizationContext.Current, caller), "context-before-original-taskawaiter-return");
        }
        return new { outcome, suppressed, wrapped, rawContextPreserved = true, notificationsPreserved = true };
    }

    private static int Main()
    {
        try
        {
            var cases = new List<object>();
            foreach (var suppressed in new[] { false, true })
            foreach (var outcome in new[] { "normal", "fault", "cancel", "reentrant", "callback-throw", "unwrapped-negative" })
            {
                Exception? failure = null;
                object? result = null;
                var thread = new Thread(() => {
                    try
                    {
                        var before = Execution.GetValue(Thread.CurrentThread);
                        var context = SynchronizationContext.Current;
                        var culture = CultureInfo.CurrentCulture;
                        var uiCulture = CultureInfo.CurrentUICulture;
                        // This outer owned scope restores every case, including
                        // the intentionally broken negative and assertion exits.
                        Run(Default, _ => result = Case(outcome, suppressed, outcome != "unwrapped-negative"), null);
                        Require(ReferenceEquals(Execution.GetValue(Thread.CurrentThread), before) &&
                            ReferenceEquals(SynchronizationContext.Current, context) &&
                            CultureInfo.CurrentCulture.Equals(culture) && CultureInfo.CurrentUICulture.Equals(uiCulture),
                            "owned-thread-scope-not-restored");
                    }
                    catch (Exception error) { failure = error; }
                });
                thread.Start();
                Require(thread.Join(TimeSpan.FromSeconds(5)), "owned-thread-not-joined");
                if (failure is not null) throw new InvalidOperationException("reference-control-failed", failure);
                cases.Add(result!);
            }
            Console.WriteLine(JsonSerializer.Serialize(new { scope = "host-CoreLib-reference-control-only",
                wasiGuestExecution = false, pinnedWasiQualification = false, cases, status = "passed" }));
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.ToString());
            return 1;
        }
    }
}
