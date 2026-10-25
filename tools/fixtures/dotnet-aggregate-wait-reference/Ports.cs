using System.Threading;
using System.Reflection;
using System.Runtime.ExceptionServices;
using Mono.Cecil;

// Explicit HOST-REFERENCE ports. These are never copied into a guest/CoreLib.
// Real CLR Tasks, MRES, tokens and ExecutionContext remain in use; this queue
// does not qualify the WASI dispatcher, readiness provider or native ledger.
internal static class Ports
{
    public static Task? s_mainTask;
    public static int s_lsfTaskWaitDepth;
    public static ManualResetEventSlim? s_lsfAggregateTarget;
    public static CancellationToken s_lsfAggregateToken;
    public static long s_lsfAggregateStart;
    public static int s_lsfAggregateTimeout;
    public static bool s_lsfAggregateCompleted;
    internal static readonly Queue<Action> Work = new();
    internal static Action<object?> AggregateBody = null!;
    internal static Action<object?> SingleBody = null!;
    internal static Func<bool> Ready = null!;
    internal static Action? BeforeDispatch;
    internal static Action? AfterDispatch;
    internal static long Now;
    internal static int StartReads;
    internal static int RemainingReads;
    internal static int Dispatches;
    internal static int WakeCalls;
    internal static int LastWakeDuration;
    internal static int CopiedValidationCalls;
    internal static bool Platform = true;
    internal static Exception? DelayFailure;
    internal static ManualResetEventSlim? ObservedTarget;

    public static bool IsWasi() => Platform;
    public static bool CopiedDisposed(ManualResetEventSlim value)
    {
        var getter = typeof(ManualResetEventSlim).GetMethod("get_IsDisposed",
            System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
        ActualCil.Need(getter is not null && !getter.IsStatic && getter.ReturnType == typeof(bool)
            && getter.GetParameters().Length == 0, "host-disposal-getter-shape");
        CopiedValidationCalls++;
        return getter!.CreateDelegate<Func<ManualResetEventSlim, bool>>()(value);
    }
    public static long StartClock() { StartReads++; return Now; }
    public static long RemainingClock() { RemainingReads++; return Now; }
    public static bool Dispatch()
    {
        BeforeDispatch?.Invoke();
        ActualCil.Need(Work.Count != 0, "host-dispatch-no-ready-work");
        Dispatches++; ObservedTarget ??= s_lsfAggregateTarget;
        Work.Dequeue()(); AfterDispatch?.Invoke(); return true;
    }
    public static void EnsureReady() { }
    public static Task Delay(int duration, CancellationToken token)
    {
        WakeCalls++; LastWakeDuration = duration;
        if (DelayFailure is { } error) throw error;
        return Task.Delay(duration, token);
    }
    public static void AggregateBridge(object? state) => AggregateBody(state);
    public static void SingleBridge(object? state) => SingleBody(state);
}

// Closed cleanup-fault port around a REAL CLR linked CTS, not a fake token or
// completion Task. Source instance-call shape stays unchanged in copied IL.
internal sealed class OwnedSource : IDisposable
{
    private readonly CancellationTokenSource source;
    internal static int Births, Cancels, Disposals;
    internal static Exception? CancelFailure, DisposeFailure;
    private OwnedSource(CancellationTokenSource value) { source = value; Births++; }
    public static OwnedSource CreateLinkedTokenSource(CancellationToken token) =>
        new(CancellationTokenSource.CreateLinkedTokenSource(token));
    public CancellationToken Token => source.Token;
    public void Cancel()
    {
        Cancels++; source.Cancel();
        if (CancelFailure is { } error) throw error;
    }
    public void Dispose()
    {
        Disposals++; source.Dispose();
        if (DisposeFailure is { } error) throw error;
    }
}

// Exact reference-only private enum ABI boundary. No exception is constructed
// here: the actual CLR ThrowHelper creates it and its SAME object is rethrown.
internal static class ThrowHelperPorts
{
    internal sealed record Binding(string sourceEnum, string name, int sourceValue, int hostValue);
    private static readonly (string Enum, string Name, int Value)[] Pins = [
        ("System.ExceptionArgument", "tasks", 51),
        ("System.ExceptionArgument", "millisecondsTimeout", 60),
        ("System.ExceptionArgument", "timeout", 62),
        ("System.ExceptionResource", "Task_WaitMulti_NullTask", 47),
    ];
    private static readonly Dictionary<(string Enum, int Value), object> values = new();
    private static readonly Dictionary<string, MethodInfo> methods = new();
    internal static readonly List<Binding> Bindings = new();
    internal static int Invocations;
    internal const string Null = "System.Void System.ThrowHelper::ThrowArgumentNullException(System.ExceptionArgument)";
    internal const string Range = "System.Void System.ThrowHelper::ThrowArgumentOutOfRangeException(System.ExceptionArgument)";
    internal const string Argument = "System.Void System.ThrowHelper::ThrowArgumentException(System.ExceptionResource,System.ExceptionArgument)";

    internal static void Bind(ModuleDefinition module)
    {
        ActualCil.Need(values.Count == 0 && methods.Count == 0, "throw-helper-binding-once");
        var hostTypes = new Dictionary<string, Type>();
        foreach (var name in Pins.Select(pin => pin.Enum).Distinct())
        {
            var source = module.GetTypes().Single(type => type.FullName == name);
            var host = typeof(Task).Assembly.GetType(name, throwOnError: false);
            ActualCil.Need(source.Module == module && source.IsEnum && source.Fields.Count <= 512
                && source.Fields.Single(field => field.Name == "value__").FieldType.FullName == "System.Int32"
                && host is not null && host.IsEnum && Enum.GetUnderlyingType(host) == typeof(int), "throw-helper-enum-shape");
            hostTypes.Add(name, host!);
            var hostMembers = host!.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
            ActualCil.Need(hostMembers.Length is > 0 and <= 512, "throw-helper-host-enum-bound");
            foreach (var pin in Pins.Where(pin => pin.Enum == name))
            {
                var fields = source.Fields.Where(field => field.Name == pin.Name).ToArray();
                ActualCil.Need(fields.Length == 1 && fields[0].IsLiteral && fields[0].IsStatic
                    && fields[0].HasConstant && fields[0].Constant is int number && number == pin.Value
                    && source.Fields.Count(field => field.IsLiteral && field.HasConstant
                        && field.Constant is int value && value == pin.Value) == 1, "throw-helper-source-constant");
                var hostFields = hostMembers.Where(field => field.Name == pin.Name).ToArray();
                ActualCil.Need(hostFields.Length == 1 && hostFields[0].IsLiteral
                    && hostFields[0].FieldType == host && hostFields[0].GetRawConstantValue() is int,
                    "throw-helper-host-constant");
                int hostValue = (int)hostFields[0].GetRawConstantValue()!;
                ActualCil.Need(hostMembers.Count(field => field.IsLiteral && field.GetRawConstantValue() is int number
                    && number == hostValue) == 1, "throw-helper-host-enum-alias");
                ActualCil.Need(values.TryAdd((name, pin.Value), Enum.ToObject(host, hostValue)), "throw-helper-duplicate-constant");
                Bindings.Add(new(name, pin.Name, pin.Value, hostValue));
            }
        }
        var helper = typeof(Task).Assembly.GetType("System.ThrowHelper", throwOnError: false);
        ActualCil.Need(helper is not null, "throw-helper-host-type");
        foreach (var (signature, name, parameters) in new[] {
            (Null, "ThrowArgumentNullException", new[] { hostTypes["System.ExceptionArgument"] }),
            (Range, "ThrowArgumentOutOfRangeException", new[] { hostTypes["System.ExceptionArgument"] }),
            (Argument, "ThrowArgumentException", new[] { hostTypes["System.ExceptionResource"], hostTypes["System.ExceptionArgument"] }),
        })
        {
            var source = module.GetTypes().Single(type => type.FullName == "System.ThrowHelper")
                .Methods.Single(method => method.FullName == signature);
            ActualCil.Need(source.IsStatic && !source.HasGenericParameters && source.ReturnType.FullName == "System.Void"
                && source.CallingConvention == MethodCallingConvention.Default && !source.HasThis && !source.ExplicitThis
                && source.Parameters.Select(parameter => parameter.ParameterType.FullName)
                    .SequenceEqual(parameters.Select(type => type.FullName)), "throw-helper-source-signature");
            var found = helper!.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static)
                .Where(method => method.Name == name && method.IsStatic && !method.IsGenericMethod
                    && method.ReturnType == typeof(void) && method.ReturnParameter.GetRequiredCustomModifiers().Length == 0
                    && method.ReturnParameter.GetOptionalCustomModifiers().Length == 0
                    && method.GetParameters().Select(parameter => parameter.ParameterType).SequenceEqual(parameters)
                    && method.GetParameters().All(parameter => parameter.GetRequiredCustomModifiers().Length == 0
                        && parameter.GetOptionalCustomModifiers().Length == 0)).ToArray();
            ActualCil.Need(found.Length == 1, "throw-helper-host-signature"); methods.Add(signature, found[0]);
        }
        ActualCil.Need(values.Count == 4 && methods.Count == 3, "throw-helper-closed-binding");
    }

    internal static MethodInfo? Port(string signature) => signature switch {
        Null => typeof(ThrowHelperPorts).GetMethod(nameof(NullByName)),
        Range => typeof(ThrowHelperPorts).GetMethod(nameof(RangeByName)),
        Argument => typeof(ThrowHelperPorts).GetMethod(nameof(ArgumentByName)),
        _ => null,
    };
    internal static object MethodBindings() => methods.OrderBy(pair => pair.Key)
        .Select(pair => new { sourceMethod = pair.Key, hostMethod = pair.Value.ReturnType.FullName + " "
            + pair.Value.DeclaringType!.FullName + "::" + pair.Value.Name + "("
            + string.Join(',', pair.Value.GetParameters().Select(parameter => parameter.ParameterType.FullName)) + ")" }).ToArray();
    private static object Value(string name, int value)
    {
        ActualCil.Need(values.TryGetValue((name, value), out var result), "throw-helper-unrecognized-source-enum");
        return result!;
    }
    private static void Invoke(string signature, params object[] arguments)
    {
        Invocations++;
        try { methods[signature].Invoke(null, arguments); }
        catch (TargetInvocationException error) when (error.InnerException is not null)
        { ExceptionDispatchInfo.Capture(error.InnerException).Throw(); }
        ActualCil.Need(false, "real-host-throw-helper-returned");
    }
    public static void NullByName(int argument) => Invoke(Null, Value("System.ExceptionArgument", argument));
    public static void RangeByName(int argument) => Invoke(Range, Value("System.ExceptionArgument", argument));
    public static void ArgumentByName(int resource, int argument) => Invoke(Argument,
        Value("System.ExceptionResource", resource), Value("System.ExceptionArgument", argument));
}
