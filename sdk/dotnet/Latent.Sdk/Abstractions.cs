namespace Latent.Sdk;

public sealed record ResourceBudget(
    ulong CpuFuel,
    ulong MemoryBytes,
    ulong? WallTimeLimitMillis,
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
    IReadOnlyList<ErrorDetail> Details);

public sealed record ErrorDetail(
    string Kind,
    IReadOnlyDictionary<string, string> Fields);

public sealed record DeclaredError(
    string Code,
    string Message,
    ReadOnlyMemory<byte> Payload,
    string MediaType,
    IReadOnlyDictionary<string, string> Metadata);

public sealed record InvocationReceipt(
    string ActivationId,
    string RevisionId,
    string ReleaseDigest,
    ulong RouteGeneration,
    BudgetConsumption Consumption);

public abstract record InvocationOutcome
{
    private InvocationOutcome() { }

    public sealed record Succeeded(InvokeResponse Response) : InvocationOutcome;

    public sealed record DeclaredFailure(
        InvocationReceipt Receipt,
        DeclaredError Error) : InvocationOutcome;

    public sealed record PlatformFailure(
        InvocationReceipt Receipt,
        global::Latent.Sdk.PlatformFailure Error) : InvocationOutcome;
}

public enum CancelDisposition
{
    Accepted,
    AlreadyTerminal,
    NotFound,
}

public sealed record CancelResponse(
    CancelDisposition Disposition,
    string? TerminalState);

public abstract record RetainedInvocationOutcome
{
    private RetainedInvocationOutcome() { }

    public sealed record Succeeded(
        string? CommittedStateVersion,
        IReadOnlyList<string> EffectIds,
        IReadOnlyDictionary<string, string> Metadata) : RetainedInvocationOutcome;

    public sealed record DeclaredFailure(DeclaredError Error) : RetainedInvocationOutcome;

    public sealed record PlatformFailure(
        global::Latent.Sdk.PlatformFailure Error) : RetainedInvocationOutcome;
}

public sealed record ActivationStatus(
    string ActivationId,
    string Phase,
    string? TerminalState,
    RetainedInvocationOutcome? TerminalOutcome,
    BudgetConsumption? FinalConsumption,
    ulong LastUpdatedUnixMillis,
    ulong? TerminalAtUnixMillis,
    IReadOnlyDictionary<string, string> Metadata);

public interface ILatentClient
{
    ValueTask<InvocationOutcome> InvokeAsync(
        InvokeRequest request,
        CancellationToken cancellationToken = default);

    ValueTask<CancelResponse> CancelAsync(
        string activationId,
        string reason,
        CancellationToken cancellationToken = default);

    ValueTask<ActivationStatus> GetActivationAsync(
        string activationId,
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
