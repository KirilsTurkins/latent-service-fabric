using Mono.Cecil;
using Mono.Cecil.Cil;
using System.Security.Cryptography;
using System.Text.Json;

// This private CoreLib derivation closes the two native filesystem entry
// wrappers after the unchanged public FileStream/path argument validation.
internal static class ClosedFilesystem
{
    private const string Original = "29e4bd3f70bfb0e0ea00fb2511e28ee9832b56caf9ddb5cd60906fe3bcaad735";
    private const string Cecil = "2590bbe9492beef92f4dc1a34513d7ddafaeb6ab91eb618b84f6ee6c2b9c46d7";
    private static readonly string[] Names = [
        "Microsoft.Win32.SafeHandles.SafeFileHandle Interop/Sys::Open(System.String,Interop/Sys/OpenFlags,System.Int32)",
        "System.IntPtr Interop/Sys::MksTemps(System.Byte*,System.Int32)",
    ];
    private static void Require(bool value)
    {
        if (!value) throw new InvalidDataException("closed-filesystem-preimage-or-shape");
    }
    private static string Hash(string path, long maximum)
    {
        var file = new FileInfo(path);
        Require(file.Exists && file.LinkTarget is null && file.Length > 0 && file.Length <= maximum);
        return Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
    }
    private static Dictionary<string, MethodDefinition> Methods(ModuleDefinition module) =>
        module.GetTypes().SelectMany(type => type.Methods.Select((method, index) =>
            new { key = type.FullName + "#" + index, method })).ToDictionary(item => item.key, item => item.method);

    internal static int Run(string[] args)
    {
        try
        {
            Require(args.Length == 4 && args.All(value => value.Length is > 0 and <= 4096));
            var paths = args.Select(Path.GetFullPath).ToArray();
            var original = paths[0]; var selected = paths[1]; var output = paths[2]; var receipt = paths[3];
            Require(output != receipt && output != original && output != selected && receipt != original && receipt != selected &&
                !File.Exists(output) && !Directory.Exists(output) && !File.Exists(receipt) && !Directory.Exists(receipt));
            Require(Hash(original, 8 * 1024 * 1024) == Original && new FileInfo(original).Length == 5694976);
            Require(Hash(typeof(ModuleDefinition).Assembly.Location, 512 * 1024) == Cecil);
            var baseDigest = Hash(selected, 8 * 1024 * 1024);
            using var source = ModuleDefinition.ReadModule(original);
            using var module = ModuleDefinition.ReadModule(selected);
            Require(module.Assembly.Name.FullName == source.Assembly.Name.FullName &&
                source.Assembly.Name.Name == "System.Private.CoreLib" && source.Assembly.Name.Version == new Version(10, 0, 0, 0));
            var before = Methods(module);
            Require(before.Count is >= 10000 and <= 65536);
            var identities = before.ToDictionary(item => item.Key, item => TaskWait.BodyIdentity(item.Value));
            var originalBodies = new Dictionary<string, string>();
            var changed = new HashSet<string>();
            var exception = module.Types.Single(type => type.FullName == "System.PlatformNotSupportedException");
            var constructor = exception.Methods.Single(method => method.IsConstructor && !method.IsStatic &&
                method.Parameters.Count == 1 && method.Parameters[0].ParameterType.MetadataType == MetadataType.String);
            foreach (var name in Names)
            {
                var originalMethod = source.GetTypes().SelectMany(type => type.Methods).Single(method => method.FullName == name);
                var row = before.Single(item => item.Value.FullName == name);
                var method = row.Value;
                Require(method.IsStatic && method.HasBody && !method.IsPInvokeImpl &&
                    identities[row.Key] == TaskWait.BodyIdentity(originalMethod));
                originalBodies.Add(name, identities[row.Key]); changed.Add(row.Key);
                method.Body = new MethodBody(method) { InitLocals = false, MaxStackSize = 1 };
                var il = method.Body.GetILProcessor();
                il.Emit(OpCodes.Ldstr, "Filesystem operations are unsupported in the closed guest profile.");
                il.Emit(OpCodes.Newobj, constructor);
                il.Emit(OpCodes.Throw);
            }
            Require(changed.Count == 2);
            var selectedBodies = Methods(module).ToDictionary(item => item.Key, item => TaskWait.BodyIdentity(item.Value));
            Require(selectedBodies.Count == identities.Count && identities.All(item => changed.Contains(item.Key) || selectedBodies[item.Key] == item.Value));
            module.Write(output, new WriterParameters { WriteSymbols = false, DeterministicMvid = true });
            using (var product = ModuleDefinition.ReadModule(output))
            {
                var written = Methods(product).ToDictionary(item => item.Key, item => TaskWait.BodyIdentity(item.Value));
                Require(written.Count == selectedBodies.Count && selectedBodies.All(item => written[item.Key] == item.Value));
            }
            Require(Hash(original, 8 * 1024 * 1024) == Original && Hash(selected, 8 * 1024 * 1024) == baseDigest);
            var proof = new {
                patch = "latent.dotnet.closed-filesystem.v1", originalDigest = "sha256:" + Original,
                baseDigest = "sha256:" + baseDigest, outputDigest = "sha256:" + Hash(output, 8 * 1024 * 1024),
                cecilDigest = "sha256:" + Cecil, originalMethodBodies = originalBodies, modifiedOriginalMethods = 2,
                unchangedBaseMethods = identities.Count - 2, otherBaseBodiesUnchanged = true,
                publicWrappersUnchanged = true, newHostImports = 0, filesystemAuthority = false,
            };
            using var stream = new FileStream(receipt, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            JsonSerializer.Serialize(stream, proof);
            return 0;
        }
        catch (Exception)
        {
            Console.Error.WriteLine("closed-filesystem-preimage-or-shape");
            return 1;
        }
    }
}
