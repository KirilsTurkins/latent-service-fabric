using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;
using System.Reflection.PortableExecutable;

// This tool is a captured compiler input. It accepts one exact maintained WASI
// framework assembly, writes a private derived copy and never changes NuGet
// packages or application assemblies. It installs no host capability.
internal static class Program
{
    private const string SourceDigest = "3ab88385e44dbed09c99b0a9a00fd80d6a14033a390d5471289b848267e05587";
    private const string CecilDigest = "2590bbe9492beef92f4dc1a34513d7ddafaeb6ab91eb618b84f6ee6c2b9c46d7";
    private const string HelperName = "LsfBoundedInternalErrorMessage";
    private static readonly string[] Markers = [
        "latent-http-request-too-large", "latent-http-response-too-large",
        "latent-http-deadline-exceeded", "latent-http-cancelled",
        "latent-http-budget-exhausted", "latent-http-tls-failed",
        "latent-http-connection-failed", "latent-http-unavailable",
        "latent-http-uncertain", "latent-http-invalid-state",
    ];

    private static string Digest(string path, long maximum)
    {
        var info = new FileInfo(path);
        if (!info.Exists || info.LinkTarget is not null || info.Length == 0 || info.Length > maximum)
            throw new InvalidDataException("http-error-patch-invalid-material");
        using var input = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant();
    }

    private static int Main(string[] args)
    {
        if (args.Length == 4 && args[0] == "--task-wait")
            return TaskWait.Run(args[1..]);
        try
        {
            var synchronousRead = args.Length == 4 && args[0] == "--sync-read";
            if (synchronousRead) args = args[1..];
            if (args.Length != 3 || args.Any(path => path.Length is 0 or > 4096))
                throw new InvalidDataException("http-error-patch-arguments");
            var original = Path.GetFullPath(args[0]);
            var output = Path.GetFullPath(args[1]);
            var receipt = Path.GetFullPath(args[2]);
            if (original == output || original == receipt || output == receipt ||
                File.Exists(output) || Directory.Exists(output) || File.Exists(receipt) || Directory.Exists(receipt))
                throw new InvalidDataException("http-error-patch-output-must-be-fresh");
            if (Digest(typeof(ModuleDefinition).Assembly.Location, 512 * 1024) != CecilDigest)
                throw new InvalidDataException("http-error-patch-cecil-preimage");
            if (Digest(original, 512 * 1024) != SourceDigest)
                throw new InvalidDataException("http-error-patch-unsupported-runtime-preimage");
            using var module = ModuleDefinition.ReadModule(original, new ReaderParameters {
                ReadWrite = false, ReadSymbols = false, ReadingMode = ReadingMode.Deferred,
            });
            if (module.Assembly.Name.FullName !=
                "System.Net.Http, Version=10.0.0.0, Culture=neutral, PublicKeyToken=b03f5f7f11d50a3a")
                throw new InvalidDataException("http-error-patch-assembly-identity");
            var interop = module.Types.Single(type => type.FullName == "System.Net.Http.WasiHttpInterop");
            var converter = interop.Methods.Single(method => method.Name == "ErrorCodeToString");
            if (!converter.IsStatic || converter.Parameters.Count != 1 ||
                converter.ReturnType.MetadataType != MetadataType.String || converter.Body.Instructions.Count != 95)
                throw new InvalidDataException("http-error-patch-converter-shape");
            var error = converter.Parameters[0].ParameterType.Resolve();
            if (error.Module != module || error.FullName !=
                "WasiHttpWorld.wit.imports.wasi.http.v0_2_0.ITypes/ErrorCode" ||
                error.Methods.Any(method => method.Name == HelperName))
                throw new InvalidDataException("http-error-patch-error-type");
            var payload = error.Fields.Single(field => field.Name == "value" && field.FieldType.MetadataType == MetadataType.Object);
            var instructions = converter.Body.Instructions;
            var entry = instructions.Single(instruction => instruction.OpCode == OpCodes.Ldstr &&
                instruction.Operand is string text && text == "INTERNAL_ERROR");
            var targets = (Instruction[])instructions.Single(instruction => instruction.OpCode == OpCodes.Switch).Operand;
            if (targets.Length != 39 || targets[38] != entry || entry.Next?.OpCode != OpCodes.Ret)
                throw new InvalidDataException("http-error-patch-internal-error-shape");

            // Selection also requires the authenticated, joined CoreLib port.
            // The caller binds both private assemblies to the same ILC response.
            var syncRead = synchronousRead ? JsonSerializer.SerializeToNode(HttpSyncRead.Apply(module))!.AsObject() : null;
            if (syncRead is not null)
            {
                syncRead["responseReadErrors"] = JsonSerializer.SerializeToNode(HttpReadErrors.Apply(module, original));
                syncRead["requestContentHeaders"] = JsonSerializer.SerializeToNode(HttpRequestContentHeaders.Apply(module, original));
                syncRead["synchronousSend"] = JsonSerializer.SerializeToNode(HttpSyncSend.Apply(module));
                syncRead["defaultHandlerSynchronousSend"] = JsonSerializer.SerializeToNode(HttpDefaultSyncSend.Apply(module));
            }

            // Keep the payload access in its declaring type. Only these finite
            // adapter-owned category strings are exposed; arbitrary WASI error
            // payloads, malformed variants and secrets keep the original text.
            var helper = new MethodDefinition(HelperName,
                MethodAttributes.Assembly | MethodAttributes.Static | MethodAttributes.HideBySig, module.TypeSystem.String);
            helper.Parameters.Add(new ParameterDefinition(error));
            helper.Body.InitLocals = true;
            helper.Body.Variables.Add(new VariableDefinition(module.TypeSystem.String));
            helper.Body.MaxStackSize = 2;
            var equality = new MethodReference("op_Equality", module.TypeSystem.Boolean, module.TypeSystem.String) { HasThis = false };
            equality.Parameters.Add(new ParameterDefinition(module.TypeSystem.String));
            equality.Parameters.Add(new ParameterDefinition(module.TypeSystem.String));
            var il = helper.Body.GetILProcessor();
            il.Emit(OpCodes.Ldarg_0);
            il.Emit(OpCodes.Ldfld, payload);
            il.Emit(OpCodes.Isinst, module.TypeSystem.String);
            il.Emit(OpCodes.Stloc_0);
            foreach (var marker in Markers)
            {
                var next = il.Create(OpCodes.Nop);
                il.Emit(OpCodes.Ldloc_0);
                il.Emit(OpCodes.Ldstr, marker);
                il.Emit(OpCodes.Call, equality);
                il.Emit(OpCodes.Brfalse, next);
                il.Emit(OpCodes.Ldstr, "INTERNAL_ERROR:" + marker);
                il.Emit(OpCodes.Ret);
                il.Append(next);
            }
            il.Emit(OpCodes.Ldstr, "INTERNAL_ERROR");
            il.Emit(OpCodes.Ret);
            error.Methods.Add(helper);
            entry.OpCode = OpCodes.Ldarg_0;
            entry.Operand = null;
            var originalReturn = entry.Next;
            originalReturn.OpCode = OpCodes.Call;
            originalReturn.Operand = helper;
            converter.Body.GetILProcessor().InsertAfter(originalReturn, Instruction.Create(OpCodes.Ret));
            var selectedMethods = module.GetTypes().SelectMany(type => type.Methods)
                .ToDictionary(method => method.FullName, method => TaskWait.BodyIdentity(method));
            module.Write(output, new WriterParameters { WriteSymbols = false, DeterministicMvid = true });
            // Reopen the serialized product before issuing a receipt. Relocated
            // method tokens may change; branch, catch and helper semantics may not.
            using (var product = ModuleDefinition.ReadModule(output))
            {
                var writtenMethods = product.GetTypes().SelectMany(type => type.Methods)
                    .ToDictionary(method => method.FullName, method => TaskWait.BodyIdentity(method));
                if (writtenMethods.Count != selectedMethods.Count ||
                    selectedMethods.Any(item => !writtenMethods.TryGetValue(item.Key, out var body) || body != item.Value))
                    throw new InvalidDataException("http-error-patch-serialized-method-drift");
            }
            if (Digest(original, 512 * 1024) != SourceDigest)
                throw new InvalidDataException("http-error-patch-original-changed");
            var result = JsonSerializer.SerializeToNode(new {
                patch = "latent.dotnet.http-errors.v1",
                sourceDigest = "sha256:" + SourceDigest,
                outputDigest = "sha256:" + Digest(output, 512 * 1024),
                cecilDigest = "sha256:" + CecilDigest,
                method = converter.FullName,
                categories = Markers,
                arbitraryPayloadDisclosure = false,
                defaultClientComponentQualified = false,
            })!.AsObject();
            if (syncRead is not null)
                result["synchronousRead"] = JsonSerializer.SerializeToNode(syncRead);
            using var receiptOutput = new FileStream(receipt, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            JsonSerializer.Serialize(receiptOutput, result);
            Console.WriteLine(JsonSerializer.Serialize(result));
            return 0;
        }
        catch (Exception)
        {
            // Compiler diagnostics carry a closed cause; do not expose input
            // paths, package contents or arbitrary exception payloads.
            Console.Error.WriteLine("http-error-patch-failed");
            return 1;
        }
    }
}


// The source digest above authenticates this exact WASI implementation, not a
// similarly named application stream. Reuse only its own BCL metadata: never
// resolve a framework reference against the compiler host's CLR assemblies.
internal static class HttpSyncRead
{
    private const string StreamType = "System.Net.Http.WasiInputStream";
    private const string CoreLib = "System.Private.CoreLib, Version=10.0.0.0, Culture=neutral, PublicKeyToken=7cec85d7bea7798e";

    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidDataException("http-sync-read-preimage-or-shape");
    }

    private static bool ClosedType(TypeReference type, string name, string argument) =>
        type is GenericInstanceType generic && generic.ElementType.FullName == name &&
        generic.GenericArguments.Count == 1 && generic.GenericArguments[0].FullName == argument &&
        generic.ElementType.Scope is AssemblyNameReference scope && scope.FullName == CoreLib;

    internal static object Apply(ModuleDefinition module)
    {
        var stream = module.Types.Single(type => type.FullName == StreamType);
        Require(stream.IsSealed && stream.BaseType.FullName == "System.IO.Stream" &&
            stream.BaseType.Scope is AssemblyNameReference scope && scope.FullName == CoreLib);
        var read = stream.Methods.Single(method => method.FullName ==
            "System.Int32 System.Net.Http.WasiInputStream::Read(System.Byte[],System.Int32,System.Int32)");
        var asyncRead = stream.Methods.Single(method => method.FullName ==
            "System.Threading.Tasks.Task`1<System.Int32> System.Net.Http.WasiInputStream::ReadAsync(System.Byte[],System.Int32,System.Int32,System.Threading.CancellationToken)");
        Require(read.IsPublic && read.IsVirtual && !read.IsStatic && read.HasBody &&
            read.Body.Variables.Count == 0 && read.Body.ExceptionHandlers.Count == 0 &&
            read.Body.Instructions.Count == 2 && read.Body.Instructions[0].OpCode == OpCodes.Newobj &&
            read.Body.Instructions[0].Operand is MethodReference unsupported &&
            unsupported.FullName == "System.Void System.PlatformNotSupportedException::.ctor()" &&
            unsupported.DeclaringType.Scope is AssemblyNameReference unsupportedScope && unsupportedScope.FullName == CoreLib &&
            read.Body.Instructions[1].OpCode == OpCodes.Throw &&
            asyncRead.IsPublic && asyncRead.IsVirtual && !asyncRead.IsStatic && asyncRead.HasBody &&
            ClosedType(asyncRead.ReturnType, "System.Threading.Tasks.Task`1", "System.Int32"));
        var closed = stream.Fields.Single(field => field.Name == "isClosed");
        Require(!closed.IsStatic && closed.FieldType.MetadataType == MetadataType.Boolean);
        var references = module.GetMemberReferences().OfType<MethodReference>().ToArray();
        var validate = references.Single(method => method.FullName ==
            "System.Void System.IO.Stream::ValidateBufferArguments(System.Byte[],System.Int32,System.Int32)");
        var disposed = references.Single(method => method.FullName ==
            "System.Void System.ObjectDisposedException::ThrowIf(System.Boolean,System.Object)");
        var none = references.Single(method => method.FullName ==
            "System.Threading.CancellationToken System.Threading.CancellationToken::get_None()");
        var awaiterTemplate = references.Single(method => method.Name == "GetAwaiter" &&
            ClosedType(method.DeclaringType, "System.Threading.Tasks.Task`1", "System.Net.Http.HttpResponseMessage"));
        var resultTemplate = references.Single(method => method.Name == "GetResult" &&
            ClosedType(method.DeclaringType, "System.Runtime.CompilerServices.TaskAwaiter`1", "System.Net.Http.HttpResponseMessage"));
        Require(new[] { validate, disposed, none }.All(method => !method.HasThis &&
            method.DeclaringType.Scope is AssemblyNameReference referenceScope && referenceScope.FullName == CoreLib) &&
            awaiterTemplate.HasThis && awaiterTemplate.Parameters.Count == 0 &&
            awaiterTemplate.ReturnType is GenericInstanceType templateReturn &&
            templateReturn.ElementType.FullName == "System.Runtime.CompilerServices.TaskAwaiter`1" &&
            templateReturn.GenericArguments.Count == 1 &&
            templateReturn.GenericArguments[0] is GenericParameter { Position: 0, Type: GenericParameterType.Type } &&
            resultTemplate.HasThis && resultTemplate.Parameters.Count == 0 &&
            resultTemplate.ReturnType is GenericParameter { Position: 0, Type: GenericParameterType.Type });

        var original = module.GetTypes().SelectMany(type => type.Methods)
            .ToDictionary(method => method, method => TaskWait.BodyIdentity(method));
        var awaiterType = new GenericInstanceType(((GenericInstanceType)awaiterTemplate.ReturnType).ElementType);
        awaiterType.GenericArguments.Add(module.TypeSystem.Int32);
        // MemberRef signatures retain !0, instantiated by the declaring type;
        // the local, by contrast, must have the concrete TaskAwaiter<int> type.
        var getAwaiter = new MethodReference("GetAwaiter", awaiterTemplate.ReturnType, asyncRead.ReturnType) {
            HasThis = true, CallingConvention = awaiterTemplate.CallingConvention,
        };
        var getResult = new MethodReference("GetResult", resultTemplate.ReturnType, awaiterType) {
            HasThis = true, CallingConvention = resultTemplate.CallingConvention,
        };
        read.Body = new MethodBody(read) { InitLocals = true, MaxStackSize = 5 };
        var awaiter = new VariableDefinition(awaiterType);
        read.Body.Variables.Add(awaiter);
        var il = read.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Ldarg_2);
        il.Emit(OpCodes.Ldarg_3);
        il.Emit(OpCodes.Call, validate);
        il.Emit(OpCodes.Ldarg_0);
        il.Emit(OpCodes.Ldfld, closed);
        il.Emit(OpCodes.Ldarg_0);
        il.Emit(OpCodes.Call, disposed);
        var beginRead = il.Create(OpCodes.Ldarg_0);
        il.Emit(OpCodes.Ldarg_3);
        il.Emit(OpCodes.Brtrue, beginRead);
        // A valid empty read must not acquire a pollable or contact a provider.
        il.Emit(OpCodes.Ldc_I4_0);
        il.Emit(OpCodes.Ret);
        il.Append(beginRead);
        il.Emit(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Ldarg_2);
        il.Emit(OpCodes.Ldarg_3);
        il.Emit(OpCodes.Call, none);
        il.Emit(OpCodes.Call, asyncRead);
        il.Emit(OpCodes.Callvirt, getAwaiter);
        il.Emit(OpCodes.Stloc, awaiter);
        il.Emit(OpCodes.Ldloca, awaiter);
        il.Emit(OpCodes.Call, getResult);
        il.Emit(OpCodes.Ret);
        Require(original.Where(item => item.Key != read).All(item => TaskWait.BodyIdentity(item.Key) == item.Value));
        return new {
            profile = "dotnet-wasi-sync-response-read-v1",
            method = read.FullName,
            asyncMethod = asyncRead.FullName,
            originalReadBodyDigest = "sha256:" + original[read],
            originalAsyncBodyDigest = "sha256:" + original[asyncRead],
            modifiedOriginalMethods = 1,
            unchangedOriginalMethods = original.Count - 1,
            completion = "original-ReadAsync-TaskAwaiter",
            bufferValidation = "original-Stream.ValidateBufferArguments",
            emptyRead = "zero-without-provider-contact",
            disposal = "original-ObjectDisposedException.ThrowIf",
            generatedHelpers = 0,
            newHostImports = 0,
            defaultClientComponentQualified = false,
        };
    }
}


// Keep the generated stream's native error payload access inside its declaring
// type. Only this authenticated response-reader catch is adapted; EOF, pending
// polling, cancellation, result production and all other BCL methods stay intact.
internal static class HttpReadErrors
{
    private const string StreamErrorType = "WasiHttpWorld.wit.imports.wasi.io.v0_2_0.IStreams/StreamError";
    private const string ResourceType = "WasiHttpWorld.wit.imports.wasi.io.v0_2_0.IError/Error";
    private const string Method = "System.Void System.Net.Http.WasiInputStream/<ReadAsync>d__17::MoveNext()";
    private const string OriginalIlDigest = "785ff886dedc4ce9d1340bbd4262043c2a142821524448383e135fb61f1292a5";
    private const string Helper = "LsfThrowResponseReadError";
    private const string Message = "HTTP response body read failed.";
    private const string CoreLib = "System.Private.CoreLib, Version=10.0.0.0, Culture=neutral, PublicKeyToken=7cec85d7bea7798e";

    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidDataException("http-response-read-error-preimage-or-shape");
    }

    internal static object Apply(ModuleDefinition module, string originalPath)
    {
        var types = module.GetTypes().ToDictionary(type => type.FullName);
        var error = types[StreamErrorType];
        var resource = types[ResourceType];
        var reader = types["System.Net.Http.WasiInputStream/<ReadAsync>d__17"];
        var method = reader.Methods.Single(candidate => candidate.FullName == Method);
        Require(method.HasBody && !method.IsStatic && method.Parameters.Count == 0 &&
            !error.IsValueType && !error.Methods.Any(candidate => candidate.Name == Helper));
        using (var input = File.OpenRead(originalPath))
        using (var pe = new PEReader(input))
        {
            var code = System.Reflection.Metadata.PEReaderExtensions.GetMethodBody(pe, checked((int)method.RVA)).GetILBytes();
            Require(code is not null && code.Length == 446 &&
                Convert.ToHexString(SHA256.HashData(code)).ToLowerInvariant() == OriginalIlDigest);
        }
        var tag = error.Fields.Single(field => field.Name == "Tag");
        var payload = error.Fields.Single(field => field.Name == "value");
        var dispose = resource.Methods.Single(candidate => candidate.Name == "Dispose" && candidate.Parameters.Count == 0);
        Require(!tag.IsStatic && tag.IsInitOnly && tag.FieldType.MetadataType == MetadataType.Byte &&
            !payload.IsStatic && payload.IsInitOnly && payload.IsPrivate && payload.FieldType.MetadataType == MetadataType.Object &&
            dispose.IsPublic && !dispose.IsStatic && dispose.HasBody && dispose.ReturnType.MetadataType == MetadataType.Void);
        var exception = module.GetMemberReferences().OfType<MethodReference>().Single(candidate => candidate.FullName ==
            "System.Void System.IO.IOException::.ctor(System.String)");
        Require(exception.HasThis && exception.DeclaringType.Scope is AssemblyNameReference scope && scope.FullName == CoreLib);
        var original = module.GetTypes().SelectMany(type => type.Methods)
            .ToDictionary(candidate => candidate, candidate => TaskWait.BodyIdentity(candidate));
        Require(original.Count == 2093);
        var catchBlock = method.Body.ExceptionHandlers.Single(handler => handler.HandlerType == ExceptionHandlerType.Catch &&
            handler.CatchType?.FullName == "WasiHttpWorld.WitException");
        var instructions = method.Body.Instructions;
        var catchInstructions = instructions.SkipWhile(instruction => instruction != catchBlock.HandlerStart)
            .TakeWhile(instruction => instruction != catchBlock.HandlerEnd).ToArray();
        var cast = catchInstructions.Single(instruction => instruction.OpCode == OpCodes.Castclass &&
            instruction.Operand is TypeReference reference && reference.FullName == StreamErrorType);
        var rethrow = catchInstructions.Single(instruction => instruction.OpCode == OpCodes.Rethrow);
        Require(cast.Previous == catchBlock.HandlerStart && cast.Previous.OpCode == OpCodes.Callvirt &&
            cast.Previous.Operand is MethodReference value && value.FullName == "System.Object WasiHttpWorld.WitException::get_Value()" &&
            cast.Next.OpCode == OpCodes.Ldfld && cast.Next.Operand == tag &&
            cast.Next.Next.OpCode == OpCodes.Ldc_I4_1 && cast.Next.Next.Next.OpCode == OpCodes.Bne_Un_S &&
            cast.Next.Next.Next.Operand == rethrow && rethrow.Next == catchBlock.HandlerEnd);

        var helper = new MethodDefinition(Helper, MethodAttributes.Assembly | MethodAttributes.HideBySig, module.TypeSystem.Void);
        helper.Body.InitLocals = true;
        helper.Body.MaxStackSize = 2;
        var owner = new VariableDefinition(resource);
        helper.Body.Variables.Add(owner);
        var emit = helper.Body.GetILProcessor();
        var unchanged = emit.Create(OpCodes.Ret);
        emit.Emit(OpCodes.Ldarg_0);
        emit.Emit(OpCodes.Ldfld, tag);
        emit.Emit(OpCodes.Brtrue, unchanged);
        emit.Emit(OpCodes.Ldarg_0);
        emit.Emit(OpCodes.Ldfld, payload);
        emit.Emit(OpCodes.Isinst, resource);
        emit.Emit(OpCodes.Stloc, owner);
        emit.Emit(OpCodes.Ldloc, owner);
        emit.Emit(OpCodes.Brfalse, unchanged);
        // This releases only the native error resource, not the response body or
        // outstanding physical HTTP operation. A failed drop is not a clean exit.
        emit.Emit(OpCodes.Ldloc, owner);
        emit.Emit(OpCodes.Callvirt, dispose);
        emit.Emit(OpCodes.Ldstr, Message);
        emit.Emit(OpCodes.Newobj, exception);
        emit.Emit(OpCodes.Throw);
        // Unknown tags and malformed payloads retain the caller's original
        // WitException rethrow; neither becomes EOF or a fabricated I/O result.
        emit.Append(unchanged);
        error.Methods.Add(helper);

        var captured = new VariableDefinition(error);
        method.Body.Variables.Add(captured);
        var il = method.Body.GetILProcessor();
        var duplicate = il.Create(OpCodes.Dup);
        il.InsertAfter(cast, duplicate);
        il.InsertAfter(duplicate, il.Create(OpCodes.Stloc, captured));
        var first = il.Create(OpCodes.Ldloc, captured);
        il.InsertBefore(rethrow, first);
        il.InsertBefore(rethrow, il.Create(OpCodes.Call, helper));
        // The existing non-CLOSED branch targets rethrow directly. It must enter
        // the translation first, while the real rethrow remains as the fallback.
        foreach (var instruction in instructions)
        {
            if (instruction.Operand == rethrow) instruction.Operand = first;
            else if (instruction.Operand is Instruction[] targets)
                for (var index = 0; index < targets.Length; index++)
                    if (targets[index] == rethrow) targets[index] = first;
            // Added catch instructions must not overflow an existing short jump.
            instruction.OpCode = instruction.OpCode.Code switch {
                Code.Br_S => OpCodes.Br, Code.Brfalse_S => OpCodes.Brfalse, Code.Brtrue_S => OpCodes.Brtrue,
                Code.Beq_S => OpCodes.Beq, Code.Bge_S => OpCodes.Bge, Code.Bge_Un_S => OpCodes.Bge_Un,
                Code.Bgt_S => OpCodes.Bgt, Code.Bgt_Un_S => OpCodes.Bgt_Un, Code.Ble_S => OpCodes.Ble,
                Code.Ble_Un_S => OpCodes.Ble_Un, Code.Blt_S => OpCodes.Blt, Code.Blt_Un_S => OpCodes.Blt_Un,
                Code.Bne_Un_S => OpCodes.Bne_Un, Code.Leave_S => OpCodes.Leave,
                _ => instruction.OpCode,
            };
        }
        Require(original.Where(item => item.Key != method).All(item => TaskWait.BodyIdentity(item.Key) == item.Value) &&
            module.GetTypes().SelectMany(type => type.Methods).Count() == original.Count + 1);
        return new {
            profile = "dotnet-wasi-response-read-errors-v1",
            method = method.FullName,
            originalIlBytes = 446,
            originalIlDigest = "sha256:" + OriginalIlDigest,
            exceptionType = "System.IO.IOException",
            message = Message,
            nativeErrorOwnership = "dispose-before-throw",
            closed = "original-eof",
            cancellation = "original-propagation",
            unknownError = "original-rethrow",
            modifiedOriginalMethods = 1,
            generatedHelpers = 1,
            newHostImports = 0,
            pendingGuestIoQualified = false,
        };
    }
}
// Materialize the original lazy ContentLength getter at the existing content
// header enumeration boundary. Never serialize or buffer content to infer its
// length, and never replace explicit length/null or unknown-stream semantics.
internal static class HttpRequestContentHeaders
{
    private const string Method = "WasiHttpWorld.wit.imports.wasi.http.v0_2_0.ITypes/Fields System.Net.Http.WasiHttpInterop::ConvertRequestHeaders(System.Net.Http.HttpRequestMessage)";
    private const string OriginalIlDigest = "b38ac3de4ab20fbeb71b1fb783b501721061ec8139403125cd40b8590f0ac2b9";
    private const string Getter = "System.Nullable`1<System.Int64> System.Net.Http.Headers.HttpContentHeaders::get_ContentLength()";
    private const string GetterIlDigest = "b1414b862ff467801df85e05df0fba005cf796f3e63d963cb46e7c166df881be";
    private const string Helper = "LsfPrepareRequestContentHeaders";

    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidDataException("http-request-content-headers-preimage-or-shape");
    }

    private static void VerifyIl(PEReader pe, MethodDefinition method, int length, string digest)
    {
        var code = System.Reflection.Metadata.PEReaderExtensions.GetMethodBody(pe, checked((int)method.RVA)).GetILBytes();
        Require(code is not null && code.Length == length &&
            Convert.ToHexString(SHA256.HashData(code)).ToLowerInvariant() == digest);
    }

    internal static object Apply(ModuleDefinition module, string originalPath)
    {
        var interop = module.Types.Single(type => type.FullName == "System.Net.Http.WasiHttpInterop");
        var content = module.Types.Single(type => type.FullName == "System.Net.Http.HttpContent");
        var headers = module.Types.Single(type => type.FullName == "System.Net.Http.Headers.HttpContentHeaders");
        var method = interop.Methods.Single(candidate => candidate.FullName == Method);
        var getter = headers.Methods.Single(candidate => candidate.FullName == Getter);
        var getHeaders = content.Methods.Single(candidate => candidate.FullName ==
            "System.Net.Http.Headers.HttpContentHeaders System.Net.Http.HttpContent::get_Headers()");
        Require(method.IsStatic && method.HasBody && getter.IsPublic && !getter.IsStatic && getter.HasBody &&
            getHeaders.IsPublic && !getHeaders.IsStatic && getHeaders.HasBody &&
            !interop.Methods.Any(candidate => candidate.Name == Helper));
        using (var input = File.OpenRead(originalPath))
        using (var pe = new PEReader(input))
        {
            VerifyIl(pe, method, 297, OriginalIlDigest);
            VerifyIl(pe, getter, 104, GetterIlDigest);
        }
        var enumeration = method.Body.Instructions.Single(instruction => instruction.OpCode == OpCodes.Callvirt &&
            instruction.Operand is MethodReference target && target.FullName == getHeaders.FullName);
        Require(enumeration.Previous.OpCode == OpCodes.Callvirt &&
            enumeration.Previous.Operand is MethodReference requestContent && requestContent.FullName ==
                "System.Net.Http.HttpContent System.Net.Http.HttpRequestMessage::get_Content()" &&
            enumeration.Next.OpCode == OpCodes.Callvirt && enumeration.Next.Operand is MethodReference iterator &&
            iterator.Name == "GetEnumerator" && iterator.DeclaringType.FullName == "System.Net.Http.Headers.HttpHeaders");
        var original = module.GetTypes().SelectMany(type => type.Methods)
            .ToDictionary(candidate => candidate, candidate => TaskWait.BodyIdentity(candidate));
        var helper = new MethodDefinition(Helper,
            MethodAttributes.Assembly | MethodAttributes.Static | MethodAttributes.HideBySig, headers);
        helper.Parameters.Add(new ParameterDefinition(content));
        helper.Body.MaxStackSize = 2;
        var il = helper.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0);
        il.Emit(OpCodes.Callvirt, getHeaders);
        il.Emit(OpCodes.Dup);
        il.Emit(OpCodes.Callvirt, getter);
        il.Emit(OpCodes.Pop);
        il.Emit(OpCodes.Ret);
        interop.Methods.Add(helper);
        // Both call instructions occupy five bytes and consume/produce the same
        // stack types. All original branch targets and exception regions stay.
        enumeration.OpCode = OpCodes.Call;
        enumeration.Operand = helper;
        Require(original.Where(item => item.Key != method).All(item => TaskWait.BodyIdentity(item.Key) == item.Value) &&
            module.GetTypes().SelectMany(type => type.Methods).Count() == original.Count + 1);
        return new {
            profile = "dotnet-wasi-request-content-length-v1",
            method = method.FullName,
            originalIlBytes = 297,
            originalIlDigest = "sha256:" + OriginalIlDigest,
            getter = getter.FullName,
            getterIlBytes = 104,
            getterIlDigest = "sha256:" + GetterIlDigest,
            noContent = "original-no-content-branch",
            explicitLength = "original-value-including-null",
            unknownLength = "original-null-no-buffering",
            modifiedOriginalMethods = 1,
            generatedHelpers = 1,
            newHostImports = 0,
            serializesContent = false,
            buffersContent = false,
            defaultClientComponentQualified = false,
        };
    }
}


// Reuse the original WASI transport and the separately authenticated TaskWait
// join. This is selected only with --sync-read after the whole original BCL is
// authenticated; ordinary error-only derivations retain the unsupported Send.
internal static class HttpSyncSend
{
    private const string Handler = "System.Net.Http.WasiHttpHandler";
    private const string CoreLib = "System.Private.CoreLib, Version=10.0.0.0, Culture=neutral, PublicKeyToken=7cec85d7bea7798e";
    private const string Send = "System.Net.Http.HttpResponseMessage System.Net.Http.WasiHttpHandler::Send(System.Net.Http.HttpRequestMessage,System.Threading.CancellationToken)";
    private const string SendAsync = "System.Threading.Tasks.Task`1<System.Net.Http.HttpResponseMessage> System.Net.Http.WasiHttpHandler::SendAsync(System.Net.Http.HttpRequestMessage,System.Threading.CancellationToken)";

    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidDataException("http-sync-send-preimage-or-shape");
    }

    private static bool ClosedType(TypeReference type, string name, string argument) =>
        type is GenericInstanceType generic && generic.ElementType.FullName == name &&
        generic.GenericArguments.Count == 1 && generic.GenericArguments[0].FullName == argument &&
        generic.ElementType.Scope is AssemblyNameReference scope && scope.FullName == CoreLib;

    internal static object Apply(ModuleDefinition module)
    {
        var handler = module.Types.Single(type => type.FullName == Handler);
        var send = handler.Methods.Single(method => method.FullName == Send);
        var sendAsync = handler.Methods.Single(method => method.FullName == SendAsync);
        Require(handler.IsSealed && handler.BaseType.FullName == "System.Net.Http.HttpMessageHandler" &&
            handler.BaseType.Scope == module && send.IsFamilyOrAssembly && send.IsVirtual && !send.IsNewSlot &&
            !send.IsStatic && send.HasBody && send.Parameters.Count == 2 &&
            send.Body.Variables.Count == 0 && send.Body.ExceptionHandlers.Count == 0 &&
            send.Body.Instructions.Count == 2 && send.Body.Instructions[0].OpCode == OpCodes.Newobj &&
            send.Body.Instructions[0].Operand is MethodReference unsupported &&
            unsupported.FullName == "System.Void System.PlatformNotSupportedException::.ctor()" &&
            unsupported.DeclaringType.Scope is AssemblyNameReference scope && scope.FullName == CoreLib &&
            send.Body.Instructions[1].OpCode == OpCodes.Throw &&
            sendAsync.IsFamilyOrAssembly && sendAsync.IsVirtual && !sendAsync.IsStatic && sendAsync.HasBody &&
            sendAsync.Parameters.Count == 2 &&
            ClosedType(sendAsync.ReturnType, "System.Threading.Tasks.Task`1", "System.Net.Http.HttpResponseMessage") &&
            send.Parameters.Select(parameter => parameter.ParameterType.FullName).SequenceEqual(
                sendAsync.Parameters.Select(parameter => parameter.ParameterType.FullName)));
        // Check the unchanged ordinary construction path, not an injected
        // handler or a package-selected factory replacement.
        var client = module.Types.Single(type => type.FullName == "System.Net.Http.HttpClient");
        var clientHandler = module.Types.Single(type => type.FullName == "System.Net.Http.HttpClientHandler");
        var clientConstructor = client.Methods.Single(method => method.IsConstructor && !method.IsStatic && method.Parameters.Count == 0);
        var handlerConstructor = clientHandler.Methods.Single(method => method.IsConstructor && !method.IsStatic && method.Parameters.Count == 0);
        Require(clientConstructor.HasBody && handlerConstructor.HasBody &&
            clientConstructor.Body.Instructions.Any(instruction => instruction.OpCode == OpCodes.Newobj &&
                instruction.Operand is MethodReference target && target.FullName == "System.Void System.Net.Http.HttpClientHandler::.ctor()") &&
            handlerConstructor.Body.Instructions.Any(instruction => instruction.OpCode == OpCodes.Newobj &&
                instruction.Operand is MethodReference target && target.FullName == "System.Void System.Net.Http.WasiHttpHandler::.ctor()"));
        var references = module.GetMemberReferences().OfType<MethodReference>().ToArray();
        var awaiterTemplate = references.Single(method => method.Name == "GetAwaiter" &&
            ClosedType(method.DeclaringType, "System.Threading.Tasks.Task`1", "System.Net.Http.HttpResponseMessage"));
        var resultTemplate = references.Single(method => method.Name == "GetResult" &&
            ClosedType(method.DeclaringType, "System.Runtime.CompilerServices.TaskAwaiter`1", "System.Net.Http.HttpResponseMessage"));
        Require(awaiterTemplate.HasThis && awaiterTemplate.Parameters.Count == 0 &&
            awaiterTemplate.ReturnType is GenericInstanceType templateReturn &&
            templateReturn.ElementType.FullName == "System.Runtime.CompilerServices.TaskAwaiter`1" &&
            templateReturn.GenericArguments.Count == 1 &&
            templateReturn.GenericArguments[0] is GenericParameter { Position: 0, Type: GenericParameterType.Type } &&
            resultTemplate.HasThis && resultTemplate.Parameters.Count == 0 &&
            resultTemplate.ReturnType is GenericParameter { Position: 0, Type: GenericParameterType.Type });
        var original = module.GetTypes().SelectMany(type => type.Methods)
            .ToDictionary(method => method, method => TaskWait.BodyIdentity(method));
        var awaiterType = new GenericInstanceType(((GenericInstanceType)awaiterTemplate.ReturnType).ElementType);
        awaiterType.GenericArguments.Add(send.ReturnType);
        var getAwaiter = new MethodReference("GetAwaiter", awaiterTemplate.ReturnType, sendAsync.ReturnType) {
            HasThis = true, CallingConvention = awaiterTemplate.CallingConvention,
        };
        var getResult = new MethodReference("GetResult", resultTemplate.ReturnType, awaiterType) {
            HasThis = true, CallingConvention = resultTemplate.CallingConvention,
        };
        send.Body = new MethodBody(send) { InitLocals = true, MaxStackSize = 3 };
        var awaiter = new VariableDefinition(awaiterType);
        send.Body.Variables.Add(awaiter);
        var il = send.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarg_0);
        il.Emit(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Ldarg_2);
        il.Emit(OpCodes.Callvirt, sendAsync);
        il.Emit(OpCodes.Callvirt, getAwaiter);
        il.Emit(OpCodes.Stloc, awaiter);
        il.Emit(OpCodes.Ldloca, awaiter);
        il.Emit(OpCodes.Call, getResult);
        il.Emit(OpCodes.Ret);
        Require(original.Where(item => item.Key != send).All(item => TaskWait.BodyIdentity(item.Key) == item.Value));
        return new {
            profile = "dotnet-wasi-sync-send-v1",
            method = send.FullName,
            asyncMethod = sendAsync.FullName,
            originalBody = "authenticated-PlatformNotSupportedException-throw",
            defaultConstruction = "original-HttpClient-HttpClientHandler-WasiHttpHandler",
            completion = "original-SendAsync-TaskAwaiter",
            requestAndCancellation = "original-arguments",
            modifiedOriginalMethods = 1,
            generatedHelpers = 0,
            newHostImports = 0,
            nativeSendQualified = false,
        };
    }
}


// The outer default handler has its own authenticated WASI unsupported throw.
// Delegate to its unchanged async method so the original lazy Handler chain,
// validation, telemetry and request/cancellation identity remain authoritative.
internal static class HttpDefaultSyncSend
{
    private const string Handler = "System.Net.Http.HttpClientHandler";
    private const string CoreLib = "System.Private.CoreLib, Version=10.0.0.0, Culture=neutral, PublicKeyToken=7cec85d7bea7798e";
    private const string Send = "System.Net.Http.HttpResponseMessage System.Net.Http.HttpClientHandler::Send(System.Net.Http.HttpRequestMessage,System.Threading.CancellationToken)";
    private const string SendAsync = "System.Threading.Tasks.Task`1<System.Net.Http.HttpResponseMessage> System.Net.Http.HttpClientHandler::SendAsync(System.Net.Http.HttpRequestMessage,System.Threading.CancellationToken)";

    private static void Require(bool condition)
    {
        if (!condition) throw new InvalidDataException("http-default-sync-send-preimage-or-shape");
    }

    private static bool ClosedType(TypeReference type, string name, string argument) =>
        type is GenericInstanceType generic && generic.ElementType.FullName == name &&
        generic.GenericArguments.Count == 1 && generic.GenericArguments[0].FullName == argument &&
        generic.ElementType.Scope is AssemblyNameReference scope && scope.FullName == CoreLib;

    internal static object Apply(ModuleDefinition module)
    {
        var handler = module.Types.Single(type => type.FullName == Handler);
        var send = handler.Methods.Single(method => method.FullName == Send);
        var sendAsync = handler.Methods.Single(method => method.FullName == SendAsync);
        Require(!handler.IsSealed && handler.IsPublic && handler.BaseType.FullName == "System.Net.Http.HttpMessageHandler" &&
            handler.BaseType.Scope == module && send.IsFamilyOrAssembly && send.IsVirtual && !send.IsNewSlot &&
            !send.IsStatic && send.HasBody && send.Parameters.Count == 2 &&
            send.Body.Variables.Count == 0 && send.Body.ExceptionHandlers.Count == 0 &&
            send.Body.Instructions.Count == 2 && send.Body.Instructions[0].OpCode == OpCodes.Newobj &&
            send.Body.Instructions[0].Operand is MethodReference unsupported &&
            unsupported.FullName == "System.Void System.PlatformNotSupportedException::.ctor()" &&
            unsupported.DeclaringType.Scope is AssemblyNameReference scope && scope.FullName == CoreLib &&
            send.Body.Instructions[1].OpCode == OpCodes.Throw &&
            sendAsync.IsFamilyOrAssembly && sendAsync.IsVirtual && !sendAsync.IsStatic && sendAsync.HasBody &&
            sendAsync.Parameters.Count == 2 &&
            ClosedType(sendAsync.ReturnType, "System.Threading.Tasks.Task`1", "System.Net.Http.HttpResponseMessage") &&
            send.Parameters.Select(parameter => parameter.ParameterType.FullName).SequenceEqual(
                sendAsync.Parameters.Select(parameter => parameter.ParameterType.FullName)));
        // Check the unchanged ordinary construction path, not an injected
        // handler or a package-selected factory replacement.
        var client = module.Types.Single(type => type.FullName == "System.Net.Http.HttpClient");
        var clientHandler = module.Types.Single(type => type.FullName == "System.Net.Http.HttpClientHandler");
        var clientConstructor = client.Methods.Single(method => method.IsConstructor && !method.IsStatic && method.Parameters.Count == 0);
        var handlerConstructor = clientHandler.Methods.Single(method => method.IsConstructor && !method.IsStatic && method.Parameters.Count == 0);
        Require(clientConstructor.HasBody && handlerConstructor.HasBody &&
            clientConstructor.Body.Instructions.Any(instruction => instruction.OpCode == OpCodes.Newobj &&
                instruction.Operand is MethodReference target && target.FullName == "System.Void System.Net.Http.HttpClientHandler::.ctor()") &&
            handlerConstructor.Body.Instructions.Any(instruction => instruction.OpCode == OpCodes.Newobj &&
                instruction.Operand is MethodReference target && target.FullName == "System.Void System.Net.Http.WasiHttpHandler::.ctor()"));
        var references = module.GetMemberReferences().OfType<MethodReference>().ToArray();
        var cancellationThrow = references.Single(method => method.FullName ==
            "System.Void System.Threading.CancellationToken::ThrowIfCancellationRequested()");
        Require(cancellationThrow.HasThis && cancellationThrow.Parameters.Count == 0 &&
            cancellationThrow.DeclaringType.IsValueType &&
            cancellationThrow.DeclaringType.Scope is AssemblyNameReference cancellationScope &&
            cancellationScope.FullName == CoreLib &&
            send.Parameters[1].ParameterType.FullName == cancellationThrow.DeclaringType.FullName &&
            send.Parameters[1].ParameterType.Scope is AssemblyNameReference parameterScope && parameterScope.FullName == CoreLib);
        var awaiterTemplate = references.Single(method => method.Name == "GetAwaiter" &&
            ClosedType(method.DeclaringType, "System.Threading.Tasks.Task`1", "System.Net.Http.HttpResponseMessage"));
        var resultTemplate = references.Single(method => method.Name == "GetResult" &&
            ClosedType(method.DeclaringType, "System.Runtime.CompilerServices.TaskAwaiter`1", "System.Net.Http.HttpResponseMessage"));
        Require(awaiterTemplate.HasThis && awaiterTemplate.Parameters.Count == 0 &&
            awaiterTemplate.ReturnType is GenericInstanceType templateReturn &&
            templateReturn.ElementType.FullName == "System.Runtime.CompilerServices.TaskAwaiter`1" &&
            templateReturn.GenericArguments.Count == 1 &&
            templateReturn.GenericArguments[0] is GenericParameter { Position: 0, Type: GenericParameterType.Type } &&
            resultTemplate.HasThis && resultTemplate.Parameters.Count == 0 &&
            resultTemplate.ReturnType is GenericParameter { Position: 0, Type: GenericParameterType.Type });
        var original = module.GetTypes().SelectMany(type => type.Methods)
            .ToDictionary(method => method, method => TaskWait.BodyIdentity(method));
        var awaiterType = new GenericInstanceType(((GenericInstanceType)awaiterTemplate.ReturnType).ElementType);
        awaiterType.GenericArguments.Add(send.ReturnType);
        var getAwaiter = new MethodReference("GetAwaiter", awaiterTemplate.ReturnType, sendAsync.ReturnType) {
            HasThis = true, CallingConvention = awaiterTemplate.CallingConvention,
        };
        var getResult = new MethodReference("GetResult", resultTemplate.ReturnType, awaiterType) {
            HasThis = true, CallingConvention = resultTemplate.CallingConvention,
        };
        send.Body = new MethodBody(send) { InitLocals = true, MaxStackSize = 3 };
        var awaiter = new VariableDefinition(awaiterType);
        send.Body.Variables.Add(awaiter);
        var il = send.Body.GetILProcessor();
        il.Emit(OpCodes.Ldarga, send.Parameters[1]);
        il.Emit(OpCodes.Call, cancellationThrow);
        il.Emit(OpCodes.Ldarg_0);
        il.Emit(OpCodes.Ldarg_1);
        il.Emit(OpCodes.Ldarg_2);
        il.Emit(OpCodes.Callvirt, sendAsync);
        il.Emit(OpCodes.Callvirt, getAwaiter);
        il.Emit(OpCodes.Stloc, awaiter);
        il.Emit(OpCodes.Ldloca, awaiter);
        il.Emit(OpCodes.Call, getResult);
        il.Emit(OpCodes.Ret);
        Require(original.Where(item => item.Key != send).All(item => TaskWait.BodyIdentity(item.Key) == item.Value));
        return new {
            profile = "dotnet-default-httpclient-sync-send-v1",
            method = send.FullName,
            asyncMethod = sendAsync.FullName,
            originalBody = "authenticated-PlatformNotSupportedException-throw",
            defaultConstruction = "original-HttpClient-HttpClientHandler-WasiHttpHandler",
            completion = "original-SendAsync-TaskAwaiter",
            requestAndCancellation = "original-arguments",
            preCancellation = "original-CancellationToken.ThrowIfCancellationRequested-before-SendAsync",
            modifiedOriginalMethods = 1,
            generatedHelpers = 0,
            newHostImports = 0,
            nativeSendQualified = false,
        };
    }
}
