using System.Collections;
using System.Reflection;
using System.Text.Json;
using Google.Protobuf;
using Google.Protobuf.Reflection;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transport.Tests;

internal static partial class Program
{
    private static void SharedVectors()
    {
        DirectoryInfo? root = new(Directory.GetCurrentDirectory());
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "sdk/profile/fixtures.json"))) root = root.Parent;
        using JsonDocument fixtures = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(root!.FullName, "sdk/profile/fixtures.json")));
        FileDescriptor[] sources = [Latent.Control.V1.CommonReflection.Descriptor, Latent.Control.V1.PolicyReflection.Descriptor,
            Latent.Control.V1.CapabilityReflection.Descriptor, Latent.Control.V1.NodeReflection.Descriptor, Latent.Control.V1.ReleaseReflection.Descriptor, Latent.Invocation.V1.InvocationReflection.Descriptor];
        Dictionary<string, MessageDescriptor> messages = sources.SelectMany(source => source.MessageTypes).GroupBy(message => message.Name).ToDictionary(group => group.Key, group => group.First());
        int count = 0;
        foreach (JsonElement scenario in fixtures.RootElement.GetProperty("cases").EnumerateArray())
        {
            string name = scenario.GetProperty("type").GetString()!;
            if (!messages.TryGetValue(name, out MessageDescriptor? descriptor)) continue;
            Type type = typeof(Profile.IClientProfile).Assembly.GetType("Latent.Sdk.Profile." + name)!;
            object original = FixtureValue(type, scenario.GetProperty("value"))!;
            bool contradictory = scenario.TryGetProperty("response_error", out JsonElement error) && error.GetString() == "contradictory-oneof";
            try
            {
                var wire = (IMessage)Activator.CreateInstance(descriptor.ClrType)!;
                ProfileCodec.ToWire(original, wire);
                Check(!contradictory, "contradictory fixture was silently repaired");
                byte[] bytes = wire.ToByteArray();
                WireShape.Validate(bytes, descriptor, new(8 * 1024 * 1024, 8192, default));
                object result = ProfileCodec.FromWire(descriptor.Parser.ParseFrom(bytes), type);
                Check(JsonSerializer.Serialize(original, type) == JsonSerializer.Serialize(result, type), "wire fixture changed: " + scenario.GetProperty("name").GetString());
            }
            catch (FormatException) when (contradictory) { assertions++; }
            catch (Exception failure) { throw new InvalidOperationException("shared fixture failed: " + scenario.GetProperty("name").GetString(), failure); }
            count++;
        }
        var legacy = new Profile.CapabilityResourceUsage("node", new Dictionary<string, ulong>
            { ["stream_owners"] = 2, ["stream_connections"] = 2 }, Array.Empty<string>());
        var absent = (Latent.Control.V1.CapabilityResourceUsage)ProfileCodec.ToWire(legacy, new Latent.Control.V1.CapabilityResourceUsage());
        Check(!absent.HasStreamQuarantinedConnections, "legacy constructor manufactured zero");
        Check(((Profile.CapabilityResourceUsage)ProfileCodec.FromWire(absent, typeof(Profile.CapabilityResourceUsage)))
            .StreamQuarantinedConnections is null, "older payload lost absence");
        var zero = legacy with { StreamQuarantinedConnections = 0 };
        var zeroWire = (Latent.Control.V1.CapabilityResourceUsage)ProfileCodec.ToWire(zero, new Latent.Control.V1.CapabilityResourceUsage());
        Check(zeroWire.HasStreamQuarantinedConnections, "observed zero lost presence");
        Check(((Profile.CapabilityResourceUsage)ProfileCodec.FromWire(zeroWire, typeof(Profile.CapabilityResourceUsage)))
            .StreamQuarantinedConnections == 0, "observed zero changed during decoding");
        var retained = legacy with { StreamQuarantinedConnections = 1 };
        var retainedWire = (Latent.Control.V1.CapabilityResourceUsage)ProfileCodec.ToWire(retained, new Latent.Control.V1.CapabilityResourceUsage());
        Check(retainedWire.HasStreamQuarantinedConnections, "retained count lost presence");
        Check(((Profile.CapabilityResourceUsage)ProfileCodec.FromWire(retainedWire, typeof(Profile.CapabilityResourceUsage)))
            .StreamQuarantinedConnections == 1, "retained count changed during decoding");
        Check(count == 64, "not all shared protobuf fixtures executed");
        Console.WriteLine($"PASS SharedVectors: {count} authoritative protobuf cases");
    }

    private static object? FixtureValue(Type target, JsonElement source)
    {
        bool missing = source.ValueKind is JsonValueKind.Undefined or JsonValueKind.Null;
        Type? optional = Nullable.GetUnderlyingType(target);
        if (optional is not null) return missing ? null : FixtureValue(optional, source);
        if (target == typeof(string)) return missing ? "" : source.GetString();
        if (target == typeof(ReadOnlyMemory<byte>)) return new ReadOnlyMemory<byte>(missing ? [] : source.GetBytesFromBase64());
        if (target == typeof(ulong)) return missing ? 0UL : Profile.UnsignedDecimal.Parse(source.GetString()!);
        if (target == typeof(uint)) return missing ? 0U : source.GetUInt32();
        if (target == typeof(bool)) return !missing && source.GetBoolean();
        if (target.IsValueType) return Activator.CreateInstance(target, missing ? 0 : source.GetInt32());
        if (target.IsGenericType && target.GetGenericTypeDefinition() == typeof(IReadOnlyDictionary<,>))
        {
            Type[] types = target.GetGenericArguments();
            var result = (IDictionary)Activator.CreateInstance(typeof(Dictionary<,>).MakeGenericType(types))!;
            if (!missing) foreach (JsonProperty property in source.EnumerateObject()) result.Add(property.Name, FixtureValue(types[1], property.Value));
            return result;
        }
        if (target.IsGenericType && target.GetGenericTypeDefinition() == typeof(IReadOnlyList<>))
        {
            Type element = target.GetGenericArguments()[0];
            var result = (IList)Activator.CreateInstance(typeof(List<>).MakeGenericType(element))!;
            if (!missing) foreach (JsonElement item in source.EnumerateArray()) result.Add(FixtureValue(element, item));
            return result;
        }
        if (missing) return null;
        ConstructorInfo[] constructors = target.GetConstructors();
        int arity = constructors.Max(candidate => candidate.GetParameters().Length);
        ConstructorInfo constructor = constructors.Single(candidate => candidate.GetParameters().Length == arity);
        object?[] values = constructor.GetParameters().Select(parameter =>
        {
            string name = JsonNamingPolicy.SnakeCaseLower.ConvertName(parameter.Name!);
            bool present = source.TryGetProperty(name, out JsonElement value);
            if (!present && parameter.ParameterType == typeof(string) && new NullabilityInfoContext().Create(parameter).ReadState == NullabilityState.Nullable)
                return null;
            return FixtureValue(parameter.ParameterType, value);
        }).ToArray();
        return constructor.Invoke(values);
    }
}
