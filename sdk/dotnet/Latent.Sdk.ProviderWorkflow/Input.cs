using System.Net;
using System.Text;
using System.Text.Json;
using Latent.Sdk.Transport;
using Profile = Latent.Sdk.Profile;

namespace Latent.Examples;

internal sealed record Target(string Service, string Route, string Contract, string Function, string Publication, string ComponentDigest);

internal sealed class Input
{
    internal const string MediaType = "application/vnd.latent.wit-values.v1+json";
    internal string Endpoint { get; }
    internal string Tenant { get; }
    internal string Control { get; }
    internal string Upstream { get; }
    internal string PolicyDocument { get; }
    internal IReadOnlyDictionary<string, Target> Targets { get; }
    private readonly string bearer;

    internal Input(string path)
    {
        Require(OperatingSystem.IsLinux() && Path.IsPathFullyQualified(path), "protected-linux-input-required");
        Private(path, false);
        string directory = Path.GetDirectoryName(path)!;
        Private(directory, true);
        using JsonDocument document = JsonDocument.Parse(Read(path, 65536), new JsonDocumentOptions { MaxDepth = 10 });
        JsonElement root = document.RootElement;
        Shape(root, "schemaVersion", "language", "endpoint", "tenant", "credentialFile", "controlDirectory", "upstreamUrl", "targets", "policyDocument");
        Require(Field(root, "schemaVersion") == "latent.sdk.provider.workflow.input.v1" && Field(root, "language") == "dotnet", "input-profile");
        Endpoint = Field(root, "endpoint");
        Tenant = Field(root, "tenant");
        Require(Uri.TryCreate(Endpoint, UriKind.Absolute, out Uri? endpoint) && endpoint.Scheme == "http" &&
            IPAddress.TryParse(endpoint.DnsSafeHost, out IPAddress? address) && IPAddress.IsLoopback(address), "numeric-loopback-endpoint");
        string credential = Field(root, "credentialFile", 4096);
        Control = Field(root, "controlDirectory", 4096);
        Require(Path.IsPathFullyQualified(credential) && Path.GetDirectoryName(credential) == directory &&
            Path.GetFullPath(Control) == Path.Combine(Path.GetDirectoryName(directory)!, "control"), "protected-input-paths");
        Private(credential, false);
        Private(Control, true);
        byte[] token = Read(credential, 512);
        Require(token.Length != 0 && token.All(value => value is >= 33 and <= 126), "credential-shape");
        bearer = Encoding.ASCII.GetString(token);
        Upstream = Field(root, "upstreamUrl");
        Require(Uri.TryCreate(Upstream, UriKind.Absolute, out Uri? upstream) && upstream.Scheme == "http" &&
            upstream.Host == "localhost" && upstream.Port > 0 && Upstream == $"http://localhost:{upstream.Port}/allowed", "provider-target");
        PolicyDocument = Field(root, "policyDocument", 16384);
        using JsonDocument policy = JsonDocument.Parse(PolicyDocument, new JsonDocumentOptions { MaxDepth = 4 });
        Shape(policy.RootElement, "formatVersion", "tenant", "rules");
        Require(policy.RootElement.GetProperty("formatVersion").GetInt32() == 1 && Field(policy.RootElement, "tenant") == Tenant &&
            policy.RootElement.GetProperty("rules").ValueKind == JsonValueKind.Array && policy.RootElement.GetProperty("rules").GetArrayLength() == 0,
            "non-granting-policy-required");
        JsonElement targets = root.GetProperty("targets");
        Shape(targets, "http", "blob", "callee");
        var parsed = new Dictionary<string, Target>();
        foreach (string name in new[] { "http", "blob", "callee" })
        {
            JsonElement selected = targets.GetProperty(name);
            Shape(selected, "service", "route", "contract", "function", "publication", "componentDigest");
            parsed.Add(name, new(Field(selected, "service"), Field(selected, "route"), Field(selected, "contract"),
                Field(selected, "function"), Field(selected, "publication"), Field(selected, "componentDigest")));
        }
        Targets = parsed;
    }

    public override string ToString() => "Latent provider workflow input (redacted)";

    internal ClientOptions Options(bool wrongCredential = false, bool limited = false) => new()
    {
        Endpoint = Endpoint, BearerToken = wrongCredential ? "LSF-NOT-A-VALID-CREDENTIAL" : bearer,
        DefaultTimeout = TimeSpan.FromSeconds(3), ConnectTimeout = TimeSpan.FromSeconds(2),
        MaxInFlight = 4, ReservedRecovery = 2, MaxQueued = 2, MaxResponseBytes = limited ? 8 : 1024 * 1024
    };

    internal Profile.InvokeRequest Request(string provider, string identity, string? function = null, string? tenant = null, ulong? deadline = null)
    {
        Target target = Targets[provider];
        bool callee = provider == "callee";
        ReadOnlyMemory<byte> payload = callee ? "[]"u8.ToArray() :
            JsonSerializer.SerializeToUtf8Bytes(new object[] { 0, provider == "http" ? Upstream : "", "0" });
        return new(identity, null, null, new(tenant ?? Tenant, target.Service, target.Contract, function ?? target.Function, target.Route),
            payload, MediaType, deadline, 0, null,
            new(function == "spin" ? 1000UL : callee ? 100_000_000UL : 10_000_000_000UL, callee ? 4194304UL : 16777216UL,
                0, callee ? 0U : 8U, 0, 0, provider == "blob" ? 65536UL : 0UL, provider == "blob" ? 65536UL : 0UL, 0, 0, 5000),
            new Dictionary<string, string>());
    }

    internal void Receipt(Profile.InvokeResponse response, string provider, string identity)
    {
        Target target = Targets[provider];
        Require(response.ActivationId == identity && response.PublicationId == target.Publication && response.ReleaseDigest == target.ComponentDigest &&
            response.RevisionId.Length != 0 && response.RouteGeneration != 0 && response.Consumption is not null, "invocation-receipt");
    }

    internal static ulong Guest(Profile.InvokeResponse response)
    {
        Require(response.Success is not null && response.Success.MediaType == MediaType, "typed-guest-success");
        using JsonDocument value = JsonDocument.Parse(response.Success!.Payload, new JsonDocumentOptions { MaxDepth = 4 });
        Require(value.RootElement.ValueKind == JsonValueKind.Array && value.RootElement.GetArrayLength() == 1 &&
            value.RootElement[0].ValueKind == JsonValueKind.String, "canonical-unsigned-guest-result");
        return Profile.UnsignedDecimal.Parse(value.RootElement[0].GetString()!);
    }

    internal static byte[] Read(string path, int maximum)
    {
        using var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        Require(source.Length <= maximum, "input-byte-bound");
        byte[] data = new byte[checked((int)source.Length)];
        source.ReadExactly(data);
        Require(source.ReadByte() == -1, "input-byte-bound");
        return data;
    }

    internal static void Private(string path, bool directory)
    {
        FileAttributes attributes = File.GetAttributes(path);
        Require((attributes & FileAttributes.ReparsePoint) == 0 && ((attributes & FileAttributes.Directory) != 0) == directory,
            "private-input-kind");
        if (!OperatingSystem.IsLinux()) throw new InvalidOperationException("protected-linux-input-required");
        UnixFileMode mode = File.GetUnixFileMode(path);
        const UnixFileMode shared = UnixFileMode.GroupRead | UnixFileMode.GroupWrite | UnixFileMode.GroupExecute |
            UnixFileMode.OtherRead | UnixFileMode.OtherWrite | UnixFileMode.OtherExecute;
        Require((mode & shared) == 0 && (mode & UnixFileMode.UserRead) != 0, "private-input-permissions");
    }

    private static void Shape(JsonElement value, params string[] fields)
    {
        Require(value.ValueKind == JsonValueKind.Object, "input-object");
        string[] actual = value.EnumerateObject().Select(property => property.Name).ToArray();
        Require(actual.Length == fields.Length && actual.Distinct().Count() == actual.Length && fields.All(actual.Contains), "input-object-fields");
    }

    private static string Field(JsonElement value, string name, int maximum = 256)
    {
        JsonElement field = value.GetProperty(name);
        Require(field.ValueKind == JsonValueKind.String, "input-string");
        string text = field.GetString()!;
        Require(text.Length is > 0 && text.Length <= maximum && !text.Any(character => char.IsControl(character)), "input-string-bound");
        return text;
    }

    internal static void Require(bool condition, string reason)
    {
        if (!condition) throw new InvalidOperationException(reason);
    }
}
