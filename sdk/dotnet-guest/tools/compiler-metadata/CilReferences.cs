// Passive ECMA-335 method-reference/forwarder resolution. No Assembly.Load,
// reflection over application types, initializer, or application IL execution.
using System.Buffers.Binary;
using System.Reflection;
using System.Reflection.Emit;
using System.Reflection.Metadata;
using System.Reflection.Metadata.Ecma335;
using System.Reflection.PortableExecutable;
using System.Security.Cryptography;

internal static class CilReferences
{
    private const int MaxMethods = 262144, MaxTypes = 65536, MaxEdges = 65536;
    private const int MaxBodyBytes = 262144, MaxTotalBodyBytes = 8 * 1024 * 1024;
    private static string Hash(byte[] raw) => "sha256:" + Convert.ToHexStringLower(SHA256.HashData(raw));
    private static string MethodId(string assembly, MethodDefinitionHandle method) =>
        Hash(System.Text.Encoding.UTF8.GetBytes(assembly + ":" + MetadataTokens.GetToken(method)))[7..];
    private static void Require(bool value) { if (!value) throw new InvalidDataException("compiler-cil-input-invalid"); }
    private sealed class Module : IDisposable
    {
        internal readonly byte[] Bytes;
        internal readonly PEReader Pe;
        internal readonly MetadataReader Metadata;
        internal readonly string Digest, Identity;
        internal readonly Dictionary<string, TypeDefinitionHandle> Types = new(StringComparer.Ordinal);
        internal readonly Dictionary<string, string> Forwarders = new(StringComparer.Ordinal);
        internal readonly Dictionary<(TypeDefinitionHandle, string, string), MethodDefinitionHandle> Methods = new();
        internal Module(byte[] bytes)
        {
            Bytes = bytes; Digest = Hash(bytes); Pe = new PEReader(new MemoryStream(bytes, writable: false));
            Metadata = Pe.GetMetadataReader(); Require(Metadata.IsAssembly);
            var assembly = Metadata.GetAssemblyDefinition();
            Identity = AssemblyIdentity(Metadata, Metadata.GetString(assembly.Name), assembly.Version,
                assembly.Culture, assembly.PublicKey, assembly.Flags);
        }
        public void Dispose() => Pe.Dispose();
    }
    private static string AssemblyIdentity(MetadataReader reader, string name, Version version,
        StringHandle culture, BlobHandle key, AssemblyFlags flags)
    {
        var bytes = reader.GetBlobBytes(key);
        // This is the ECMA assembly-reference token, NOT an authenticity hash.
        // Whole original assembly SHA-256 remains the material identity.
        if ((flags & AssemblyFlags.PublicKey) != 0 && bytes.Length != 0)
            bytes = SHA1.HashData(bytes)[^8..].Reverse().ToArray();
        return name + "|" + version + "|" + reader.GetString(culture) + "|" + Convert.ToHexStringLower(bytes);
    }
    private static string ReferenceIdentity(MetadataReader reader, AssemblyReferenceHandle handle)
    {
        var reference = reader.GetAssemblyReference(handle);
        return AssemblyIdentity(reader, reader.GetString(reference.Name), reference.Version,
            reference.Culture, reference.PublicKeyOrToken, reference.Flags);
    }
    private static string? TypeName(MetadataReader reader, TypeDefinitionHandle handle)
    {
        var type = reader.GetTypeDefinition(handle);
        if (!type.GetDeclaringType().IsNil || type.GetGenericParameters().Count != 0) return null;
        return reader.GetString(type.Namespace) + "." + reader.GetString(type.Name);
    }
    private static bool PrimitiveSignature(byte[] signature)
    {
        // No encoded type handles/generic instantiations: byte equality then
        // has the same meaning across the referenced and defining modules.
        if (signature.Length < 3 || (signature[0] & ~0x20) != 0 || signature[1] > 32) return false;
        if (signature.Length != signature[1] + 3) return false;
        for (int at = 2; at < signature.Length; at++)
            if (signature[at] is not (>= 0x01 and <= 0x0e) and not 0x18 and not 0x19 and not 0x1c
                || at > 2 && signature[at] == 0x01) return false;
        return true;
    }
    private static (Module Module, TypeDefinitionHandle Type)? ResolveType(Module origin, EntityHandle handle,
        Dictionary<string, Module> modules)
    {
        if (handle.Kind == HandleKind.TypeDefinition)
            return (origin, (TypeDefinitionHandle)handle);
        if (handle.Kind != HandleKind.TypeReference) return null;
        var reference = origin.Metadata.GetTypeReference((TypeReferenceHandle)handle);
        if (reference.ResolutionScope.Kind != HandleKind.AssemblyReference) return null;
        string identity = ReferenceIdentity(origin.Metadata, (AssemblyReferenceHandle)reference.ResolutionScope);
        string name = origin.Metadata.GetString(reference.Namespace) + "." + origin.Metadata.GetString(reference.Name);
        var seen = new HashSet<string>(StringComparer.Ordinal);
        for (int depth = 0; depth < 32; depth++)
        {
            if (!seen.Add(identity) || !modules.TryGetValue(identity, out var selected)) return null;
            if (selected.Types.TryGetValue(name, out var type)) return (selected, type);
            if (!selected.Forwarders.TryGetValue(name, out var next)) return null;
            identity = next;
        }
        return null;
    }
    private static (string Id, string Assembly, string Signature)? ResolveMethod(Module origin, int token,
        Dictionary<string, Module> modules)
    {
        var handle = MetadataTokens.EntityHandle(token);
        if (handle.Kind == HandleKind.MethodDefinition)
        {
            var selected = (MethodDefinitionHandle)handle;
            return (MethodId(origin.Digest, selected), origin.Digest,
                Hash(origin.Metadata.GetBlobBytes(origin.Metadata.GetMethodDefinition(selected).Signature)));
        }
        if (handle.Kind != HandleKind.MemberReference) return null;
        var reference = origin.Metadata.GetMemberReference((MemberReferenceHandle)handle);
        if (reference.GetKind() != MemberReferenceKind.Method) return null;
        var signature = origin.Metadata.GetBlobBytes(reference.Signature);
        if (!PrimitiveSignature(signature)) return null;
        var resolved = ResolveType(origin, reference.Parent, modules);
        if (resolved is null) return null;
        var (module, type) = resolved.Value;
        var name = origin.Metadata.GetString(reference.Name);
        var signatureDigest = Hash(signature);
        return module.Methods.TryGetValue((type, name, signatureDigest), out var found)
            ? (MethodId(module.Digest, found), module.Digest, signatureDigest) : null;
    }
    internal sealed record Edge(string SourceId, string BodyDigest, int Offset, string Operation,
        string TargetId, string TargetAssemblyDigest, string TargetSignatureDigest);
    internal sealed record ApiBody(string Api, string Id, string AssemblyDigest, string SignatureDigest,
        string BodyDigest, int MetadataToken);
    internal sealed record Result(IReadOnlyList<Edge> Edges, int UnknownReferences, int OmittedEdges,
        int BodiesInspected, long BodyBytesInspected, HashSet<string> CorelibTargets, IReadOnlyList<ApiBody> ApiBodies);

    internal static Result Read(string[] paths, string corelibDigest, int sourceAssemblies)
    {
        Require(sourceAssemblies > 0 && sourceAssemblies <= paths.Length && paths.Length <= 512);
        var owned = new List<Module>();
        try
        {
            long total = 0; int types = 0, methods = 0, forwards = 0;
            var modules = new Dictionary<string, Module>(StringComparer.Ordinal);
            foreach (var path in paths)
            {
                var file = new FileInfo(path);
                Require(file.Exists && file.LinkTarget is null && file.Length is > 0 and <= 16 * 1024 * 1024);
                total += file.Length; Require(total <= 64 * 1024 * 1024);
                var module = new Module(File.ReadAllBytes(path)); owned.Add(module);
                if (modules.TryGetValue(module.Identity, out var canonical))
                {
                    // Actual ILC inputs may alias the SAME complete assembly
                    // through different original paths. Identity alone never
                    // permits two different implementations to resolve here.
                    if (!canonical.Bytes.AsSpan().SequenceEqual(module.Bytes))
                        throw new InvalidDataException("compiler-cil-identity-image-collision "
                            + canonical.Digest + " " + module.Digest);
                    continue;
                }
                modules.Add(module.Identity, module);
                foreach (var type in module.Metadata.TypeDefinitions)
                {
                    Require(++types <= MaxTypes);
                    var name = TypeName(module.Metadata, type);
                    if (name is not null) Require(module.Types.TryAdd(name, type));
                }
                foreach (var method in module.Metadata.MethodDefinitions)
                {
                    Require(++methods <= MaxMethods);
                    var declaration = module.Metadata.GetMethodDefinition(method);
                    var signature = module.Metadata.GetBlobBytes(declaration.Signature);
                    if (declaration.GetGenericParameters().Count != 0 || !PrimitiveSignature(signature)) continue;
                    Require(module.Methods.TryAdd((declaration.GetDeclaringType(), module.Metadata.GetString(declaration.Name),
                        Hash(signature)), method));
                }
                foreach (var type in module.Metadata.ExportedTypes)
                {
                    Require(++forwards <= MaxTypes);
                    var forward = module.Metadata.GetExportedType(type);
                    if ((forward.Attributes & (TypeAttributes)0x00200000) == 0
                        || forward.Implementation.Kind != HandleKind.AssemblyReference) continue;
                    var name = module.Metadata.GetString(forward.Namespace) + "." + module.Metadata.GetString(forward.Name);
                    Require(module.Forwarders.TryAdd(name,
                        ReferenceIdentity(module.Metadata, (AssemblyReferenceHandle)forward.Implementation)));
                }
            }
            var core = modules.Values.Where(module => module.Digest == corelibDigest).ToArray();
            Require(core.Length == 1 && core[0].Metadata.GetString(core[0].Metadata.GetAssemblyDefinition().Name)
                == "System.Private.CoreLib");
            var opcodes = new Dictionary<ushort, OpCode>();
            foreach (var field in typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static))
            {
                if (field.FieldType != typeof(OpCode)) continue;
                var opcode = (OpCode)field.GetValue(null)!;
                ushort key = unchecked((ushort)opcode.Value);
                if (!opcodes.TryAdd(key, opcode)) Require(opcodes[key].OperandType == opcode.OperandType);
            }
            var edges = new List<Edge>(); var targets = new HashSet<string>(StringComparer.Ordinal);
            int unknown = 0, omitted = 0, bodies = 0, inspectedEdges = 0; long bodyBytes = 0;
            var apiBodies = new List<ApiBody>();
            // A finite API implementation mapping, not an application/package
            // selector. The actual selected CoreLib and exact signature own it.
            if (core[0].Types.TryGetValue("System.IO.Path", out var pathType))
            foreach (var handle in core[0].Metadata.GetTypeDefinition(pathType).GetMethods())
            {
                var method = core[0].Metadata.GetMethodDefinition(handle);
                var signature = core[0].Metadata.GetBlobBytes(method.Signature);
                if (core[0].Metadata.GetString(method.Name) != "GetTempFileName"
                    || !signature.AsSpan().SequenceEqual(new byte[] { 0x00, 0x00, 0x0e })
                    || method.RelativeVirtualAddress == 0) continue;
                var il = core[0].Pe.GetMethodBody(method.RelativeVirtualAddress).GetILBytes() ?? Array.Empty<byte>();
                Require(il.Length <= MaxBodyBytes && apiBodies.Count == 0);
                bodyBytes += il.Length; bodies++;
                apiBodies.Add(new ApiBody("System.IO.Path.GetTempFileName", MethodId(corelibDigest, handle),
                    corelibDigest, Hash(signature), Hash(il), MetadataTokens.GetToken(handle)));
            }
            var apiTargets = apiBodies.Select(row => row.Id).ToHashSet(StringComparer.Ordinal);
            // Keep ALL original input positions in owned. Deduplicate only
            // inside the original source prefix, never before Take: otherwise
            // an alias could move a reference assembly into the source set.
            foreach (var module in owned.Take(sourceAssemblies).DistinctBy(module => module.Digest))
            foreach (var handle in module.Metadata.MethodDefinitions)
            {
                var method = module.Metadata.GetMethodDefinition(handle);
                if (method.RelativeVirtualAddress == 0 || (method.ImplAttributes & MethodImplAttributes.CodeTypeMask) != MethodImplAttributes.IL)
                    continue;
                var il = module.Pe.GetMethodBody(method.RelativeVirtualAddress).GetILBytes() ?? Array.Empty<byte>();
                if (il.Length > MaxBodyBytes || bodyBytes + il.Length > MaxTotalBodyBytes) { unknown++; continue; }
                bodyBytes += il.Length; bodies++;
                var bodyDigest = Hash(il);
                for (int at = 0; at < il.Length;)
                {
                    int offset = at; ushort opcode = il[at++];
                    if (opcode == 0xfe) { Require(at < il.Length); opcode = (ushort)(0xfe00 | il[at++]); }
                    Require(opcodes.TryGetValue(opcode, out var instruction));
                    int bytes = instruction.OperandType switch {
                        OperandType.InlineNone => 0,
                        OperandType.ShortInlineBrTarget or OperandType.ShortInlineI or OperandType.ShortInlineVar => 1,
                        OperandType.InlineVar => 2,
                        OperandType.InlineI8 or OperandType.InlineR => 8,
                        OperandType.InlineSwitch => -1,
                        OperandType.InlineBrTarget or OperandType.InlineField or OperandType.InlineI or OperandType.InlineMethod
                            or OperandType.InlineSig or OperandType.InlineString or OperandType.InlineTok or OperandType.InlineType
                            or OperandType.ShortInlineR => 4,
                        _ => throw new InvalidDataException("compiler-cil-input-invalid") };
                    if (bytes < 0)
                    {
                        Require(il.Length - at >= 4);
                        int count = BinaryPrimitives.ReadInt32LittleEndian(il.AsSpan(at, 4));
                        Require(count >= 0 && count <= 65536); bytes = checked(4 + count * 4);
                    }
                    Require(bytes <= il.Length - at);
                    if (opcode is 0x27 or 0x29) unknown++; // jmp/calli are not static call proofs.
                    if (opcode is 0x28 or 0x6f or 0x73 or 0xfe06 or 0xfe07)
                    {
                        Require(bytes == 4 && ++inspectedEdges <= MaxEdges);
                        var target = ResolveMethod(module, BinaryPrimitives.ReadInt32LittleEndian(il.AsSpan(at, 4)), modules);
                        if (target is null) unknown++;
                        else
                        {
                            if (target.Value.Assembly == corelibDigest) targets.Add(target.Value.Id);
                            edges.Add(new Edge(MethodId(module.Digest, handle), bodyDigest, offset,
                                instruction.Name!, target.Value.Id, target.Value.Assembly, target.Value.Signature));
                            // Addressable callbacks first, then current CoreLib
                            // operands; remaining omissions stay explicit.
                            edges = edges.OrderBy(edge => !apiTargets.Contains(edge.TargetId))
                                .ThenBy(edge => edge.Operation is not ("ldftn" or "ldvirtftn"))
                                .ThenBy(edge => edge.TargetAssemblyDigest != corelibDigest)
                                .ThenBy(edge => edge.SourceId, StringComparer.Ordinal).ThenBy(edge => edge.Offset)
                                .Take(65).ToList();
                            if (edges.Count == 65)
                            {
                                // A real selected-API operand is mandatory,
                                // never silently replaced by an absence claim.
                                Require(!apiTargets.Contains(edges[64].TargetId));
                                edges.RemoveAt(64); omitted++;
                            }
                        }
                    }
                    at += bytes;
                }
            }
            return new Result(edges, unknown, omitted, bodies, bodyBytes, targets, apiBodies);
        }
        finally { foreach (var module in owned) module.Dispose(); }
    }
}
