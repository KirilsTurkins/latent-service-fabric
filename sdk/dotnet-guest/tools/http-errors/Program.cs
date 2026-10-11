using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;

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
        try
        {
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
            module.Write(output, new WriterParameters { WriteSymbols = false, DeterministicMvid = true });
            if (Digest(original, 512 * 1024) != SourceDigest)
                throw new InvalidDataException("http-error-patch-original-changed");
            var result = new {
                patch = "latent.dotnet.http-errors.v1",
                sourceDigest = "sha256:" + SourceDigest,
                outputDigest = "sha256:" + Digest(output, 512 * 1024),
                cecilDigest = "sha256:" + CecilDigest,
                method = converter.FullName,
                categories = Markers,
                arbitraryPayloadDisclosure = false,
                defaultClientComponentQualified = false,
            };
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
