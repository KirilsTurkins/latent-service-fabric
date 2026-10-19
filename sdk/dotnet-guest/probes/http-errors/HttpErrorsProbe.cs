using System.Reflection;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;

// Execute the actual captured WASI BCL in two isolated host load contexts.
// This verifies its conversion/exception boundary, not a guest scheduler or
// default-client component. No native WASI import is called by this probe.
if (args.Length == 4 && args[0] == "--sync-send")
{
    HttpSyncSendProbe.Run(args[1..]);
    return;
}
if (args.Length == 4 && args[0] == "--request-content-headers")
{
    HttpRequestContentHeadersProbe.Run(args[1..]);
    return;
}
if (args.Length == 4 && args[0] == "--response-read-errors")
{
    HttpResponseReadErrorsProbe.Run(args[1..]);
    return;
}
if (args.Length == 4 && args[0] == "--sync-read")
{
    HttpSyncReadProbe.Run(args[1..]);
    return;
}
if (args.Length != 3 || File.Exists(args[2]))
    throw new InvalidDataException("http-error-probe-arguments");
string Digest(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
if (Digest(args[0]) != "3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587")
    throw new InvalidDataException("http-error-probe-original-preimage");
var originalContext = new AssemblyLoadContext("original-wasi-bcl", isCollectible: true);
var derivedContext = new AssemblyLoadContext("derived-wasi-bcl", isCollectible: true);
var original = originalContext.LoadFromAssemblyPath(Path.GetFullPath(args[0]));
var derived = derivedContext.LoadFromAssemblyPath(Path.GetFullPath(args[1]));
var cases = 0;
void Equal(object? expected, object? actual)
{
    cases++;
    if (!Equals(expected, actual))
        throw new InvalidDataException("http-error-probe-mismatch");
}
string ConvertError(Assembly assembly, byte tag, object? payload)
{
    var interop = assembly.GetType("System.Net.Http.WasiHttpInterop", throwOnError: true)!;
    var converter = interop.GetMethod("ErrorCodeToString", BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)!;
    var errorType = converter.GetParameters().Single().ParameterType;
    var error = Activator.CreateInstance(errorType, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
        binder: null, args: [tag, payload], culture: null)!;
    return (string)converter.Invoke(null, [error])!;
}
for (byte tag = 0; tag < 38; tag++)
    Equal(ConvertError(original, tag, null), ConvertError(derived, tag, null));
Equal(ConvertError(original, 255, "latent-http-uncertain"), ConvertError(derived, 255, "latent-http-uncertain"));
string[] markers = [
    "latent-http-request-too-large", "latent-http-response-too-large",
    "latent-http-deadline-exceeded", "latent-http-cancelled", "latent-http-budget-exhausted",
    "latent-http-tls-failed", "latent-http-connection-failed", "latent-http-unavailable",
    "latent-http-uncertain", "latent-http-invalid-state",
];
foreach (var marker in markers)
{
    Equal("INTERNAL_ERROR", ConvertError(original, 38, marker));
    var message = ConvertError(derived, 38, marker);
    Equal("INTERNAL_ERROR:" + marker, message);
    var exceptionType = derived.GetType("System.Net.Http.HttpRequestException", throwOnError: true)!;
    var exception = (Exception)Activator.CreateInstance(exceptionType, [message])!;
    Equal(message, exception.Message);
}
object?[] hiddenPayloads = [null, "", "private-credential", "latent-http-uncertain\nprivate-credential",
    "prefix-latent-http-uncertain", "latent-http-uncertain-suffix", "LATENT-HTTP-UNCERTAIN",
    new string('x', 8192), 42, new object()];
foreach (var payload in hiddenPayloads)
    Equal("INTERNAL_ERROR", ConvertError(derived, 38, payload));
var result = new {
    scope = "captured-wasi-bcl-conversion-and-exception",
    assertions = cases,
    originalDigest = "sha256:" + Digest(args[0]),
    derivedDigest = "sha256:" + Digest(args[1]),
    allNonInternalVariantsUnchanged = true,
    boundedCategoriesPreserved = true,
    arbitraryPayloadDisclosure = false,
    defaultClientComponentQualified = false,
};
using (var output = new FileStream(args[2], FileMode.CreateNew, FileAccess.Write, FileShare.None))
    JsonSerializer.Serialize(output, result);
Console.WriteLine(JsonSerializer.Serialize(result));
originalContext.Unload();
derivedContext.Unload();


internal static class HttpSyncReadProbe
{
    // Host controls intentionally use only a preloaded BCL buffer, EOF, empty
    // reads and pre-cancelled Tasks. No host result qualifies pending WASI I/O;
    // the unchanged signed fourteen-case fixture remains the native gate.
    internal static void Run(string[] args)
    {
        if (args.Length != 3 || File.Exists(args[2]))
            throw new InvalidDataException("http-sync-read-probe-arguments");
        string Digest(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
        if (Digest(args[0]) != "3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587")
            throw new InvalidDataException("http-sync-read-probe-preimage");
        var originalContext = new AssemblyLoadContext("original-sync-read-control", isCollectible: true);
        var derivedContext = new AssemblyLoadContext("derived-sync-read-control", isCollectible: true);
        try
        {
            var original = originalContext.LoadFromAssemblyPath(Path.GetFullPath(args[0]));
            var derived = derivedContext.LoadFromAssemblyPath(Path.GetFullPath(args[1]));
            const BindingFlags Fields = BindingFlags.Instance | BindingFlags.NonPublic;
            void Set(Stream stream, string name, object? value) => stream.GetType().GetField(name, Fields)!.SetValue(stream, value);
            Stream Create(Assembly assembly, byte[]? bytes = null)
            {
                var type = assembly.GetType("System.Net.Http.WasiInputStream", throwOnError: true)!;
                var stream = (Stream)System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(type);
                // There are deliberately no native handles to finalize/dispose.
                GC.SuppressFinalize(stream);
                Set(stream, "buffer", bytes);
                return stream;
            }
            var assertions = 0;
            void Equal(object? expected, object? actual)
            {
                assertions++;
                if (!Equals(expected, actual)) throw new InvalidDataException("http-sync-read-probe-mismatch");
            }
            Type? Error(Action action)
            {
                try { action(); return null; }
                catch (Exception error) { return error.GetType(); }
            }
            Equal(typeof(PlatformNotSupportedException), Error(() => Create(original).Read(new byte[1], 0, 1)));
            var empty = Create(derived);
            Equal(0, empty.Read([], 0, 0));
            // Compare malformed ranges to the original framework validator,
            // including its API-specific exception type and check ordering.
            var validate = typeof(Stream).GetMethod("ValidateBufferArguments", BindingFlags.Static | BindingFlags.NonPublic)!
                .CreateDelegate<Action<byte[], int, int>>();
            foreach (var item in new (byte[]? Buffer, int Offset, int Count)[] {
                (null, 0, 0), (new byte[2], -1, 0), (new byte[2], 0, -1), (new byte[2], 2, 1),
            })
                Equal(Error(() => validate(item.Buffer!, item.Offset, item.Count)),
                    Error(() => empty.Read(item.Buffer!, item.Offset, item.Count)));
            var buffered = Create(derived, [10, 20, 30, 40, 50]);
            byte[] destination = [99, 99, 99, 99, 99, 99];
            Equal(2, buffered.Read(destination, 1, 2));
            Equal("99,10,20,99,99,99", string.Join(",", destination));
            Equal(1, buffered.Read(destination.AsSpan(3, 1)));
            Equal((byte)30, destination[3]);
            Equal(40, buffered.ReadByte());
            Equal(1, buffered.Read(destination, 0, destination.Length));
            Equal((byte)50, destination[0]);
            Set(buffered, "otherSideClosed", true);
            Equal(0, buffered.Read(destination, 0, destination.Length));
            Equal(-1, buffered.ReadByte());
            var copied = Create(derived, [1, 2, 3, 4]);
            using (var target = new EndAfterWrite(() => Set(copied, "otherSideClosed", true)))
            {
                copied.CopyTo(target, 4);
                Equal("1,2,3,4", string.Join(",", target.ToArray()));
                Equal(1, target.Writes);
            }
            Set(empty, "isClosed", true);
            Equal(typeof(ObjectDisposedException), Error(() => empty.Read([], 0, 0)));
            Equal(typeof(ObjectDisposedException), Error(() => empty.Read(new byte[1], 0, 1)));
            var cancelled = new CancellationToken(canceled: true);
            var task = Create(derived).ReadAsync(new byte[1], 0, 1, cancelled);
            Equal(true, task.IsCanceled);
            OperationCanceledException? observed = null;
            try { task.GetAwaiter().GetResult(); }
            catch (OperationCanceledException error) { observed = error; }
            Equal(true, observed is not null);
            Equal(cancelled, observed?.CancellationToken);
            var asynchronous = Create(derived, [7, 8]);
            var bytes = new byte[2];
            Equal(2, asynchronous.ReadAsync(bytes, 0, 2, CancellationToken.None).GetAwaiter().GetResult());
            Equal("7,8", string.Join(",", bytes));
            var result = new {
                scope = "captured-wasi-bcl-sync-read-buffered-host-controls",
                assertions,
                originalDigest = "sha256:" + Digest(args[0]),
                derivedDigest = "sha256:" + Digest(args[1]),
                originalReadUnsupported = true,
                defaultClientComponentQualified = false,
                pendingGuestIoQualified = false,
            };
            using var output = new FileStream(args[2], FileMode.CreateNew, FileAccess.Write, FileShare.None);
            JsonSerializer.Serialize(output, result);
            Console.WriteLine(JsonSerializer.Serialize(result));
        }
        finally
        {
            originalContext.Unload();
            derivedContext.Unload();
        }
    }

    private sealed class EndAfterWrite(Action end) : MemoryStream
    {
        internal int Writes { get; private set; }
        public override void Write(byte[] bytes, int offset, int count)
        {
            base.Write(bytes, offset, count);
            Writes++;
            end();
        }
    }
}


internal static class HttpResponseReadErrorsProbe
{
    // These are actual derived-BCL helper controls with zero native handles.
    // They do not exercise native imports, prove a live resource drop, or stand
    // in for the unchanged signed-node truncated/oversized-body acceptance cases.
    internal static void Run(string[] args)
    {
        if (args.Length != 3 || File.Exists(args[2]))
            throw new InvalidDataException("http-response-read-errors-probe-arguments");
        string Digest(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
        if (Digest(args[0]) != "3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587")
            throw new InvalidDataException("http-response-read-errors-probe-preimage");
        var originalContext = new AssemblyLoadContext("original-response-error-control", isCollectible: true);
        var derivedContext = new AssemblyLoadContext("derived-response-error-control", isCollectible: true);
        try
        {
            var original = originalContext.LoadFromAssemblyPath(Path.GetFullPath(args[0]));
            var derived = derivedContext.LoadFromAssemblyPath(Path.GetFullPath(args[1]));
            const BindingFlags Instance = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            const string StreamError = "WasiHttpWorld.wit.imports.wasi.io.v0_2_0.IStreams+StreamError";
            var type = derived.GetType(StreamError, throwOnError: true)!;
            var resource = derived.GetType("WasiHttpWorld.wit.imports.wasi.io.v0_2_0.IError+Error", throwOnError: true)!;
            var wit = derived.GetType("WasiHttpWorld.WitException", throwOnError: true)!;
            const string Name = "LsfThrowResponseReadError";
            var mapper = type.GetMethod(Name, Instance);
            var assertions = 0;
            void Equal(object? expected, object? actual)
            {
                assertions++;
                if (!Equals(expected, actual)) throw new InvalidDataException("http-response-read-errors-probe-mismatch");
            }
            Equal(null, original.GetType(StreamError, throwOnError: true)!.GetMethod(Name, Instance));
            Equal(true, mapper is not null);
            (Exception Original, Exception Selected) Translate(byte tag, object? payload)
            {
                var error = Activator.CreateInstance(type, Instance, binder: null, args: [tag, payload], culture: null)!;
                var fallback = (Exception)Activator.CreateInstance(wit, Instance, binder: null, args: [error, 0u], culture: null)!;
                try { mapper!.Invoke(error, null); }
                catch (TargetInvocationException observed) when (observed.InnerException is not null)
                {
                    return (fallback, observed.InnerException);
                }
                // This is the exact fallback required at the original rethrow.
                return (fallback, fallback);
            }
            foreach (object? payload in new object?[] { null, "private-credential", 42, new object() })
            {
                var observed = Translate(0, payload);
                Equal(true, ReferenceEquals(observed.Original, observed.Selected));
            }
            var handle = resource.GetProperty("Handle", Instance)!;
            foreach (byte tag in new byte[] { 1, 2, 255 })
            {
                var owner = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(resource);
                var observed = Translate(tag, owner);
                Equal(true, ReferenceEquals(observed.Original, observed.Selected));
                Equal(0, handle.GetValue(owner));
            }
            var failedOwner = System.Runtime.CompilerServices.RuntimeHelpers.GetUninitializedObject(resource);
            var failed = Translate(0, failedOwner).Selected;
            Equal(typeof(IOException), failed.GetType());
            Equal("HTTP response body read failed.", failed.Message);
            Equal(null, failed.InnerException);
            Equal(0, handle.GetValue(failedOwner));
            var result = new {
                scope = "captured-wasi-bcl-response-error-zero-handle-host-controls",
                assertions,
                originalDigest = "sha256:" + Digest(args[0]),
                derivedDigest = "sha256:" + Digest(args[1]),
                nativeErrorDropQualified = false,
                pendingGuestIoQualified = false,
                defaultClientComponentQualified = false,
            };
            using var output = new FileStream(args[2], FileMode.CreateNew, FileAccess.Write, FileShare.None);
            JsonSerializer.Serialize(output, result);
            Console.WriteLine(JsonSerializer.Serialize(result));
        }
        finally
        {
            originalContext.Unload();
            derivedContext.Unload();
        }
    }
}


internal static class HttpRequestContentHeadersProbe
{
    // Execute the derived helper and the original captured BCL getter. Creating
    // native Fields is deliberately outside this host control; the unchanged
    // signed POST cases must prove actual header transmission and body framing.
    internal static void Run(string[] args)
    {
        if (args.Length != 3 || File.Exists(args[2]))
            throw new InvalidDataException("http-request-content-headers-probe-arguments");
        string Digest(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
        if (Digest(args[0]) != "3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587")
            throw new InvalidDataException("http-request-content-headers-probe-preimage");
        var originalContext = new AssemblyLoadContext("original-content-headers-control", isCollectible: true);
        var derivedContext = new AssemblyLoadContext("derived-content-headers-control", isCollectible: true);
        try
        {
            var original = originalContext.LoadFromAssemblyPath(Path.GetFullPath(args[0]));
            var derived = derivedContext.LoadFromAssemblyPath(Path.GetFullPath(args[1]));
            var helper = derived.GetType("System.Net.Http.WasiHttpInterop", throwOnError: true)!
                .GetMethod("LsfPrepareRequestContentHeaders", BindingFlags.NonPublic | BindingFlags.Static)!;
            object Make(Assembly assembly, string name, params object[] values) =>
                Activator.CreateInstance(assembly.GetType("System.Net.Http." + name, throwOnError: true)!, values)!;
            object Headers(object content) => content.GetType().GetProperty("Headers")!.GetValue(content)!;
            object Prepare(object content) => helper.Invoke(null, [content])!;
            Dictionary<string, string> Values(object headers) =>
                ((IEnumerable<KeyValuePair<string, IEnumerable<string>>>)headers)
                    .ToDictionary(pair => pair.Key, pair => string.Join(",", pair.Value), StringComparer.OrdinalIgnoreCase);
            object? Length(object headers) => headers.GetType().GetProperty("ContentLength")!.GetValue(headers);
            void SetLength(object headers, long? value) => headers.GetType().GetProperty("ContentLength")!.SetValue(headers, value);
            string Snapshot(object headers) => string.Join("|", Values(headers).OrderBy(pair => pair.Key)
                .Select(pair => pair.Key + ":" + pair.Value));
            var assertions = 0;
            void Equal(object? expected, object? actual)
            {
                assertions++;
                if (!Equals(expected, actual)) throw new InvalidDataException("http-request-content-headers-probe-mismatch");
            }
            var baseline = Make(original, "ByteArrayContent", new byte[] { 0, 1, 2, 3 });
            var content = Make(derived, "ByteArrayContent", new byte[] { 0, 1, 2, 3 });
            var baselineHeaders = Headers(baseline);
            var headers = Headers(content);
            Equal(false, Values(baselineHeaders).ContainsKey("Content-Length"));
            Equal(false, Values(headers).ContainsKey("Content-Length"));
            Equal(true, ReferenceEquals(headers, Prepare(content)));
            Equal("4", Values(headers)["Content-Length"]);
            Equal(4L, Length(baselineHeaders));
            Equal(Snapshot(baselineHeaders), Snapshot(headers));
            ((IDisposable)baseline).Dispose();
            ((IDisposable)content).Dispose();

            foreach (var size in new[] { 0, 1, 4, 1000 })
            {
                var sized = Make(derived, "ByteArrayContent", new byte[size]);
                var prepared = Prepare(sized);
                Equal(size.ToString(System.Globalization.CultureInfo.InvariantCulture), Values(prepared)["Content-Length"]);
                Equal(Snapshot(prepared), Snapshot(Prepare(sized)));
                ((IDisposable)sized).Dispose();
            }
            var segment = Make(derived, "ByteArrayContent", new byte[7], 2, 3);
            Equal("3", Values(Prepare(segment))["Content-Length"]);
            ((IDisposable)segment).Dispose();
            using (var source = new MemoryStream(new byte[8]))
            {
                source.Position = 3;
                var streamContent = Make(derived, "StreamContent", source);
                Equal("5", Values(Prepare(streamContent))["Content-Length"]);
                Equal(3L, source.Position);
                ((IDisposable)streamContent).Dispose();
            }
            var explicitContent = Make(derived, "ByteArrayContent", new byte[4]);
            var explicitHeaders = Headers(explicitContent);
            SetLength(explicitHeaders, 9);
            var before = Snapshot(explicitHeaders);
            Equal("9", Values(Prepare(explicitContent))["Content-Length"]);
            Equal(before, Snapshot(explicitHeaders));
            SetLength(explicitHeaders, null);
            Equal(false, Values(Prepare(explicitContent)).ContainsKey("Content-Length"));
            Equal(null, Length(explicitHeaders));
            ((IDisposable)explicitContent).Dispose();

            using (var source = new UnreadableStream(seekable: false))
            {
                var streamContent = Make(derived, "StreamContent", source);
                Equal(false, Values(Prepare(streamContent)).ContainsKey("Content-Length"));
                Equal(0, source.ReadCalls);
                Equal(0, source.LengthCalls);
                ((IDisposable)streamContent).Dispose();
            }
            var typed = Make(derived, "ByteArrayContent", new byte[4]);
            var typedHeaders = Headers(typed);
            var add = typedHeaders.GetType().GetMethod("TryAddWithoutValidation", [typeof(string), typeof(string)])!;
            add.Invoke(typedHeaders, ["Content-Type", "application/octet-stream"]);
            add.Invoke(typedHeaders, ["X-Lsf-Probe", "preserved"]);
            var values = Values(Prepare(typed));
            Equal("application/octet-stream", values["Content-Type"]);
            Equal("preserved", values["X-Lsf-Probe"]);
            Equal("4", values["Content-Length"]);
            ((IDisposable)typed).Dispose();

            using (var source = new UnreadableStream(seekable: true))
            {
                var streamContent = Make(derived, "StreamContent", source);
                Exception? observed = null;
                try { Prepare(streamContent); }
                catch (TargetInvocationException error) { observed = error.InnerException; }
                Equal(true, ReferenceEquals(source.Failure, observed));
                Equal(1, source.LengthCalls);
                Equal(0, source.ReadCalls);
                ((IDisposable)streamContent).Dispose();
            }
            var result = new {
                scope = "captured-wasi-bcl-request-content-headers-host-controls",
                assertions,
                originalDigest = "sha256:" + Digest(args[0]),
                derivedDigest = "sha256:" + Digest(args[1]),
                originalLazyLengthMissing = true,
                nativeHeaderTransmissionQualified = false,
                pendingGuestIoQualified = false,
                defaultClientComponentQualified = false,
            };
            using var output = new FileStream(args[2], FileMode.CreateNew, FileAccess.Write, FileShare.None);
            JsonSerializer.Serialize(output, result);
            Console.WriteLine(JsonSerializer.Serialize(result));
        }
        finally
        {
            originalContext.Unload();
            derivedContext.Unload();
        }
    }

    private sealed class UnreadableStream(bool seekable) : Stream
    {
        internal readonly Exception Failure = new InvalidDataException("content-length-control");
        internal int ReadCalls { get; private set; }
        internal int LengthCalls { get; private set; }
        public override bool CanRead => true;
        public override bool CanWrite => false;
        public override bool CanSeek => seekable;
        public override long Length { get { LengthCalls++; throw Failure; } }
        public override long Position { get => 0; set => throw new NotSupportedException(); }
        public override int Read(byte[] buffer, int offset, int count) { ReadCalls++; throw Failure; }
        public override void Flush() => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }
}


internal static class HttpSyncSendProbe
{
    // Only invalid requests are executed on the host: their original SendAsync
    // fails before native WASI I/O. Successful/pending Send requires signed-node
    // qualification and cannot be inferred from these completed fault paths.
    internal static void Run(string[] args)
    {
        if (args.Length != 3 || File.Exists(args[2]))
            throw new InvalidDataException("http-sync-send-probe-arguments");
        string Digest(string path) => Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
        if (Digest(args[0]) != "3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587")
            throw new InvalidDataException("http-sync-send-probe-preimage");
        var originalContext = new AssemblyLoadContext("original-sync-send-control", isCollectible: true);
        var derivedContext = new AssemblyLoadContext("derived-sync-send-control", isCollectible: true);
        var owned = new List<IDisposable>();
        try
        {
            var original = originalContext.LoadFromAssemblyPath(Path.GetFullPath(args[0]));
            var derived = derivedContext.LoadFromAssemblyPath(Path.GetFullPath(args[1]));
            const BindingFlags Flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            var assertions = 0;
            void Equal(object? expected, object? actual)
            {
                assertions++;
                if (!Equals(expected, actual)) throw new InvalidDataException("http-sync-send-probe-mismatch");
            }
            object DefaultHandler(Assembly assembly)
            {
                var clientType = assembly.GetType("System.Net.Http.HttpClient", throwOnError: true)!;
                var client = Activator.CreateInstance(clientType)!;
                owned.Add((IDisposable)client);
                var outer = clientType.BaseType!.GetField("_handler", Flags)!.GetValue(client)!;
                Equal("System.Net.Http.HttpClientHandler", outer.GetType().FullName);
                var handler = outer.GetType().GetField("_underlyingHandler", Flags)!.GetValue(outer)!;
                Equal("System.Net.Http.WasiHttpHandler", handler.GetType().FullName);
                return handler;
            }
            var originalHandler = DefaultHandler(original);
            var derivedHandler = DefaultHandler(derived);
            object? Request(Assembly assembly, bool nullRequest) => nullRequest ? null :
                Activator.CreateInstance(assembly.GetType("System.Net.Http.HttpRequestMessage", throwOnError: true)!);
            MethodInfo Method(object handler, string name) => handler.GetType().GetMethods(Flags)
                .Single(method => method.Name == name && method.GetParameters().Length == 2);
            Exception Failure(Action action)
            {
                try { action(); }
                catch (Exception error)
                {
                    while (error is TargetInvocationException { InnerException: not null } target)
                        error = target.InnerException!;
                    return error;
                }
                throw new InvalidDataException("http-sync-send-probe-expected-original-fault");
            }
            Exception Send(object handler, object? request) => Failure(() =>
                Method(handler, "Send").Invoke(handler, [request, CancellationToken.None]));
            Exception SendAsync(object handler, object? request) => Failure(() =>
                ((Task)Method(handler, "SendAsync").Invoke(handler, [request, CancellationToken.None])!).GetAwaiter().GetResult());
            foreach (var nullRequest in new[] { true, false })
                Equal(typeof(PlatformNotSupportedException), Send(originalHandler, Request(original, nullRequest)).GetType());
            foreach (var nullRequest in new[] { true, false })
            {
                var reference = SendAsync(originalHandler, Request(original, nullRequest));
                var unchanged = SendAsync(derivedHandler, Request(derived, nullRequest));
                var synchronous = Send(derivedHandler, Request(derived, nullRequest));
                var expected = nullRequest ? typeof(NullReferenceException) : typeof(ArgumentException);
                Equal((expected, expected), (reference.GetType(), unchanged.GetType()));
                Equal(reference.Message, unchanged.Message);
                Equal(unchanged.GetType(), synchronous.GetType());
                Equal(unchanged.Message, synchronous.Message);
            }
            Equal("System.Net.Http.HttpMessageHandler", Method(derivedHandler, "Send").GetBaseDefinition().DeclaringType!.FullName);
            var result = new {
                scope = "captured-wasi-bcl-sync-send-validation-host-controls",
                assertions,
                originalDigest = "sha256:" + Digest(args[0]),
                derivedDigest = "sha256:" + Digest(args[1]),
                originalSynchronousSendUnsupported = true,
                originalSendAsyncFaultsPreserved = true,
                ordinaryDefaultConstructionPreserved = true,
                nativeSendQualified = false,
                pendingGuestIoQualified = false,
                defaultClientComponentQualified = false,
            };
            using var output = new FileStream(args[2], FileMode.CreateNew, FileAccess.Write, FileShare.None);
            JsonSerializer.Serialize(output, result);
            Console.WriteLine(JsonSerializer.Serialize(result));
        }
        finally
        {
            foreach (var client in owned) client.Dispose();
            originalContext.Unload();
            derivedContext.Unload();
        }
    }
}
