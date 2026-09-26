using System.Net;
using System.Net.Sockets;
using Latent.Sdk.Profile;

namespace Latent.Sdk.Transport;

public sealed class ClientOptions
{
    public required string Endpoint { get; init; }
    public required string BearerToken { get; init; }
    public TimeSpan ConnectTimeout { get; init; } = TimeSpan.FromSeconds(2);
    public TimeSpan DefaultTimeout { get; init; } = TimeSpan.FromSeconds(5);
    public int MaxInFlight { get; init; } = 8;
    public int ReservedRecovery { get; init; } = 2;
    public int MaxQueued { get; init; } = 8;
    public int MaxRequestBytes { get; init; } = 1024 * 1024;
    public int MaxResponseBytes { get; init; } = 1024 * 1024;
    public int MaxHeaderBytes { get; init; } = 16 * 1024;
    public int MaxGraphBytes { get; init; } = 8 * 1024 * 1024;
    public int MaxGraphNodes { get; init; } = 8192;

    public override string ToString() => "Latent bounded .NET client configuration (redacted)";

    internal (Uri Uri, IPEndPoint Address) Validate()
    {
        if (Environment.Version.Major != 8 || Environment.Version < new Version(8, 0, 31) || string.IsNullOrEmpty(Endpoint) || Endpoint.Length > 256 ||
            !Uri.TryCreate(Endpoint, UriKind.Absolute, out Uri? endpoint) || endpoint.Scheme != "http" ||
            !IPAddress.TryParse(endpoint.DnsSafeHost, out IPAddress? address) || !IPAddress.IsLoopback(address) ||
            (address.AddressFamily == AddressFamily.InterNetworkV6 && address.ScopeId != 0) || endpoint.Port < 1)
            throw Invalid();
        string authority = address.AddressFamily == AddressFamily.InterNetworkV6 ? $"[{address}]:{endpoint.Port}" : $"{address}:{endpoint.Port}";
        if (Endpoint != "http://" + authority || string.IsNullOrEmpty(BearerToken) || BearerToken.Length > 512 ||
            BearerToken.Any(character => character < '!' || character > '~') ||
            ConnectTimeout <= TimeSpan.Zero || ConnectTimeout > TimeSpan.FromSeconds(30) ||
            DefaultTimeout <= TimeSpan.Zero || DefaultTimeout > TimeSpan.FromSeconds(30) ||
            MaxInFlight is < 2 or > 32 || ReservedRecovery < 1 || ReservedRecovery >= MaxInFlight || MaxQueued is < 0 or > 64 ||
            MaxRequestBytes is < 1 or > 4 * 1024 * 1024 || MaxResponseBytes is < 1 or > 4 * 1024 * 1024 ||
            MaxHeaderBytes is < 1024 or > 32 * 1024 || MaxHeaderBytes % 1024 != 0 ||
            MaxGraphBytes is < 1024 or > 32 * 1024 * 1024 || MaxGraphNodes is < 32 or > 16384)
            throw Invalid();
        return (endpoint, new IPEndPoint(address, endpoint.Port));
    }

    internal static ClientException Invalid() => Failure(FailureCategory.InvalidRequest, "invalid bounded loopback client configuration");

    internal static ClientException Failure(FailureCategory category, string message) => new(new ClientFailure(
        category, message, null, null, false, OutcomeKnowledge.NotDispatched, new(null, null), null, null, null, null));
}
