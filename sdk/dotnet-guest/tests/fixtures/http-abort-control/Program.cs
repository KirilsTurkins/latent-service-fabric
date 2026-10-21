using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Mono.Cecil;
using Mono.Cecil.Cil;

// Explicit resource ports. Only the three pinned producer method bodies are
// copied verbatim (operand identities lowered to these ports) into this CLR
// control. This is not a WASI/provider/physical-retirement qualification.
public static class Events { public static readonly List<string> Values = new(); }
public sealed class WitPortException : Exception { }
public sealed class OutputResourcePort : IDisposable {
    public void Dispose() => Events.Values.Add("stream-drop");
}
public sealed class BodyPort : IDisposable {
    public bool Failed;
    public void Dispose() => Events.Values.Add("body-abort");
    public static void Finish(BodyPort body, object? trailers) {
        Events.Values.Add("body-finish");
        if (body.Failed) throw new WitPortException();
    }
}
public sealed class FuturePort : IDisposable {
    public void Dispose() => Events.Values.Add("future-drop");
}
public sealed class InputPort : Stream {
    protected override void Dispose(bool disposing) => Events.Values.Add("input-drop");
    public override bool CanRead => false; public override bool CanSeek => false; public override bool CanWrite => false;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
    public override void Flush() => throw new NotSupportedException();
    public override int Read(byte[] b, int o, int n) => throw new NotSupportedException();
    public override long Seek(long o, SeekOrigin s) => throw new NotSupportedException();
    public override void SetLength(long n) => throw new NotSupportedException();
    public override void Write(byte[] b, int o, int n) => throw new NotSupportedException();
}
public sealed class OutputStreamPort : Stream {
    public bool isClosed;
    public OutputResourcePort stream = new();
    public BodyPort body = new();
    public override void Close() => throw new InvalidOperationException("unbound original Close");
    protected override void Dispose(bool disposing) => throw new InvalidOperationException("unbound original Dispose");
    internal void AbortCleanup() => throw new InvalidOperationException("unbound correction");
    public override bool CanRead => false; public override bool CanSeek => false; public override bool CanWrite => true;
    public override long Length => throw new NotSupportedException();
    public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
    public override void Flush() => throw new NotSupportedException();
    public override int Read(byte[] b, int o, int n) => throw new NotSupportedException();
    public override long Seek(long o, SeekOrigin s) => throw new NotSupportedException();
    public override void SetLength(long n) => throw new NotSupportedException();
    public override void Write(byte[] b, int o, int n) => throw new NotSupportedException();
}
public sealed class RequestPort {
    public bool isDisposed;
    public OutputStreamPort? wasiOutputStream;
    public InputPort? incomingStream;
    public FuturePort? future;
    public void Dispose() => throw new InvalidOperationException("unbound original wrapper cleanup");
}

internal static class HttpAbortControl {
    private const string Original = "3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587";
    private static void Need(bool condition) { if (!condition) throw new InvalidDataException("closed control failed"); }
    private static string Hash(string path) => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path)));
    private static void Derive(string original, string destination, bool corrected) {
        Need(Hash(original) == Original && !Directory.Exists(destination));
        using var source = ModuleDefinition.ReadModule(original);
        using var target = ModuleDefinition.ReadModule(typeof(HttpAbortControl).Assembly.Location);
        const string Types = "WasiHttpWorld.wit.imports.wasi.http.v0_2_0.ITypes/";
        var ports = new Dictionary<string,string> {
            ["System.Net.Http.WasiOutputStream"] = nameof(OutputStreamPort),
            ["System.Net.Http.WasiRequestWrapper"] = nameof(RequestPort),
            ["System.Net.Http.WasiInputStream"] = nameof(InputPort),
            ["WasiHttpWorld.wit.imports.wasi.io.v0_2_0.IStreams/OutputStream"] = nameof(OutputResourcePort),
            [Types+"OutgoingBody"] = nameof(BodyPort), [Types+"FutureIncomingResponse"] = nameof(FuturePort),
        };
        TypeDefinition Port(string name) => target.Types.Single(t => t.FullName == ports[name]);
        MethodReference MapMethod(MethodReference method) {
            if (ports.ContainsKey(method.DeclaringType.FullName))
                return Port(method.DeclaringType.FullName).Methods.Single(m => m.Name == (method.Name == "LsfAbortFailedRequestOutput" ? "AbortCleanup" : method.Name)
                    && m.Parameters.Count == method.Parameters.Count);
            Need(method.DeclaringType.FullName is "System.IO.Stream" or "System.GC");
            var reflected = (method.DeclaringType.FullName == "System.GC" ? typeof(GC) : typeof(Stream)).GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static)
                .Single(m => m.Name == method.Name && m.GetParameters().Length == method.Parameters.Count);
            return target.ImportReference(reflected);
        }
        if (corrected) ManagedHttpWork.AbortCleanup(source);
        var selected = source.GetTypes().SelectMany(t => t.Methods).Where(m =>
            m.DeclaringType.FullName == "System.Net.Http.WasiOutputStream" && (m.Name == "Close" || m.Name == "Dispose" || m.Name == "LsfAbortFailedRequestOutput")
            || m.DeclaringType.FullName == "System.Net.Http.WasiRequestWrapper" && m.Name == "Dispose").ToArray();
        Need(selected.Length == (corrected ? 4 : 3));
        foreach (var originalMethod in selected) {
            Need(originalMethod.Body.ExceptionHandlers.Count == 0 && originalMethod.Body.Variables.Count == 0);
            var destinationMethod = MapMethod(originalMethod).Resolve();
            destinationMethod.Body = new Mono.Cecil.Cil.MethodBody(destinationMethod) {
                InitLocals = originalMethod.Body.InitLocals, MaxStackSize = originalMethod.Body.MaxStackSize };
            var map = originalMethod.Body.Instructions.ToDictionary(i => i, _ => Instruction.Create(OpCodes.Nop));
            foreach (var instruction in originalMethod.Body.Instructions) {
                var copy = map[instruction]; copy.OpCode = instruction.OpCode;
                copy.Operand = instruction.Operand switch {
                    Instruction branch => map[branch],
                    FieldReference field => Port(field.DeclaringType.FullName).Fields.Single(f => f.Name == field.Name),
                    MethodReference method => MapMethod(method),
                    _ => instruction.Operand,
                };
                destinationMethod.Body.Instructions.Add(copy);
            }
        }
        Directory.CreateDirectory(destination);
        target.Write(Path.Combine(destination,"Control.dll"));
        foreach (string name in new[] { "Control.runtimeconfig.json", "Control.deps.json", "Mono.Cecil.dll" })
            File.Copy(Path.Combine(Path.GetDirectoryName(typeof(HttpAbortControl).Assembly.Location)!,name),Path.Combine(destination,name));
        Console.WriteLine(JsonSerializer.Serialize(new { sourceHttp = Original, copiedActualBodies = 3,
            corrected, copiedGeneratedHelpers = corrected ? 1 : 0, assembly = Hash(Path.Combine(destination,"Control.dll")), guestQualified = false }));
    }
    private static void Execute(bool corrected) {
        var request = new RequestPort { wasiOutputStream = new OutputStreamPort { body = new BodyPort { Failed = true } },
            incomingStream = new InputPort(), future = new FuturePort() };
        var original = new HttpRequestException("HTTP_REQUEST_BODY_SIZE"); Exception? observed = null;
        try { try { throw original; } catch { request.Dispose(); throw; } }
        catch (Exception error) { observed = error; }
        Need(corrected ? ReferenceEquals(original,observed) : observed is WitPortException);
        Need(Events.Values.SequenceEqual(corrected
            ? new[] { "stream-drop", "body-abort", "input-drop", "future-drop" }
            : new[] { "stream-drop", "body-finish" }));
        var failedEvents = Events.Values.ToArray(); Events.Values.Clear();
        var successful = new OutputStreamPort(); successful.Close(); successful.Close();
        Need(Events.Values.SequenceEqual(new[] { "stream-drop", "body-finish" }));
        Console.WriteLine(JsonSerializer.Serialize(new { corrected, copiedActualBodies = 3,
            originalExceptionPreserved = ReferenceEquals(original,observed), failedEvents,
            successEvents = Events.Values, nativeResources = "explicit-test-ports", guestQualified = false }));
    }
    private static void Main(string[] args) {
        if (args.Length == 4 && args[0] == "derive") Derive(args[1],args[2],args[3] == "new");
        else if (args.Length == 2 && args[0] == "execute") Execute(args[1] == "new");
        else throw new InvalidDataException("closed control arguments");
    }
}
