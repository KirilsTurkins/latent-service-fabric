namespace Latent.Sdk;

public sealed record ResourceBudget(
    ulong CpuFuel,
    ulong MemoryBytes,
    ulong? WallDeadlineUnixMillis,
    uint ChildCalls,
    uint OutboundRequests,
    ulong StateReadBytes,
    ulong StateWriteBytes,
    ulong BlobReadBytes,
    ulong BlobWriteBytes,
    ulong LogBytes,
    uint EffectCount);

public sealed record BudgetConsumption(
    ulong CpuFuel,
    ulong PeakMemoryBytes,
    ulong WallTimeMicros,
    uint ChildCalls,
    uint OutboundRequests,
    ulong StateReadBytes,
    ulong StateWriteBytes,
    ulong BlobReadBytes,
    ulong BlobWriteBytes,
    ulong LogBytes,
    uint EffectCount);

public sealed record InvocationTarget(
    string Tenant,
    string Service,
    string Contract,
    string Function,
    string? Route);

public sealed record InvokeOptions(
    ulong? DeadlineUnixMillis,
    byte Priority,
    string? IdempotencyKey,
    ResourceBudget Budget,
    IReadOnlyDictionary<string, string> Metadata);

public sealed record InvokeRequest(
    InvocationTarget Target,
    ReadOnlyMemory<byte> Payload,
    string MediaType,
    InvokeOptions Options);

public sealed record InvokeResponse(
    string ActivationId,
    string RevisionId,
    string ReleaseDigest,
    ulong RouteGeneration,
    ReadOnlyMemory<byte> Payload,
    string MediaType,
    string? CommittedStateVersion,
    IReadOnlyList<string> EffectIds,
    BudgetConsumption Consumption,
    IReadOnlyDictionary<string, string> Metadata);

public sealed record PlatformFailure(
    string Code,
    string Message,
    bool Retryable,
    IReadOnlyDictionary<string, string> Details);

public interface ILatentClient
{
    ValueTask<InvokeResponse> InvokeAsync(
        InvokeRequest request,
        CancellationToken cancellationToken = default);

    ValueTask CancelAsync(
        string activationId,
        string reason,
        CancellationToken cancellationToken = default);
}

public interface IGuestContext
{
    string ActivationId { get; }
    string RootActivationId { get; }
    string? ParentActivationId { get; }
    ulong? DeadlineUnixMillis { get; }
    ResourceBudget RemainingBudget { get; }
    IReadOnlyDictionary<string, string> Metadata { get; }
}
