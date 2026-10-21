// Passive ECMA-335 metadata only. Never Assembly.Load or execute application IL.
// The finite non-generic Ecma name projection follows NativeAotNameMangler.cs at
// dotnet/runtimelab 8449ba666dd991e495d8363d9852f18eb86a1aa1 (MIT license).
using System.Reflection;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;
using System.Text.Json;

internal static class Program
{
    private const int MaxAssemblies = 512, MaxQueries = 64, MaxMethods = 262144;
    private const long MaxAssemblyBytes = 16 * 1024 * 1024, MaxTotalBytes = 64 * 1024 * 1024;
    private record Query(string Id, string AssemblyDigest, string SignatureDigest, string Symbol,
        string? MangledName, string Kind, string Declaration, bool RootAnchor);
    private static string Digest(byte[] value) => "sha256:" + Convert.ToHexStringLower(SHA256.HashData(value));
    private static string Sanitize(string value)
    {
        // Exact pinned UTF-16 sanitizer, including collision participation by
        // declarations whose non-ASCII query mapping remains unknown below.
        return string.Concat(value.Select((c, i) => char.IsAsciiLetter(c) ? c.ToString()
            : char.IsAsciiDigit(c) ? (i == 0 ? "_" : "") + c : "_"));
    }
    private static string Unique(string value, HashSet<string> used)
    {
        var selected = value; var suffix = 0;
        while (used.Contains(selected)) selected = value + "_" + suffix++;
        used.Add(selected); return selected;
    }
    private static void Require(bool value) { if (!value) throw new InvalidDataException("compiler-metadata-input-invalid"); }
    private static bool Ascii(string value) => value.All(c => c <= 127);
    private static bool ExportAttribute(MetadataReader metadata, MethodDefinition method)
    {
        foreach (var handle in method.GetCustomAttributes())
        {
            var attribute = metadata.GetCustomAttribute(handle);
            if (attribute.Constructor.Kind != HandleKind.MemberReference) continue;
            var constructor = metadata.GetMemberReference((MemberReferenceHandle)attribute.Constructor);
            if (metadata.GetString(constructor.Name) != ".ctor" || constructor.Parent.Kind != HandleKind.TypeReference) continue;
            var type = metadata.GetTypeReference((TypeReferenceHandle)constructor.Parent);
            if (metadata.GetString(type.Namespace) != "System.Runtime.InteropServices"
                || metadata.GetString(type.Name) != "UnmanagedCallersOnlyAttribute"
                || type.ResolutionScope.Kind != HandleKind.AssemblyReference) continue;
            var owner = metadata.GetAssemblyReference((AssemblyReferenceHandle)type.ResolutionScope);
            if (metadata.GetString(owner.Name) is "System.Runtime.InteropServices" or "System.Runtime" or "System.Private.CoreLib") return true;
        }
        return false;
    }
    public static int Main(string[] args)
    {
        Require(args.Length == 2);
        var manifest = new FileInfo(args[0]);
        Require(manifest.Exists && manifest.Length <= 65536 && manifest.LinkTarget is null);
        var paths = JsonSerializer.Deserialize<string[]>(File.ReadAllBytes(manifest.FullName))
            ?? throw new InvalidDataException("compiler-metadata-input-invalid");
        Require(paths is not null && paths.Length is > 0 and <= MaxAssemblies
            && paths.Distinct(StringComparer.Ordinal).Count() == paths.Length);
        var queries = new List<Query>(); var assemblyIdentities = new List<string>();
        long totalBytes = 0; int methods = 0, types = 0;
        var allNames = new HashSet<string>(StringComparer.Ordinal);
        foreach (var path in paths)
        {
            var file = new FileInfo(path);
            Require(file.Exists && file.Length is > 0 and <= MaxAssemblyBytes && file.LinkTarget is null);
            totalBytes += file.Length; Require(totalBytes <= MaxTotalBytes);
            var bytes = File.ReadAllBytes(file.FullName); var identity = Digest(bytes);
            using var pe = new PEReader(new MemoryStream(bytes, writable: false));
            Require(pe.HasMetadata);
            var metadata = pe.GetMetadataReader(); Require(metadata.IsAssembly);
            var assembly = metadata.GetString(metadata.GetAssemblyDefinition().Name);
            bool asciiAssembly = Ascii(assembly), rootAssembly = assemblyIdentities.Count == 0;
            Require(allNames.Add(assembly)); assemblyIdentities.Add(identity);
            if (assembly.StartsWith("System.Private.", StringComparison.Ordinal)) assembly = "S.P." + assembly[15..];
            var prefix = Sanitize(assembly);
            var typeNames = new Dictionary<TypeDefinitionHandle, string>();
            var typeUsed = new HashSet<string>(StringComparer.Ordinal);
            string FullName(TypeDefinitionHandle handle, int depth = 0)
            {
                Require(depth < 64);
                var value = metadata.GetTypeDefinition(handle);
                var space = metadata.GetString(value.Namespace); var name = metadata.GetString(value.Name);
                var own = space.Length == 0 ? name : space + "." + name;
                return value.GetDeclaringType().IsNil ? own : FullName(value.GetDeclaringType(), depth + 1) + "_" + own;
            }
            bool GenericType(TypeDefinitionHandle handle, int depth = 0)
            {
                Require(depth < 64);
                var value = metadata.GetTypeDefinition(handle);
                return value.GetGenericParameters().Count > 0 ||
                    (!value.GetDeclaringType().IsNil && GenericType(value.GetDeclaringType(), depth + 1));
            }
            foreach (var handle in metadata.TypeDefinitions)
            {
                types++; Require(types <= 65536);
                typeNames[handle] = Unique(prefix + "_" + Sanitize(FullName(handle)), typeUsed);
            }
            foreach (var handle in metadata.TypeDefinitions)
            {
                var type = metadata.GetTypeDefinition(handle);
                var methodUsed = new HashSet<string>(StringComparer.Ordinal);
                foreach (var methodHandle in type.GetMethods())
                {
                    methods++; Require(methods <= MaxMethods);
                    var method = metadata.GetMethodDefinition(methodHandle);
                    var name = metadata.GetString(method.Name);
                    var nativeName = Unique(Sanitize(name), methodUsed);
                    var generic = GenericType(handle) || method.GetGenericParameters().Count > 0;
                    var signature = metadata.GetBlobBytes(method.Signature);
                    var token = MetadataTokens.GetToken(methodHandle);
                    var id = Digest(System.Text.Encoding.UTF8.GetBytes(identity + ":" + token)).Substring(7);
                    var symbol = FullName(handle) + "." + name;
                    // No system-module primitive abbreviations, generic
                    // instantiations, synthetic methods or fuzzy name matches.
                    string? mangled = generic || !asciiAssembly || !Ascii(FullName(handle)) || !Ascii(name)
                        || assembly.StartsWith("S.P.", StringComparison.Ordinal)
                        ? null : typeNames[handle] + "__" + nativeName;
                    var kind = name == ".cctor" ? "initialization" : name == ".ctor" ? "constructor" : "method";
                    var declaration = (method.Attributes & MethodAttributes.PinvokeImpl) != 0 ? "pinvoke" : "ordinary";
                    bool anchor = rootAssembly && mangled is not null && (method.Attributes & MethodAttributes.Static) != 0
                        && ExportAttribute(metadata, method);
                    queries.Add(new Query(id, identity, Digest(signature), symbol, mangled, kind, declaration, anchor));
                    // Preserve root mapping anchors, then the actual captured
                    // dependency assemblies. Generated SDK PInvokes in the root
                    // DLL must not crowd every transitive query out of the cap.
                    queries = queries.OrderBy(q => !q.RootAnchor)
                        .ThenBy(q => q.AssemblyDigest == assemblyIdentities[0]).ThenBy(q => q.Declaration != "pinvoke")
                        .ThenBy(q => q.Kind == "initialization" ? 0 : q.Kind == "constructor" ? 1 : 2)
                        .ThenBy(q => q.Symbol, StringComparer.Ordinal).ThenBy(q => q.Id, StringComparer.Ordinal)
                        .Take(MaxQueries).ToList();
                }
            }
        }
        var result = JsonSerializer.SerializeToUtf8Bytes(new {
            schemaVersion = "lsf.dotnet.compiler-queries.v1", sourceRevision = "8449ba666dd991e495d8363d9852f18eb86a1aa1",
            assemblies = assemblyIdentities, queries, omittedMethods = methods - queries.Count,
            methodsInspected = methods, typesInspected = types, assemblyBytesInspected = totalBytes,
            initializersExecuted = false
        }, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
        Require(result.Length <= 65536);
        File.WriteAllBytes(args[1], result); return 0;
    }
}
