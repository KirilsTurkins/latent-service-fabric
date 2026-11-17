using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Reflection;

// Only these host ports are substituted. This projection neither runs a
// signed component nor claims the real dispatcher or pollable has run.
public static class AggregateFiniteProjection
{
    public static Task? Current;
    public static int Depth;
    public static ManualResetEventSlim? Target;
    public static CancellationToken Token;
    public static long Start;
    public static int Timeout;
    public static bool Observed;
    public static Action? DispatchAction;
    public static readonly ExecutionContext Default = (ExecutionContext)typeof(ExecutionContext)
        .GetField("Default", BindingFlags.Static | BindingFlags.NonPublic)!.GetValue(null)!;

    public static void EnsureJoinReady() { } // No managed admission in this host projection.
    public static bool Prefetched() => false;
    public static long Remaining(long start, long timeout) => Math.Max(0, timeout - (Environment.TickCount64 - start));
    public static bool Dispatch()
    {
        Interlocked.Exchange(ref DispatchAction, null)?.Invoke();
        Thread.Sleep(1);
        return true;
    }
    public static void RunDefault(ExecutionContext context, ContextCallback callback, object? state)
        => ExecutionContext.Run(context, callback, state);
    public static bool Ready() => throw new NotImplementedException();
    public static void OriginalPump(object? state) => throw new NotImplementedException();
    public static void FinitePump(object? state) => throw new NotImplementedException();
    public static bool FiniteWait(Task task, int milliseconds, CancellationToken token) => throw new NotImplementedException();
}

internal static class AggregateFiniteControl
{
    private const string OriginalFinite = "8606fa511dc66800891d7d1d6aa9a39e581e1de59a27e4524356ef292002dd1e";
    private const string FixedFinite = "28c962130eac6aabab096d74cf2a6ef1775fc2a317fc5bf60e9fbe9706cab002";
    private const string ReadyIdentity = "4eabc2f11e2f7eac8a6d4a67812a51d356b7654101845c01458b5f85754cb5a7";

    private static void Require(bool value, string message)
    {
        if (!value) throw new InvalidOperationException(message);
    }

    private static Type BuildProjection(string assembly, string originalFinite, string tool, string output, bool fixedVersion)
    {
        using var actual = ModuleDefinition.ReadModule(assembly);
        using var baselineModule = ModuleDefinition.ReadModule(originalFinite);
        using var projected = ModuleDefinition.ReadModule(Assembly.GetExecutingAssembly().Location);
        var loop = actual.Types.Single(type => type.FullName == "System.Threading.WasiEventLoop");
        var context = actual.Types.Single(type => type.FullName == "System.Threading.ExecutionContext");
        var target = projected.Types.Single(type => type.FullName == nameof(AggregateFiniteProjection));
        var ready = Program.Method(loop, "LsfAggregateReady");
        var normalPump = Program.Method(loop, "LsfDispatchUntilActualTaskCompletion");
        var finitePump = Program.Method(loop, "LsfObserveFiniteTaskCompletion");
        var originalLoop = baselineModule.Types.Single(type => type.FullName == "System.Threading.WasiEventLoop");
        var finite = Program.Method(fixedVersion ? loop : originalLoop, "LsfWaitForActualTaskOrTimeout");
        var identity = Assembly.LoadFrom(tool).GetType("TaskWait", true)!
            .GetMethod("BodyIdentity", BindingFlags.Static | BindingFlags.NonPublic)!;
        string Identify(MethodDefinition method) => (string)identity.Invoke(null, new object[] { method, 0 })!;
        Require(Identify(ready) == ReadyIdentity, "aggregate-ready-identity");
        Require(Identify(finite) == (fixedVersion ? FixedFinite : OriginalFinite), "aggregate-finite-identity");

        var methods = new Dictionary<string, MethodDefinition>();
        var copies = new[] { (ready, "Ready"), (normalPump, "OriginalPump"),
                             (finitePump, "FinitePump"), (finite, "FiniteWait") };
        foreach (var (source, name) in copies) methods[source.FullName] = Program.Method(target, name);
        var references = ready.Body.Instructions.Concat(normalPump.Body.Instructions).Concat(finite.Body.Instructions)
            .Select(instruction => instruction.Operand).OfType<MethodReference>().ToArray();
        methods[references.Single(method => method.Name == "LsfManagedWorkPrefetchedReady").FullName] = Program.Method(target, "Prefetched");
        methods[references.Single(method => method.Name == "EnsureJoinReady").FullName] = Program.Method(target, "EnsureJoinReady");
        methods[references.Single(method => method.Name == "UpdateTimeOut").FullName] = Program.Method(target, "Remaining");
        methods[references.First(method => method.Name == "Dispatch" && method.DeclaringType.FullName == "System.Threading.ThreadPoolWorkQueue").FullName]
            = Program.Method(target, "Dispatch");
        methods[references.Single(method => method.Name == "RunInternal" && method.DeclaringType.FullName == "System.Threading.ExecutionContext").FullName]
            = Program.Method(target, "RunDefault");
        var fields = new Dictionary<string, FieldDefinition>();
        foreach (var (original, replacement) in new[] { ("s_mainTask", "Current"), ("s_lsfTaskWaitDepth", "Depth"),
                     ("s_lsfAggregateTarget", "Target"), ("s_lsfAggregateToken", "Token"), ("s_lsfAggregateStart", "Start"),
                     ("s_lsfAggregateTimeout", "Timeout"), ("s_lsfAggregateCompleted", "Observed") })
            fields[loop.Fields.Single(field => field.Name == original).FullName] = target.Fields.Single(field => field.Name == replacement);
        fields[context.Fields.Single(field => field.Name == "Default").FullName] = target.Fields.Single(field => field.Name == "Default");
        foreach (var (source, name) in copies) Program.CopyBody(source, Program.Method(target, name), projected, methods, fields);
        var assemblyName = fixedVersion ? "AggregateFiniteFixedProjection" : "AggregateFiniteOriginalProjection";
        projected.Assembly.Name.Name = assemblyName;
        projected.Name = assemblyName + ".dll";
        Require(!File.Exists(output), "aggregate-projection-output-exists");
        projected.Write(output);
        return Assembly.LoadFile(Path.GetFullPath(output)).GetType(nameof(AggregateFiniteProjection), true)!;
    }

    private static void ClrReference()
    {
        var nested = new TaskCompletionSource<int>();
        var worker = Task.Run(() => {
            ThreadPool.QueueUserWorkItem(_ => nested.SetResult(42));
            return nested.Task.Wait(3000);
        });
        Require(Task.WaitAll(new[] { worker }, 5000) && worker.Result, "clr-nested-finite-in-aggregate");
    }

    private static void CheckProjection(Type projection, bool fixedVersion)
    {
        var ready = projection.GetMethod("Ready")!.CreateDelegate<Func<bool>>();
        var wait = projection.GetMethod("FiniteWait")!.CreateDelegate<Func<Task, int, CancellationToken, bool>>();
        var target = projection.GetField("Target")!;
        var current = projection.GetField("Current")!;
        var depth = projection.GetField("Depth")!;
        var action = projection.GetField("DispatchAction")!;
        var timeout = projection.GetField("Timeout")!;
        using var aggregate = new ManualResetEventSlim(false);
        var previous = new TaskCompletionSource<int>().Task;
        target.SetValue(null, aggregate); current.SetValue(null, previous); timeout.SetValue(null, -1); depth.SetValue(null, 4);
        void Restored() => Require(ReferenceEquals(target.GetValue(null), aggregate)
            && ReferenceEquals(current.GetValue(null), previous) && (int)depth.GetValue(null)! == 4, "aggregate-frame-not-restored");
        var nested = new TaskCompletionSource<int>();
        bool masked = false, readyAfterCompletion = false;
        action.SetValue(null, (Action)(() => {
            masked = target.GetValue(null) is null;
            nested.SetResult(42);
            Require(((Task)current.GetValue(null)!).IsCompleted, "finite-wake-not-completed");
            readyAfterCompletion = ready();
        }));
        Require(wait(nested.Task, 3000, CancellationToken.None), "nested-finite-did-not-complete");
        Restored();
        Require(masked == fixedVersion && readyAfterCompletion == fixedVersion, "nested-readiness-mismatch");
        if (!fixedVersion) return;

        // A completed outer aggregate must not make an incomplete inner wake
        // appear ready; after inner completion that same wake must be ready.
        aggregate.Set();
        nested = new TaskCompletionSource<int>();
        action.SetValue(null, (Action)(() => {
            Require(target.GetValue(null) is null && !ready(), "outer-completion-shadowed-inner");
            nested.SetResult(42);
            Require(((Task)current.GetValue(null)!).IsCompleted && ready(), "inner-completion-hidden");
        }));
        Require(wait(nested.Task, 3000, CancellationToken.None), "completed-outer-control");
        Restored(); aggregate.Reset();

        using (var cancellation = new CancellationTokenSource())
        {
            nested = new TaskCompletionSource<int>();
            action.SetValue(null, (Action)(() => {
                Require(target.GetValue(null) is null, "cancel-unmasked");
                cancellation.Cancel();
            }));
            try { wait(nested.Task, 3000, cancellation.Token); throw new InvalidOperationException("cancellation-not-observed"); }
            catch (OperationCanceledException error) { Require(error.CancellationToken == cancellation.Token, "cancellation-token-changed"); }
            Restored();
        }
        nested = new TaskCompletionSource<int>();
        action.SetValue(null, (Action)(() => Require(target.GetValue(null) is null, "timeout-unmasked")));
        Require(!wait(nested.Task, 20, CancellationToken.None), "timeout-not-observed");
        Restored();

        var failure = new InvalidOperationException("dispatch-primary");
        action.SetValue(null, (Action)(() => throw failure));
        try { wait(new TaskCompletionSource<int>().Task, 3000, CancellationToken.None); throw new InvalidOperationException("failure-not-observed"); }
        catch (InvalidOperationException error) { Require(ReferenceEquals(error, failure), "dispatch-failure-changed"); }
        Restored();

        var outer = new TaskCompletionSource<int>();
        action.SetValue(null, (Action)(() => {
            var outerWake = current.GetValue(null);
            Require(target.GetValue(null) is null && (int)depth.GetValue(null)! == 5, "outer-finite-frame");
            var inner = new TaskCompletionSource<int>();
            action.SetValue(null, (Action)(() => inner.SetResult(1)));
            Require(wait(inner.Task, 3000, CancellationToken.None), "inner-finite-frame");
            Require(target.GetValue(null) is null && ReferenceEquals(current.GetValue(null), outerWake)
                && (int)depth.GetValue(null)! == 5, "inner-finite-frame-not-restored");
            outer.SetResult(1);
        }));
        Require(wait(outer.Task, 3000, CancellationToken.None), "outer-finite-frame-not-completed");
        Restored();
    }

    internal static void Run(string originalFinite, string candidate, string tool, string output)
    {
        ClrReference();
        CheckProjection(BuildProjection(candidate, originalFinite, tool, output + ".aggregate-original.dll", false), false);
        CheckProjection(BuildProjection(candidate, originalFinite, tool, output + ".aggregate-fixed.dll", true), true);
        Console.WriteLine("AGGREGATE_FINITE_IL_HOST PASS clr-reference;original-mismatch;ready;timeout;cancellation;exception;nested;restore");
    }
}
