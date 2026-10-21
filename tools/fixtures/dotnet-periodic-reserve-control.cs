using System.Reflection;
using System.Text.Json;

// Execute the actual generated Reserve bridge. Only the native WIT import and
// Console writer are explicit ports. No native/guest qualification is implied.
internal static class Program
{
    private static void Need(bool value)
    { if (!value) throw new InvalidDataException("periodic-reserve-control"); }
    private sealed class RefusedWriter : TextWriter
    {
        public override System.Text.Encoding Encoding => System.Text.Encoding.UTF8;
        public override void WriteLine(string? value) => throw new IOException("fixed-control-writer-refusal");
    }
    private static int Main(string[] args)
    {
        Need(args.Length == 3);
        int kind = int.Parse(args[0]); uint error = uint.Parse(args[1]); string mode = args[2];
        var method = typeof(LsfManagedWorkRoot).GetMethod("Reserve", BindingFlags.Static | BindingFlags.NonPublic)!;
        var original = Console.Error; using var sink = new StringWriter();
        WIT_OWNER.NativeKind = kind; WIT_OWNER.NativeError = error; WIT_OWNER.Accept = mode == "success";
        Exception? failure = null; object? result = null;
        try
        {
            Console.SetError(mode == "writer-fails" ? new RefusedWriter() : sink);
            try { result = method.Invoke(null, [kind, 19UL, 29UL]); }
            catch (TargetInvocationException wrapped) { failure = wrapped.InnerException; }
        }
        finally { Console.SetError(original); }
        Need(WIT_OWNER.Calls == 1 && WIT_OWNER.LastKind == checked((uint)kind)
            && WIT_OWNER.LastGeneration == 19UL && WIT_OWNER.LastId == 29UL);
        if (mode == "success")
        {
            Need(failure is null && result is ValueTuple<ulong, ulong> tuple && tuple == (41UL, 59UL));
            Need(sink.ToString() == "");
        }
        else
        {
            Need(failure?.GetType() == typeof(InvalidOperationException)
                && failure.Message == "managed-work-admission-refused"
                && failure.StackTrace!.Contains("LsfManagedWorkRoot.Reserve", StringComparison.Ordinal));
            int code = kind is >= 0 and < 8 && error < 7 ? 38 + kind * 7 + (int)error : 0;
            Need(sink.ToString() == (mode == "writer-fails" ? "" : $"LSF-PERIODIC-CODE:{code:D4}" + Environment.NewLine));
        }
        Console.WriteLine(JsonSerializer.Serialize(new { kind, originalHostU32 = error, passed = true,
            originalRefusalPreserved = true, actualGeneratedBridge = true, qualification = false }));
        return 0;
    }
}

namespace WIT_NAMESPACE
{
    internal readonly struct Result
    {
        public bool IsOk => IOwnerImports.Accept;
        public uint AsErr => !IsOk ? IOwnerImports.NativeError : throw new InvalidDataException("positive-error-read");
        public (ulong, ulong) AsOk => IsOk ? (41UL, 59UL) : throw new InvalidDataException("negative-success-read");
    }
    internal static class IOwnerImports
    {
        internal static int NativeKind, Calls;
        internal static uint NativeError, LastKind;
        internal static ulong LastGeneration, LastId;
        internal static bool Accept;
        public static Result Reserve(uint kind, ulong generation, ulong id)
        {
            if (kind != checked((uint)NativeKind)) throw new InvalidDataException("native-kind-changed");
            Calls++; LastKind = kind; LastGeneration = generation; LastId = id; return new Result();
        }
        public static Result Settle(ulong generation, ulong id) => throw new InvalidDataException("unexpected-settle");
        public static Result Close() => throw new InvalidDataException("unexpected-close");
        public static void Context(ulong generation, ulong id) => throw new InvalidDataException("unexpected-context");
    }
}
