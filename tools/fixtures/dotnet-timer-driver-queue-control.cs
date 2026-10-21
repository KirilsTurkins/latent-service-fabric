using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Text.Json;

internal static class Program
{
    internal static void Need(bool value) { if (!value) throw new InvalidOperationException("driver-queue-control"); }
    private static void Graft(string source, string rewriter, string output, string mode)
    {
        using var from = ModuleDefinition.ReadModule(source);
        using var target = ModuleDefinition.ReadModule(typeof(Program).Assembly.Location);
        var original = from.GetTypes().Single(t => t.FullName == "System.Threading.TimerQueue");
        var identity = System.Reflection.Assembly.LoadFrom(rewriter).GetType("TaskWait")!
            .GetMethod("BodyIdentity", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic)!;
        string Body(MethodDefinition method) => (string)identity.Invoke(null, new object[] { method, 0 })!;
        var selected = original.Methods.Single(m => m.Name == "SetNextTimer");
        Need(Body(selected) == "52444cc85ffc852a6263e8eea04eca300a98de18f36e1f472d43bfaf80c8aabe");
        if (mode == "old")
        {
            // Exact test-only inverse of the reviewed private option selection.
            // Source/rewriter inputs are read-only; no historical receipt is made.
            var call = selected.Body.Instructions.Single(i => i.Operand is MethodReference m && m.Name == "ContinueWith");
            Need(call.Operand is MethodReference current && current.Parameters.Count == 5 &&
                call.Previous.Operand is MethodReference scheduler && scheduler.Name == "get_Default" &&
                call.Previous.Previous.OpCode == OpCodes.Ldc_I4 && (int)call.Previous.Previous.Operand == 0x40000 &&
                call.Previous.Previous.Previous.Operand is MethodReference token && token.Name == "get_None" &&
                token.DeclaringType.FullName == "System.Threading.CancellationToken");
            var options = call.Previous.Previous; var none = options.Previous;
            selected.Body.Instructions.Remove(options); selected.Body.Instructions.Remove(none);
            call.Operand = from.GetTypes().Single(t => t.FullName == "System.Threading.Tasks.Task").Methods.Single(m =>
                m.Name == "ContinueWith" && m.Parameters.Count == 3 &&
                m.Parameters[0].ParameterType.FullName == "System.Action`2<System.Threading.Tasks.Task,System.Object>" &&
                m.Parameters[1].ParameterType.MetadataType == MetadataType.Object &&
                m.Parameters[2].ParameterType.FullName == "System.Threading.Tasks.TaskScheduler");
            Need(Body(selected) == "caf5877560c8575fb600594a3e612af0bff01bb4ee2808632854c87169fa14cd");
        }
        else Need(mode == "new");
        var queue = target.GetTypes().Single(t => t.FullName == "Queue");
        var state = original.NestedTypes.Single(t => t.Name == "LsfTimerDriverState");
        var mappedState = queue.NestedTypes.Single(t => t.Name == "LsfTimerDriverState");
        var pollable = target.GetTypes().Single(t => t.FullName == "Pollable");
        string[] names = ["SetNextTimer", "LsfTimerDriverToken", "LsfTimerDriverRegister", "LsfTimerDriverCallback", "LsfTimerDriverRetireIfIdle"];
        TypeReference Type(TypeReference type) => type.FullName == original.FullName ? queue
            : type.FullName == state.FullName ? mappedState
            : type.FullName.EndsWith("IPoll/Pollable", StringComparison.Ordinal) ? pollable
            : type is ArrayType array ? new ArrayType(Type(array.ElementType))
            : type is GenericInstanceType generic ? Generic(generic) : target.ImportReference(type);
        TypeReference Generic(GenericInstanceType originalType)
        {
            var copy = new GenericInstanceType(target.ImportReference(originalType.ElementType));
            foreach (var parameter in originalType.GenericArguments) copy.GenericArguments.Add(Type(parameter));
            return copy;
        }
        MethodReference Method(MethodReference method)
        {
            if (method.DeclaringType.FullName == original.FullName)
                return queue.Methods.Single(m => m.Name == method.Name && m.Parameters.Count == method.Parameters.Count);
            if (method.DeclaringType.FullName == state.FullName)
                return mappedState.Methods.Single(m => m.Name == method.Name && m.Parameters.Count == method.Parameters.Count);
            if (method.DeclaringType.FullName == "System.Threading.Timer" && method.Name == "get_ActiveCount")
                return queue.Methods.Single(m => m.Name == "ActiveCount");
            if (method.Name is "SubscribeDuration" or "RegisterWasiPollable")
                return queue.Methods.Single(m => m.Name == method.Name);
            if (method.DeclaringType.FullName == "System.Threading.Tasks.TaskScheduler" && method.Name == "get_Default")
                return queue.Methods.Single(m => m.Name == "DefaultScheduler");
            if (method.DeclaringType is GenericInstanceType list && list.GenericArguments.Any(t => t.FullName == original.FullName))
            {
                var copy = new MethodReference(method.Name, Type(method.ReturnType), Type(method.DeclaringType)) {
                    HasThis = method.HasThis, ExplicitThis = method.ExplicitThis, CallingConvention = method.CallingConvention };
                foreach (var parameter in method.Parameters) copy.Parameters.Add(new ParameterDefinition(Type(parameter.ParameterType)));
                return copy;
            }
            return target.ImportReference(method);
        }
        foreach (var name in names)
        {
            var actual = original.Methods.Single(m => m.Name == name);
            var copied = queue.Methods.Single(m => m.Name == name);
            copied.Body = new MethodBody(copied) { InitLocals = actual.Body.InitLocals, MaxStackSize = actual.Body.MaxStackSize };
            var variables = actual.Body.Variables.ToDictionary(v => v, v => new VariableDefinition(Type(v.VariableType)));
            foreach (var variable in variables.Values) copied.Body.Variables.Add(variable);
            var rows = actual.Body.Instructions.ToDictionary(i => i, _ => Instruction.Create(OpCodes.Nop));
            foreach (var instruction in actual.Body.Instructions)
            {
                var copy = rows[instruction]; copy.OpCode = instruction.OpCode;
                copy.Operand = instruction.Operand switch {
                    Instruction branch => rows[branch], Instruction[] branches => branches.Select(b => rows[b]).ToArray(),
                    VariableDefinition variable => variables[variable], ParameterDefinition parameter => copied.Parameters[parameter.Index],
                    MethodReference method => Method(method),
                    FieldReference field => (field.DeclaringType.FullName == state.FullName ? mappedState : queue).Fields.Single(f => f.Name == field.Name),
                    TypeReference type => Type(type), null or string or int or long => instruction.Operand,
                    _ => throw new InvalidDataException("closed-driver-copy-operand"),
                };
                copied.Body.Instructions.Add(copy);
            }
            foreach (var handler in actual.Body.ExceptionHandlers)
                copied.Body.ExceptionHandlers.Add(new ExceptionHandler(handler.HandlerType) {
                    TryStart = rows[handler.TryStart], TryEnd = handler.TryEnd is null ? null : rows[handler.TryEnd],
                    HandlerStart = rows[handler.HandlerStart], HandlerEnd = handler.HandlerEnd is null ? null : rows[handler.HandlerEnd],
                    CatchType = handler.CatchType is null ? null : Type(handler.CatchType),
                });
        }
        Directory.CreateDirectory(output); target.Write(Path.Combine(output, "Control.dll"));
        foreach (var name in new[] { "Control.runtimeconfig.json", "Control.deps.json", "Mono.Cecil.dll" })
            File.Copy(Path.Combine(Path.GetDirectoryName(typeof(Program).Assembly.Location)!, name), Path.Combine(output, name));
        Console.WriteLine(JsonSerializer.Serialize(new { copiedActualDriverMethods = names, testOnlyOriginalOptionProjection = mode == "old", guestQualified = false }));
    }

    private static void Main(string[] args)
    {
        if (args is ["graft", var source, var rewriter, var output, var variant]) { Graft(source, rewriter, output, variant); return; }
        Need(args.Length == 2 && args[0] == "execute"); string mode = args[1];
        Queue.Active = 1; Queue.SetNextTimer(200, 100);
        Need(Queue.Scheduler.Count == 1 && Queue.Driver is { Task.IsCompleted: false });
        bool requiredRan = false;
        if (mode is "old" or "new")
        {
            // FireNextTimers calls EnsureTimerFiresBy before inline Fire. Its
            // new poll-check remains genuinely queued while the second callback
            // disables the timer. The copied idle retirement cancels that wait.
            Queue.Active = 0; Queue.LsfTimerDriverRetireIfIdle();
            int afterCancellation = Queue.Scheduler.Count;
            var disposed = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var required = disposed.Task.ContinueWith(_ => requiredRan = true, CancellationToken.None,
                TaskContinuationOptions.None, Queue.Scheduler);
            disposed.SetResult();
            Need(Queue.Scheduler.Count == 2 && Queue.Scheduler.Maximum == 2);
            if (mode == "old") Need(afterCancellation == 2 && Queue.Scheduler.Refused == 1 && required.IsFaulted);
            else Need(afterCancellation == 1 && Queue.Scheduler.Refused == 0 && !required.IsCompleted);
            Queue.Scheduler.Drain(); Need(requiredRan == (mode == "new") && Queue.Handled == 0);
            int refused = Queue.Scheduler.Refused;
            // A genuine third queued entry still refuses, then the same two-slot
            // profile accepts fresh work after the actual dequeue releases it.
            var first = new Task(() => { }); var second = new Task(() => { }); var third = new Task(() => { });
            first.Start(Queue.Scheduler); second.Start(Queue.Scheduler);
            try { third.Start(Queue.Scheduler); } catch (TaskSchedulerException) { }
            Need(Queue.Scheduler.Count == 2 && Queue.Scheduler.Refused == refused + 1);
            Queue.Scheduler.Step(); new Task(() => { }).Start(Queue.Scheduler); Queue.Scheduler.Drain();
            Console.WriteLine(JsonSerializer.Serialize(new { passed = true, mode, afterCancellation,
                requiredContinuationRan = requiredRan, actualQueuedCeiling = 2, maximumQueued = Queue.Scheduler.Maximum,
                originalCapacityRefusal = mode == "old", threeRealEntriesStillRefused = true, freshSameBudget = true,
                guestQualified = false, queueAndNativeImports = "explicit-test-ports", trace = Queue.Scheduler.Trace }));
        }
        else
        {
            Queue.Scheduler.Step(); Need(Queue.Scheduler.Count == 0);
            var driver = Queue.Driver!;
            if (mode == "success") driver.SetResult();
            else if (mode == "fault") driver.SetException(new IOException("fixed-public-port-fault"));
            else throw new InvalidOperationException("control-mode");
            Need(Queue.Scheduler.Count == 1); var actual = Queue.Scheduler.Step();
            Need(mode == "success" ? actual.IsCompletedSuccessfully && Queue.Handled == 1
                : actual.IsFaulted && actual.Exception!.InnerException is InvalidOperationException { Message: "activation-timer-driver-completion" } && Queue.Handled == 0);
            Console.WriteLine(JsonSerializer.Serialize(new { passed = true, mode, originalCompletionPath = true,
                guestQualified = false, actualQueuedCeiling = 2 }));
        }
    }
}

internal sealed class Pollable { }
internal sealed class BoundedScheduler : TaskScheduler
{
    private readonly Queue<Task> entries = new();
    internal int Count => entries.Count;
    internal int Maximum, Refused;
    internal readonly List<string> Trace = new();
    protected override void QueueTask(Task task)
    {
        if (Count >= 2) { Refused++; Trace.Add("refused:2"); throw new InvalidOperationException("queued-owner-limit"); }
        entries.Enqueue(task); Maximum = Math.Max(Maximum, Count); Trace.Add("enqueued:" + Count);
    }
    protected override bool TryExecuteTaskInline(Task task, bool queued) => false;
    protected override IEnumerable<Task> GetScheduledTasks() => entries;
    internal Task Step()
    {
        var task = entries.Dequeue(); Trace.Add("dequeued:" + Count);
        Program.Need(TryExecuteTask(task)); return task;
    }
    internal void Drain() { while (Count != 0) Step(); }
}
internal sealed class Queue
{
    internal static long s_shortestDueTimeMs = long.MaxValue, s_lsfTimerDriverEpoch;
    internal static CancellationTokenSource? s_lsfTimerDriverCancellation;
    internal bool _isTimerScheduled, _isScheduled;
    internal long _scheduledDueTimeMs;
    internal static List<Queue>? s_scheduledTimers = new(), s_scheduledTimersToFire = new();
    internal static readonly Queue[] Instances = [new()];
    internal static readonly BoundedScheduler Scheduler = new();
    internal static TaskCompletionSource? Driver;
    internal static int Active, Handled;
    internal static long ActiveCount() => Active;
    internal static Queue[] get_Instances() => Instances;
    internal static TaskScheduler DefaultScheduler() => Scheduler;
    internal static Pollable SubscribeDuration(ulong delay) { Program.Need(delay == 100000000); return new(); }
    internal static Task RegisterWasiPollable(Pollable pollable, bool owns, CancellationToken token)
    {
        Program.Need(owns && ExecutionContext.IsFlowSuppressed());
        Driver = new TaskCompletionSource(new object()); var source = Driver;
        token.Register(() => source.TrySetCanceled(token));
        new Task(() => { }).Start(Scheduler); return source.Task;
    }
    internal static void TimerHandler(object state) { Handled++; }
    internal static void SetNextTimer(long next, long now) => throw new InvalidOperationException("ungrafted");
    internal static CancellationToken LsfTimerDriverToken() => throw new InvalidOperationException("ungrafted");
    internal static Task LsfTimerDriverRegister(Pollable p, bool owns, CancellationToken token) => throw new InvalidOperationException("ungrafted");
    internal static void LsfTimerDriverCallback(Task task, object state) => throw new InvalidOperationException("ungrafted");
    internal static void LsfTimerDriverRetireIfIdle() => throw new InvalidOperationException("ungrafted");
    internal sealed class LsfTimerDriverState
    {
        internal Task Task; internal long Epoch;
        internal LsfTimerDriverState(Task task, long epoch) { Task = task; Epoch = epoch; }
    }
}
