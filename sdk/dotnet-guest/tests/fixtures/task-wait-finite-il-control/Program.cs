using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Reflection;

// The generated helper bodies are copied unchanged into a host-only assembly.
// The WASI dispatcher and internal context entry are replaced by CLR controls;
// this does not execute or qualify a NativeAOT component.
public static class Projection
{
    public static Task? Current;
    public static int Depth;
    public static Action? DispatchAction;
    public static readonly ExecutionContext Default = (ExecutionContext)typeof(ExecutionContext)
        .GetField("Default", BindingFlags.Static | BindingFlags.NonPublic)!.GetValue(null)!;
    public static bool Dispatch()
    {
        Interlocked.Exchange(ref DispatchAction, null)?.Invoke();
        Thread.Sleep(1);
        return true;
    }
    public static void RunDefault(ExecutionContext context, ContextCallback callback, object? state)
        => ExecutionContext.Run(context, callback, state);
    public static void OriginalPump(object? state) => throw new NotImplementedException();
    public static void FinitePump(object? state) => throw new NotImplementedException();
    public static bool FiniteWait(Task task, int milliseconds, CancellationToken token) => throw new NotImplementedException();
}

internal static class Program
{
    private static Type? projectionType;
    private static void Require(bool value, string reason) { if (!value) throw new InvalidOperationException(reason); }

    internal static MethodDefinition Method(TypeDefinition type, string name)
        => type.Methods.Single(method => method.Name == name);

    internal static void CopyBody(MethodDefinition source, MethodDefinition target, ModuleDefinition module,
                                 Dictionary<string, MethodDefinition> methods, Dictionary<string, FieldDefinition> fields)
    {
        var body = new Mono.Cecil.Cil.MethodBody(target) { InitLocals = source.Body.InitLocals, MaxStackSize = source.Body.MaxStackSize };
        target.Body = body;
        foreach (var local in source.Body.Variables) body.Variables.Add(new VariableDefinition(module.ImportReference(local.VariableType)));
        var instructions = source.Body.Instructions.ToDictionary(instruction => instruction, _ => Instruction.Create(OpCodes.Nop));
        object? Operand(object? operand) => operand switch {
            null => null,
            Instruction instruction => instructions[instruction],
            Instruction[] list => list.Select(instruction => instructions[instruction]).ToArray(),
            VariableDefinition variable => body.Variables[variable.Index],
            ParameterDefinition parameter => target.Parameters[parameter.Index],
            MethodReference method when methods.TryGetValue(method.FullName, out var replacement) => replacement,
            FieldReference field when fields.TryGetValue(field.FullName, out var replacement) => replacement,
            MethodReference method => module.ImportReference(method),
            FieldReference field => module.ImportReference(field),
            TypeReference type => module.ImportReference(type),
            _ => operand,
        };
        foreach (var instruction in source.Body.Instructions)
        {
            var copy = instructions[instruction];
            copy.OpCode = instruction.OpCode;
            copy.Operand = Operand(instruction.Operand);
            body.Instructions.Add(copy);
        }
        Instruction? Map(Instruction? value) => value is null ? null : instructions[value];
        foreach (var handler in source.Body.ExceptionHandlers)
            body.ExceptionHandlers.Add(new ExceptionHandler(handler.HandlerType) {
                TryStart = Map(handler.TryStart), TryEnd = Map(handler.TryEnd),
                HandlerStart = Map(handler.HandlerStart), HandlerEnd = Map(handler.HandlerEnd),
                FilterStart = Map(handler.FilterStart),
                CatchType = handler.CatchType is null ? null : module.ImportReference(handler.CatchType),
            });
    }

    private static string Identity(MethodInfo identity, MethodDefinition method)
        => (string)identity.Invoke(null, new object[] { method, 0 })!;

    private static Func<Task, int, CancellationToken, bool> BuildProjection(string baseline, string candidate,
                                                                            string tool, string output)
    {
        using var oldModule = ModuleDefinition.ReadModule(baseline);
        using var actual = ModuleDefinition.ReadModule(candidate);
        using var projected = ModuleDefinition.ReadModule(Assembly.GetExecutingAssembly().Location);
        var oldLoop = oldModule.Types.Single(type => type.FullName == "System.Threading.WasiEventLoop");
        var loop = actual.Types.Single(type => type.FullName == "System.Threading.WasiEventLoop");
        var target = projected.Types.Single(type => type.FullName == nameof(Projection));
        var identity = Assembly.LoadFrom(tool).GetType("TaskWait", true)!.GetMethod("BodyIdentity", BindingFlags.Static | BindingFlags.NonPublic)!;
        foreach (string name in new[] { "LsfDispatchUntilActualTaskCompletion", "LsfWaitForActualTaskCompletion" })
            Require(Identity(identity, Method(oldLoop, name)) == Identity(identity, Method(loop, name)), "changed-infinite-" + name);
        Require(Method(loop, "LsfWaitForActualTaskCompletion").Parameters.Count == 1, "changed-join-signature");
        var normalPump = Method(loop, "LsfDispatchUntilActualTaskCompletion");
        var finitePump = Method(loop, "LsfObserveFiniteTaskCompletion");
        var finite = Method(loop, "LsfWaitForActualTaskOrTimeout");
        var dispatch = normalPump.Body.Instructions.Select(instruction => instruction.Operand).OfType<MethodReference>()
            .Single(method => method.DeclaringType.FullName == "System.Threading.ThreadPoolWorkQueue" && method.Name == "Dispatch");
        var runContext = finite.Body.Instructions.Select(instruction => instruction.Operand).OfType<MethodReference>()
            .Single(method => method.DeclaringType.FullName == "System.Threading.ExecutionContext" && method.Name == "RunInternal");
        var context = actual.Types.Single(type => type.FullName == "System.Threading.ExecutionContext");
        var methods = new Dictionary<string, MethodDefinition> {
            [normalPump.FullName] = Method(target, "OriginalPump"), [finitePump.FullName] = Method(target, "FinitePump"),
            [dispatch.FullName] = Method(target, "Dispatch"), [runContext.FullName] = Method(target, "RunDefault"),
        };
        var fields = new Dictionary<string, FieldDefinition> {
            [loop.Fields.Single(field => field.Name == "s_mainTask").FullName] = target.Fields.Single(field => field.Name == "Current"),
            [loop.Fields.Single(field => field.Name == "s_lsfTaskWaitDepth").FullName] = target.Fields.Single(field => field.Name == "Depth"),
            [context.Fields.Single(field => field.Name == "Default").FullName] = target.Fields.Single(field => field.Name == "Default"),
        };
        CopyBody(normalPump, Method(target, "OriginalPump"), projected, methods, fields);
        CopyBody(finitePump, Method(target, "FinitePump"), projected, methods, fields);
        CopyBody(finite, Method(target, "FiniteWait"), projected, methods, fields);
        projected.Assembly.Name.Name = "FiniteWaitHostProjection";
        projected.Name = "FiniteWaitHostProjection.dll";
        Require(!File.Exists(output), "projection-output-exists");
        projected.Write(output);
        var loaded = Assembly.LoadFile(Path.GetFullPath(output));
        projectionType = loaded.GetType(nameof(Projection), true)!;
        return projectionType.GetMethod("FiniteWait")!
            .CreateDelegate<Func<Task, int, CancellationToken, bool>>();
    }

    private static (string result, bool completed, bool cancelled, int restored) RestoreCase(
        Func<Task, int, CancellationToken, bool> wait, bool cancelOnRestore)
    {
        var task = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var cancellation = new CancellationTokenSource();
        int restored = 0;
        var local = new AsyncLocal<string?>(change => {
            if (change.ThreadContextChanged && change.CurrentValue == "caller")
            {
                restored++;
                if (cancelOnRestore) cancellation.Cancel(); else task.TrySetResult(42);
            }
        });
        local.Value = "caller";
        string outcome;
        try { outcome = wait(task.Task, 30, cancellation.Token) ? "true" : "false"; }
        catch (OperationCanceledException error)
        {
            Require(error.CancellationToken == cancellation.Token, "original-token");
            outcome = "cancel";
        }
        bool completed = task.Task.IsCompleted, cancelled = cancellation.IsCancellationRequested;
        local.Value = null;
        return (outcome, completed, cancelled, restored);
    }

    private static void Main(string[] args)
    {
        Require(args.Length is 4 or 5, "arguments");
        var wait = BuildProjection(args[0], args[1], args[2], args[3]);
        Require(RestoreCase(wait, false) == ("false", true, false, 1), "emitted-task-snapshot");
        Require(RestoreCase(wait, true) == ("false", false, true, 1), "emitted-token-snapshot");
        var source = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        Require(!wait(source.Task, 0, cancellation.Token), "zero-timeout-token-precedence");
        try { wait(source.Task, 10, cancellation.Token); throw new InvalidOperationException("token-not-thrown"); }
        catch (OperationCanceledException error) { Require(error.CancellationToken == cancellation.Token, "token-identity"); }
        source.SetResult(42);
        Require(wait(source.Task, 0, cancellation.Token), "completed-token-precedence");

        using (var during = new CancellationTokenSource())
        {
            var pending = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
            during.CancelAfter(20);
            try { wait(pending.Task, 1000, during.Token); throw new InvalidOperationException("in-flight-token-not-thrown"); }
            catch (OperationCanceledException error) { Require(error.CancellationToken == during.Token, "in-flight-token-identity"); }
        }
        foreach (string outcome in new[] { "success", "fault", "cancel" })
        {
            var pending = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
            ThreadPool.QueueUserWorkItem(_ => {
                Thread.Sleep(20);
                if (outcome == "success") pending.TrySetResult(42);
                else if (outcome == "fault") pending.TrySetException(new ArgumentException("expected"));
                else pending.TrySetCanceled();
            });
            Require(wait(pending.Task, 1000, CancellationToken.None), "completed-task-not-observed");
            try
            {
                pending.Task.Wait(0); // The original public Task.Wait remainder.
                Require(outcome == "success", "expected-aggregate-exception");
            }
            catch (AggregateException error)
            {
                Require(outcome == "fault" && error.InnerException is ArgumentException
                    || outcome == "cancel" && error.InnerException is TaskCanceledException, "aggregate-exception-shape");
            }
        }

        var current = projectionType!.GetField("Current")!;
        var depth = projectionType.GetField("Depth")!;
        var dispatch = projectionType.GetField("DispatchAction")!;
        var prior = new TaskCompletionSource<int>().Task;
        current.SetValue(null, prior); depth.SetValue(null, 4);
        var outer = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
        dispatch.SetValue(null, (Action)(() => {
            var outerWake = current.GetValue(null);
            Require(!ReferenceEquals(outerWake, prior) && (int)depth.GetValue(null)! == 5, "outer-scope");
            var inner = new TaskCompletionSource<int>(TaskCreationOptions.RunContinuationsAsynchronously);
            ThreadPool.QueueUserWorkItem(_ => { Thread.Sleep(20); inner.TrySetResult(1); });
            Require(wait(inner.Task, 1000, CancellationToken.None), "nested-wait");
            Require(ReferenceEquals(current.GetValue(null), outerWake) && (int)depth.GetValue(null)! == 5, "nested-scope-restore");
            outer.TrySetResult(1);
        }));
        Require(wait(outer.Task, 1000, CancellationToken.None), "outer-wait");
        Require(ReferenceEquals(current.GetValue(null), prior) && (int)depth.GetValue(null)! == 4, "outer-scope-restore");
        var thrown = new InvalidOperationException("dispatch-primary");
        dispatch.SetValue(null, (Action)(() => throw thrown));
        try { wait(new TaskCompletionSource<int>().Task, 1000, CancellationToken.None); throw new InvalidOperationException("dispatch-did-not-throw"); }
        catch (InvalidOperationException error) { Require(ReferenceEquals(error, thrown), "dispatch-primary-changed"); }
        Require(ReferenceEquals(current.GetValue(null), prior) && (int)depth.GetValue(null)! == 4, "exception-scope-restore");
        Console.WriteLine("FINITE_WAIT_EMITTED_IL_HOST PASS unchanged-infinite;restore-task;restore-token;precedence;outcomes;nested;finally");
        if (args.Length == 5)
            AggregateFiniteControl.Run(args[1], args[4], args[2], args[3]);
    }
}
