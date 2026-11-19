using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Reflection;

// Only the operating-system predicate, dispatcher, clock and private
// IsDisposed getter are host ports. No NativeAOT component or host ledger runs.
public static class ManualResetEventProjection
{
    public static ManualResetEventSlim? Target;
    public static CancellationToken Token;
    public static long Start;
    public static int Timeout;
    public static bool Observed;
    public static Task? Current;
    public static int Depth;
    public static readonly ExecutionContext Default = (ExecutionContext)typeof(ExecutionContext)
        .GetField("Default", BindingFlags.Static | BindingFlags.NonPublic)!.GetValue(null)!;
    private static readonly Func<ManualResetEventSlim, bool> IsDisposed = typeof(ManualResetEventSlim)
        .GetProperty("IsDisposed", BindingFlags.Instance | BindingFlags.NonPublic)!.GetMethod!
        .CreateDelegate<Func<ManualResetEventSlim, bool>>();
    private static readonly Queue<Action> Queue = new();
    public static int Owners;
    public static int Running;
    public static int Settled;
    public static int Dispatches;
    public static Exception? ReadinessFailure;
    public static bool WasiMode = true;

    public static bool Wasi() => WasiMode;
    public static bool Disposed(ManualResetEventSlim value) => IsDisposed(value);
    public static void RunDefault(ExecutionContext context, ContextCallback callback, object? state)
        => ExecutionContext.Run(context, callback, state);
    public static long Remaining(long start, long timeout) => Math.Max(0, timeout - (Environment.TickCount64 - start));
    public static CancellationTokenSource NoLinkedSource(CancellationToken token)
        => throw new InvalidOperationException("unexpected-linked-source");
    public static Task NoDelay(int milliseconds, CancellationToken token)
        => throw new InvalidOperationException("unexpected-timer");
    public static void EnsureReady()
    {
        if (ReadinessFailure is not null) throw ReadinessFailure;
        if (Queue.Count == 0) throw new InvalidOperationException("no-accepted-work");
    }
    public static void Submit(Action action) { Owners++; Queue.Enqueue(action); }
    public static bool Dispatch()
    {
        var action = Queue.Dequeue();
        Dispatches++; Running++;
        try { action(); }
        finally { Running--; Owners--; Settled++; }
        return true;
    }

    public static bool WaitCore(ManualResetEventSlim value, int milliseconds, CancellationToken token)
        => throw new NotImplementedException();
    public static void WaitSimple(ManualResetEventSlim value) => throw new NotImplementedException();
    public static bool Shim(ManualResetEventSlim value, int milliseconds, CancellationToken token)
        => throw new NotImplementedException();
    public static bool Entry(ManualResetEventSlim value, int milliseconds, CancellationToken token)
        => throw new NotImplementedException();
    public static void WaitDispatch(object? state) => throw new NotImplementedException();
}

internal static class ManualResetEventControl
{
    private static void Require(bool value, string reason)
    {
        if (!value) throw new InvalidOperationException(reason);
    }

    // Copy the emitted selection and the original validation/guard prefix. The
    // non-WASI branch maps to the original CLR Wait; the producer separately
    // checks that the complete pinned non-WASI remainder is unchanged.
    private static void CopyWaitPrefix(MethodDefinition source, MethodDefinition target, ModuleDefinition module,
        Dictionary<string, MethodDefinition> methods)
    {
        var guards = source.Body.Instructions.Where(instruction => instruction.OpCode == OpCodes.Call
            && instruction.Operand is MethodReference method
            && method.FullName == "System.Boolean System.OperatingSystem::IsWasi()").ToArray();
        Require(guards.Length == 2 && guards[1].Next.OpCode == OpCodes.Brfalse_S
            && guards[1].Next.Next.OpCode == OpCodes.Newobj && guards[1].Next.Next.Next.OpCode == OpCodes.Throw,
            "event-guard-shape");
        var originalFallback = (Instruction)guards[1].Next.Operand;
        var selected = source.Body.Instructions.TakeWhile(instruction => instruction != originalFallback).ToArray();
        Require(selected.Length > 15 && selected.Contains(guards[0]) && selected.Contains(guards[1]), "event-prefix-shape");
        target.Body = new Mono.Cecil.Cil.MethodBody(target) { InitLocals = source.Body.InitLocals, MaxStackSize = source.Body.MaxStackSize };
        var body = target.Body;
        var copies = selected.ToDictionary(instruction => instruction, _ => Instruction.Create(OpCodes.Nop));
        var fallback = Instruction.Create(OpCodes.Ldarg_0);
        object? Operand(object? value, Instruction origin) => value switch {
            null => null,
            Instruction when origin == guards[0].Next => fallback,
            Instruction instruction when instruction == originalFallback => fallback,
            Instruction instruction => copies[instruction],
            ParameterDefinition parameter => target.Parameters[parameter.Index + 1],
            MethodReference method when methods.TryGetValue(method.FullName, out var replacement) => replacement,
            MethodReference method => module.ImportReference(method),
            TypeReference type => module.ImportReference(type),
            _ => value,
        };
        foreach (var instruction in selected)
        {
            var copy = copies[instruction];
            copy.OpCode = instruction.OpCode;
            copy.Operand = Operand(instruction.Operand, instruction);
            body.Instructions.Add(copy);
        }
        body.Instructions.Add(fallback);
        body.Instructions.Add(Instruction.Create(OpCodes.Ldarg_1));
        body.Instructions.Add(Instruction.Create(OpCodes.Ldarg_2));
        body.Instructions.Add(Instruction.Create(OpCodes.Callvirt, module.ImportReference(
            typeof(ManualResetEventSlim).GetMethod(nameof(ManualResetEventSlim.Wait), [typeof(int), typeof(CancellationToken)])!)));
        body.Instructions.Add(Instruction.Create(OpCodes.Ret));
    }

    private static Type BuildProjection(string assembly, string output)
    {
        using var actual = ModuleDefinition.ReadModule(assembly);
        using var projected = ModuleDefinition.ReadModule(Assembly.GetExecutingAssembly().Location);
        var loop = actual.Types.Single(type => type.FullName == "System.Threading.WasiEventLoop");
        var mres = actual.Types.Single(type => type.FullName == "System.Threading.ManualResetEventSlim");
        var context = actual.Types.Single(type => type.FullName == "System.Threading.ExecutionContext");
        var target = projected.Types.Single(type => type.FullName == nameof(ManualResetEventProjection));
        var simple = mres.Methods.Single(method => method.Name == "Wait" && method.Parameters.Count == 0);
        var wait = mres.Methods.Single(method => method.Name == "Wait" && method.Parameters.Count == 2
            && method.Parameters[0].ParameterType.MetadataType == MetadataType.Int32);
        var shim = Program.Method(mres, "LsfAggregateWait");
        var entry = Program.Method(loop, "LsfAggregateWait");
        var dispatch = Program.Method(loop, "LsfAggregateDispatch");
        var methods = new Dictionary<string, MethodDefinition> {
            [simple.FullName] = Program.Method(target, "WaitSimple"),
            [wait.FullName] = Program.Method(target, "WaitCore"),
            [shim.FullName] = Program.Method(target, "Shim"),
            [entry.FullName] = Program.Method(target, "Entry"),
            [dispatch.FullName] = Program.Method(target, "WaitDispatch"),
        };
        var references = wait.Body.Instructions.Concat(shim.Body.Instructions)
            .Concat(entry.Body.Instructions).Concat(dispatch.Body.Instructions)
            .Select(instruction => instruction.Operand).OfType<MethodReference>().ToArray();
        void Bind(string owner, string name, string replacement)
        {
            var matches = references.Where(method => method.DeclaringType.FullName == owner && method.Name == name)
                .Select(method => method.FullName).Distinct().ToArray();
            Require(matches.Length == 1, "event-reference-" + name);
            methods[matches[0]] = Program.Method(target, replacement);
        }
        Bind("System.OperatingSystem", "IsWasi", "Wasi");
        Bind("System.Threading.ManualResetEventSlim", "get_IsDisposed", "Disposed");
        Bind("System.Threading.ExecutionContext", "RunInternal", "RunDefault");
        Bind("System.Threading.TimeoutHelper", "UpdateTimeOut", "Remaining");
        Bind("Lsf.CompilerOwned.ManagedWorkRuntime", "EnsureJoinReady", "EnsureReady");
        Bind("System.Threading.ThreadPoolWorkQueue", "Dispatch", "Dispatch");
        Bind("System.Threading.CancellationTokenSource", "CreateLinkedTokenSource", "NoLinkedSource");
        Bind("System.Threading.Tasks.Task", "Delay", "NoDelay");
        var fields = new Dictionary<string, FieldDefinition>();
        foreach (var (original, replacement) in new[] { ("s_mainTask", "Current"), ("s_lsfTaskWaitDepth", "Depth"),
                     ("s_lsfAggregateTarget", "Target"), ("s_lsfAggregateToken", "Token"), ("s_lsfAggregateStart", "Start"),
                     ("s_lsfAggregateTimeout", "Timeout"), ("s_lsfAggregateCompleted", "Observed") })
            fields[loop.Fields.Single(field => field.Name == original).FullName] = target.Fields.Single(field => field.Name == replacement);
        fields[context.Fields.Single(field => field.Name == "Default").FullName] = target.Fields.Single(field => field.Name == "Default");
        CopyWaitPrefix(wait, Program.Method(target, "WaitCore"), projected, methods);
        foreach (var (source, name) in new[] { (simple, "WaitSimple"), (shim, "Shim"),
                     (entry, "Entry"), (dispatch, "WaitDispatch") })
            Program.CopyBody(source, Program.Method(target, name), projected, methods, fields);
        projected.Assembly.Name.Name = "ManualResetEventHostProjection";
        projected.Name = "ManualResetEventHostProjection.dll";
        Require(!File.Exists(output), "event-projection-output-exists");
        projected.Write(output);
        return Assembly.LoadFile(Path.GetFullPath(output)).GetType(nameof(ManualResetEventProjection), true)!;
    }

    private static void CheckProjection(Type projection)
    {
        var wait = projection.GetMethod("WaitCore")!.CreateDelegate<Func<ManualResetEventSlim, int, CancellationToken, bool>>();
        var simple = projection.GetMethod("WaitSimple")!.CreateDelegate<Action<ManualResetEventSlim>>();
        var submit = projection.GetMethod("Submit")!.CreateDelegate<Action<Action>>();
        var target = projection.GetField("Target")!;
        var current = projection.GetField("Current")!;
        var depth = projection.GetField("Depth")!;
        var owners = projection.GetField("Owners")!;
        var running = projection.GetField("Running")!;
        var settled = projection.GetField("Settled")!;
        var dispatches = projection.GetField("Dispatches")!;
        var readinessFailure = projection.GetField("ReadinessFailure")!;
        var wasiMode = projection.GetField("WasiMode")!;
        using var priorTarget = new ManualResetEventSlim(false);
        using var value = new ManualResetEventSlim(false);
        var priorTask = new TaskCompletionSource<int>().Task;
        target.SetValue(null, priorTarget); current.SetValue(null, priorTask); depth.SetValue(null, 4);
        void Restored() => Require(ReferenceEquals(target.GetValue(null), priorTarget)
            && ReferenceEquals(current.GetValue(null), priorTask) && (int)depth.GetValue(null)! == 4, "event-frame-restored");

        wasiMode.SetValue(null, false);
        Require(!wait(value, 0, CancellationToken.None), "non-wasi-zero-unsignalled");
        value.Set(); Require(wait(value, 0, CancellationToken.None), "non-wasi-zero-signalled");
        simple(value); value.Reset();
        Require((int)dispatches.GetValue(null)! == 0, "non-wasi-dispatch");
        wasiMode.SetValue(null, true);
        Require(!wait(value, 0, CancellationToken.None), "zero-unsignalled");
        value.Set(); Require(wait(value, 0, CancellationToken.None), "zero-signalled");
        depth.SetValue(null, 32);
        simple(value);
        Require((int)depth.GetValue(null)! == 32 && ReferenceEquals(target.GetValue(null), priorTarget), "signalled-at-depth-limit");
        depth.SetValue(null, 4);
        simple(value); value.Reset(); Require(!wait(value, 0, CancellationToken.None), "zero-reset");
        Require((int)owners.GetValue(null)! == 0 && (int)dispatches.GetValue(null)! == 0, "zero-no-admission");
        Restored();
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        try { wait(value, 0, cancelled.Token); throw new InvalidOperationException("zero-cancel-not-thrown"); }
        catch (OperationCanceledException error) { Require(error.CancellationToken == cancelled.Token, "zero-cancel-token"); }
        try { wait(value, -2, cancelled.Token); throw new InvalidOperationException("cancel-order-not-thrown"); }
        catch (OperationCanceledException error) { Require(error.CancellationToken == cancelled.Token, "cancel-before-range"); }
        try { wait(value, -2, CancellationToken.None); throw new InvalidOperationException("range-not-thrown"); }
        catch (ArgumentOutOfRangeException error) { Require(error.ParamName == "millisecondsTimeout", "range-name"); }
        using var disposed = new ManualResetEventSlim(false); disposed.Dispose();
        try { wait(disposed, 0, cancelled.Token); throw new InvalidOperationException("disposed-not-thrown"); }
        catch (ObjectDisposedException) { }
        try { simple(disposed); throw new InvalidOperationException("simple-disposed-not-thrown"); }
        catch (ObjectDisposedException) { }
        try { wait(value, 1, CancellationToken.None); throw new InvalidOperationException("positive-timeout-supported"); }
        catch (PlatformNotSupportedException) { }
        using var cancellable = new CancellationTokenSource();
        try { wait(value, -1, cancellable.Token); throw new InvalidOperationException("cancellable-infinite-supported"); }
        catch (PlatformNotSupportedException) { }
        value.Set();
        Require(wait(value, 0, cancellable.Token), "zero-cancellable-signalled");
        try { wait(value, 1, CancellationToken.None); throw new InvalidOperationException("signalled-positive-timeout-supported"); }
        catch (PlatformNotSupportedException) { }
        value.Reset();
        depth.SetValue(null, 32);
        try { simple(value); throw new InvalidOperationException("depth-limit-not-thrown"); }
        catch (InvalidOperationException error) { Require(error.Message == "activation-task-wait-depth-limit", "event-depth-limit"); }
        Require((int)depth.GetValue(null)! == 32 && ReferenceEquals(target.GetValue(null), priorTarget)
            && (int)owners.GetValue(null)! == 0, "event-depth-preserves-frame");
        depth.SetValue(null, 4);

        submit(() => {
            Require(ReferenceEquals(target.GetValue(null), value) && (int)depth.GetValue(null)! == 5
                && (int)owners.GetValue(null)! == 1 && (int)running.GetValue(null)! == 1, "event-running-custody");
            value.Set();
        });
        simple(value);
        Require(value.IsSet && (int)owners.GetValue(null)! == 0 && (int)settled.GetValue(null)! == 1,
            "event-signal-and-settlement");
        Restored();
        value.Reset();
        using var inner = new ManualResetEventSlim(false);
        submit(() => {
            Require(ReferenceEquals(target.GetValue(null), value) && (int)owners.GetValue(null)! == 2, "outer-event-owner");
            simple(inner);
            Require(inner.IsSet && ReferenceEquals(target.GetValue(null), value)
                && (int)depth.GetValue(null)! == 5 && (int)owners.GetValue(null)! == 1, "nested-event-restored");
            value.Set();
        });
        submit(() => {
            Require(ReferenceEquals(target.GetValue(null), inner) && (int)depth.GetValue(null)! == 6
                && (int)owners.GetValue(null)! == 2 && (int)running.GetValue(null)! == 2, "inner-event-custody");
            inner.Set();
        });
        simple(value);
        Require(value.IsSet && (int)owners.GetValue(null)! == 0 && (int)settled.GetValue(null)! == 3,
            "nested-event-settlement");
        Restored();

        value.Reset();
        submit(() => value.Set());
        var failure = new InvalidOperationException("readiness-primary");
        readinessFailure.SetValue(null, failure);
        try { simple(value); throw new InvalidOperationException("readiness-not-thrown"); }
        catch (InvalidOperationException error) { Require(ReferenceEquals(error, failure), "readiness-primary-changed"); }
        Require(!value.IsSet && (int)owners.GetValue(null)! == 1 && (int)settled.GetValue(null)! == 3,
            "refused-event-owner-lost");
        Restored();
        readinessFailure.SetValue(null, null);
        simple(value);
        Require(value.IsSet && (int)owners.GetValue(null)! == 0 && (int)settled.GetValue(null)! == 4,
            "refused-event-retry-settlement");
        Restored();
    }

    private static void CheckClrContext()
    {
        // Observe a blocked waiter, not a race between Task.Run(Set) and Wait.
        // Suppress flow into this reference thread so its bootstrap/teardown
        // cannot contribute notifications from the test runner's context.
        using var signal = new ManualResetEventSlim(false, 0);
        int entered = 0, notifications = 0;
        Exception? failure = null;
        var waiter = new Thread(() => {
            bool measuring = false;
            var local = new AsyncLocal<int>(change => {
                if (measuring && change.ThreadContextChanged) Interlocked.Increment(ref notifications);
            });
            local.Value = 7;
            try {
                measuring = true;
                Volatile.Write(ref entered, 1);
                signal.Wait();
                Require(local.Value == 7, "clr-event-context-value");
            }
            catch (Exception error) { failure = error; }
            finally { measuring = false; local.Value = 0; }
        }) { IsBackground = true };
        if (ExecutionContext.IsFlowSuppressed()) waiter.Start();
        else { using (ExecutionContext.SuppressFlow()) waiter.Start(); }
        try {
            Require(SpinWait.SpinUntil(() => Volatile.Read(ref entered) == 1
                && (waiter.ThreadState & System.Threading.ThreadState.WaitSleepJoin) != 0, 10000),
                "clr-event-waiter-not-observed-blocked");
            Require(!signal.IsSet, "clr-event-signal-before-observation");
        }
        finally {
            signal.Set();
            Require(waiter.Join(10000), "clr-event-waiter-not-reaped");
        }
        if (failure is not null) System.Runtime.ExceptionServices.ExceptionDispatchInfo.Capture(failure).Throw();
        Require(notifications == 0, "clr-event-context-notifications");
    }

    private static void CheckPendingContext(Type projection)
    {
        var simple = projection.GetMethod("WaitSimple")!.CreateDelegate<Action<ManualResetEventSlim>>();
        var timed = projection.GetMethod("WaitCore")!.CreateDelegate<Func<ManualResetEventSlim, int, CancellationToken, bool>>();
        var submit = projection.GetMethod("Submit")!.CreateDelegate<Action<Action>>();
        var owners = projection.GetField("Owners")!;
        var running = projection.GetField("Running")!;
        var settled = projection.GetField("Settled")!;
        var dispatches = projection.GetField("Dispatches")!;
        var readinessFailure = projection.GetField("ReadinessFailure")!;
        var frame = new[] { "Target", "Token", "Start", "Timeout", "Observed", "Current", "Depth" }
            .Select(name => projection.GetField(name)!).ToArray();
        var waits = new Dictionary<string, Action<ManualResetEventSlim>> {
            ["simple"] = simple,
            ["infinite"] = value => Require(timed(value, -1, CancellationToken.None), "event-infinite-result"),
        };
        var failures = new List<string>();
        foreach (var (name, wait) in waits)
        foreach (bool refuse in new[] { false, true })
        {
            string label = name + (refuse ? "-refusal-retry" : "-signal");
            using var signal = new ManualResetEventSlim(false);
            var changes = new List<string>();
            bool measuring = false;
            var local = new AsyncLocal<int>(change => {
                // Do not throw from this callback: record the evidence and
                // assert it only after the wait and owner cleanup have finished.
                if (measuring && change.ThreadContextChanged)
                    changes.Add(change.PreviousValue + "->" + change.CurrentValue);
            });
            var saved = frame.Select(field => field.GetValue(null)).ToArray();
            int beforeDispatches = (int)dispatches.GetValue(null)!;
            int beforeSettled = (int)settled.GetValue(null)!;
            int workerValue = -1;
            bool suppressed = ExecutionContext.IsFlowSuppressed();
            Require((int)owners.GetValue(null)! == 0 && (int)running.GetValue(null)! == 0,
                "event-context-initial-owners");
            void Restored()
            {
                Require(local.Value == 7 && ExecutionContext.IsFlowSuppressed() == suppressed,
                    "event-context-caller-state-" + label);
                for (int index = 0; index < frame.Length; index++)
                    Require(Equals(frame[index].GetValue(null), saved[index]),
                        "event-context-frame-" + frame[index].Name + "-" + label);
            }
            void Observe(string phase)
            {
                if (changes.Count != 0)
                    failures.Add(label + "-" + phase + ":" + string.Join(",", changes));
                changes.Clear();
            }
            local.Value = 7;
            try {
                measuring = true;
                ExecutionContext.Run(ManualResetEventProjection.Default, _ => { }, null);
                Require(changes.SequenceEqual(new[] { "7->0", "0->7" }), "event-context-observer-control");
                changes.Clear();
                // The projection's queue never runs inline and does not capture
                // ExecutionContext. This also rejects a fix that simply runs
                // the dispatcher inside the waiting caller's context.
                submit(() => { workerValue = local.Value; signal.Set(); });
                Require(!signal.IsSet && (int)dispatches.GetValue(null)! == beforeDispatches,
                    "event-context-not-pending-" + label);
                if (refuse)
                {
                    var primary = new InvalidOperationException("event-context-readiness-primary");
                    readinessFailure.SetValue(null, primary);
                    try { wait(signal); throw new InvalidOperationException("event-context-refusal-not-thrown"); }
                    catch (InvalidOperationException error) {
                        Require(ReferenceEquals(error, primary), "event-context-primary-changed");
                    }
                    finally { readinessFailure.SetValue(null, null); }
                    Require(!signal.IsSet && (int)owners.GetValue(null)! == 1
                        && (int)running.GetValue(null)! == 0
                        && (int)settled.GetValue(null)! == beforeSettled
                        && (int)dispatches.GetValue(null)! == beforeDispatches,
                        "event-context-refused-owner-lost");
                    Restored(); Observe("refused");
                }
                wait(signal);
                Require(signal.IsSet && (int)owners.GetValue(null)! == 0
                    && (int)running.GetValue(null)! == 0
                    && (int)settled.GetValue(null)! == beforeSettled + 1
                    && (int)dispatches.GetValue(null)! == beforeDispatches + 1,
                    "event-context-owner-settlement-" + label);
                Restored(); Observe("returned");
                if (workerValue != 0) failures.Add(label + "-caller-context-leaked:" + workerValue);
            }
            finally { measuring = false; local.Value = 0; readinessFailure.SetValue(null, null); }
        }
        Require(failures.Count == 0, "event-wait-context-mismatch:" + string.Join(";", failures));
    }

    internal static void Run(string assembly, string output)
    {
        CheckClrContext();
        var projection = BuildProjection(assembly, output);
        CheckProjection(projection);
        CheckPendingContext(projection);
        Console.WriteLine("MANUAL_RESET_EVENT_IL_HOST PASS clr;zero;validation;signal;reset;nested;owners;refusal");
    }
}
