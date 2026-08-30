namespace Latent.Sdk;

/// <summary>Specifies the resources available to an activation.</summary>
/// <param name="CpuFuel">The maximum CPU fuel available to the activation.</param>
/// <param name="MemoryBytes">The maximum memory, in bytes, available to the activation.</param>
/// <param name="WallTimeLimitMillis">The optional relative wall-time limit, in milliseconds, enforced from activation start.</param>
/// <param name="ChildCalls">The maximum number of child calls available to the activation.</param>
/// <param name="OutboundRequests">The maximum number of outbound requests available to the activation.</param>
/// <param name="StateReadBytes">The maximum state bytes that the activation may read.</param>
/// <param name="StateWriteBytes">The maximum state bytes that the activation may write.</param>
/// <param name="BlobReadBytes">The maximum blob bytes that the activation may read.</param>
/// <param name="BlobWriteBytes">The maximum blob bytes that the activation may write.</param>
/// <param name="LogBytes">The maximum log bytes that the activation may emit.</param>
/// <param name="EffectCount">The maximum number of effects that the activation may create.</param>
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

/// <summary>Describes the resources consumed by an activation.</summary>
/// <param name="CpuFuel">The CPU fuel consumed by the activation.</param>
/// <param name="PeakMemoryBytes">The peak memory, in bytes, used by the activation.</param>
/// <param name="WallTimeMicros">The activation wall-clock duration, in microseconds.</param>
/// <param name="ChildCalls">The number of child calls made by the activation.</param>
/// <param name="OutboundRequests">The number of outbound requests made by the activation.</param>
/// <param name="StateReadBytes">The state bytes read by the activation.</param>
/// <param name="StateWriteBytes">The state bytes written by the activation.</param>
/// <param name="BlobReadBytes">The blob bytes read by the activation.</param>
/// <param name="BlobWriteBytes">The blob bytes written by the activation.</param>
/// <param name="LogBytes">The log bytes emitted by the activation.</param>
/// <param name="EffectCount">The number of effects created by the activation.</param>
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

/// <summary>Identifies the function to invoke.</summary>
/// <param name="Tenant">The tenant that owns the target service.</param>
/// <param name="Service">The target service name.</param>
/// <param name="Contract">The target service contract.</param>
/// <param name="Function">The target function name.</param>
/// <param name="Route">The optional route used to select the target.</param>
public sealed record InvocationTarget(
    string Tenant,
    string Service,
    string Contract,
    string Function,
    string? Route);

/// <summary>Specifies options for an invocation.</summary>
/// <param name="DeadlineUnixMillis">The optional absolute Unix-time invocation deadline, in milliseconds.</param>
/// <param name="Priority">The invocation priority.</param>
/// <param name="IdempotencyKey">The optional key used to identify equivalent invocations.</param>
/// <param name="Budget">The resource budget requested for the invocation.</param>
/// <param name="Metadata">Additional invocation metadata.</param>
public sealed record InvokeOptions(
    ulong? DeadlineUnixMillis,
    byte Priority,
    string? IdempotencyKey,
    ResourceBudget Budget,
    IReadOnlyDictionary<string, string> Metadata);

/// <summary>Represents a request to invoke a target function.</summary>
/// <param name="Target">The function to invoke.</param>
/// <param name="Payload">The invocation payload.</param>
/// <param name="MediaType">The media type of <paramref name="Payload"/>.</param>
/// <param name="Options">The invocation options.</param>
public sealed record InvokeRequest(
    InvocationTarget Target,
    ReadOnlyMemory<byte> Payload,
    string MediaType,
    InvokeOptions Options);

/// <summary>Represents a successful invocation response.</summary>
/// <param name="ActivationId">The identifier of the completed activation.</param>
/// <param name="RevisionId">The revision that handled the invocation.</param>
/// <param name="ReleaseDigest">The digest of the release that handled the invocation.</param>
/// <param name="RouteGeneration">The route generation used for the invocation.</param>
/// <param name="Payload">The response payload.</param>
/// <param name="MediaType">The media type of <paramref name="Payload"/>.</param>
/// <param name="CommittedStateVersion">The optional committed state version.</param>
/// <param name="EffectIds">The identifiers of effects created by the invocation.</param>
/// <param name="Consumption">The resources consumed by the invocation.</param>
/// <param name="Metadata">Additional response metadata.</param>
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

/// <summary>Describes a failure returned by the platform.</summary>
/// <param name="Code">The platform-defined failure code.</param>
/// <param name="Message">A human-readable description of the failure.</param>
/// <param name="Retryable">Whether retrying the operation may succeed.</param>
/// <param name="Details">Structured failure details.</param>
public sealed record PlatformFailure(
    string Code,
    string Message,
    bool Retryable,
    IReadOnlyList<ErrorDetail> Details);

/// <summary>Provides one structured platform-error detail.</summary>
/// <param name="Kind">The detail kind.</param>
/// <param name="Fields">The bounded fields carried by the detail.</param>
public sealed record ErrorDetail(
    string Kind,
    IReadOnlyDictionary<string, string> Fields);

/// <summary>Describes an error declared by guest or domain logic.</summary>
/// <param name="Code">The stable declared-error code.</param>
/// <param name="Message">A human-readable description.</param>
/// <param name="Payload">The optional machine-readable error payload.</param>
/// <param name="MediaType">The media type of <paramref name="Payload"/>.</param>
/// <param name="Metadata">Additional declared-error metadata.</param>
public sealed record DeclaredError(
    string Code,
    string Message,
    ReadOnlyMemory<byte> Payload,
    string MediaType,
    IReadOnlyDictionary<string, string> Metadata);

/// <summary>Identifies and accounts for a terminal invocation.</summary>
/// <param name="ActivationId">The activation identifier.</param>
/// <param name="RevisionId">The revision that handled the invocation.</param>
/// <param name="ReleaseDigest">The release digest that handled the invocation.</param>
/// <param name="RouteGeneration">The route generation used for the invocation.</param>
/// <param name="Consumption">The finalized resource consumption.</param>
public sealed record InvocationReceipt(
    string ActivationId,
    string RevisionId,
    string ReleaseDigest,
    ulong RouteGeneration,
    BudgetConsumption Consumption);

/// <summary>Represents the typed terminal outcome of a synchronous invocation.</summary>
public abstract record InvocationOutcome
{
    private InvocationOutcome() { }

    /// <summary>Represents successful guest execution.</summary>
    /// <param name="Response">The successful response.</param>
    public sealed record Succeeded(InvokeResponse Response) : InvocationOutcome;

    /// <summary>Represents a declared guest or domain error.</summary>
    /// <param name="Receipt">The finalized invocation receipt.</param>
    /// <param name="Error">The declared error.</param>
    public sealed record DeclaredFailure(
        InvocationReceipt Receipt,
        DeclaredError Error) : InvocationOutcome;

    /// <summary>Represents a platform failure.</summary>
    /// <param name="Receipt">The finalized invocation receipt.</param>
    /// <param name="Error">The platform failure.</param>
    public sealed record PlatformFailure(
        InvocationReceipt Receipt,
        global::Latent.Sdk.PlatformFailure Error) : InvocationOutcome;
}

/// <summary>Describes the deterministic result of a cancellation request.</summary>
public enum CancelDisposition
{
    /// <summary>The cancellation request was accepted.</summary>
    Accepted,
    /// <summary>The activation was already terminal.</summary>
    AlreadyTerminal,
    /// <summary>The activation was not found.</summary>
    NotFound,
}

/// <summary>Represents the result of a cancellation request.</summary>
/// <param name="Disposition">The cancellation disposition.</param>
/// <param name="TerminalState">The already-observed terminal state, when applicable.</param>
public sealed record CancelResponse(
    CancelDisposition Disposition,
    string? TerminalState);

/// <summary>Represents a retained terminal outcome in activation status.</summary>
public abstract record RetainedInvocationOutcome
{
    private RetainedInvocationOutcome() { }

    /// <summary>Represents retained success diagnostics.</summary>
    /// <param name="CommittedStateVersion">The committed state version, when any.</param>
    /// <param name="EffectIds">The identifiers of created effects.</param>
    /// <param name="Metadata">Additional terminal metadata.</param>
    public sealed record Succeeded(
        string? CommittedStateVersion,
        IReadOnlyList<string> EffectIds,
        IReadOnlyDictionary<string, string> Metadata) : RetainedInvocationOutcome;

    /// <summary>Represents a retained declared guest or domain error.</summary>
    /// <param name="Error">The declared error.</param>
    public sealed record DeclaredFailure(DeclaredError Error) : RetainedInvocationOutcome;

    /// <summary>Represents a retained platform failure.</summary>
    /// <param name="Error">The platform failure.</param>
    public sealed record PlatformFailure(
        global::Latent.Sdk.PlatformFailure Error) : RetainedInvocationOutcome;
}

/// <summary>Describes the current or terminal state of an activation.</summary>
/// <param name="ActivationId">The activation identifier.</param>
/// <param name="Phase">The current lifecycle phase.</param>
/// <param name="TerminalState">The terminal state, when terminal.</param>
/// <param name="TerminalOutcome">The retained typed terminal outcome, when terminal.</param>
/// <param name="FinalConsumption">The finalized resource consumption, when terminal.</param>
/// <param name="LastUpdatedUnixMillis">The last update time in Unix milliseconds.</param>
/// <param name="TerminalAtUnixMillis">The terminal time in Unix milliseconds, when terminal.</param>
/// <param name="Metadata">Additional status metadata.</param>
public sealed record ActivationStatus(
    string ActivationId,
    string Phase,
    string? TerminalState,
    RetainedInvocationOutcome? TerminalOutcome,
    BudgetConsumption? FinalConsumption,
    ulong LastUpdatedUnixMillis,
    ulong? TerminalAtUnixMillis,
    IReadOnlyDictionary<string, string> Metadata);

/// <summary>Defines Phase 1 invocation, cancellation, and status operations.</summary>
public interface ILatentClient
{
    /// <summary>Invokes a target function and returns its typed terminal outcome.</summary>
    /// <param name="request">The invocation request.</param>
    /// <param name="cancellationToken">A token that cancels the client request.</param>
    /// <returns>The typed terminal invocation outcome.</returns>
    ValueTask<InvocationOutcome> InvokeAsync(
        InvokeRequest request,
        CancellationToken cancellationToken = default);

    /// <summary>Requests cancellation of an activation.</summary>
    /// <param name="activationId">The identifier of the activation to cancel.</param>
    /// <param name="reason">The reason for cancellation.</param>
    /// <param name="cancellationToken">A token that cancels the client request.</param>
    /// <returns>The deterministic cancellation result.</returns>
    ValueTask<CancelResponse> CancelAsync(
        string activationId,
        string reason,
        CancellationToken cancellationToken = default);

    /// <summary>Gets the retained status and terminal diagnostics for an activation.</summary>
    /// <param name="activationId">The activation identifier.</param>
    /// <param name="cancellationToken">A token that cancels the client request.</param>
    /// <returns>The current activation status.</returns>
    ValueTask<ActivationStatus> GetActivationAsync(
        string activationId,
        CancellationToken cancellationToken = default);
}

/// <summary>Exposes contextual information for a guest activation.</summary>
public interface IGuestContext
{
    /// <summary>Gets the identifier of the current activation.</summary>
    string ActivationId { get; }
    /// <summary>Gets the identifier of the root activation in the call tree.</summary>
    string RootActivationId { get; }
    /// <summary>Gets the identifier of the parent activation, if one exists.</summary>
    string? ParentActivationId { get; }
    /// <summary>Gets the optional absolute Unix-time caller deadline, in milliseconds.</summary>
    ulong? DeadlineUnixMillis { get; }
    /// <summary>Gets the resource budget remaining for the activation.</summary>
    ResourceBudget RemainingBudget { get; }
    /// <summary>Gets additional metadata associated with the activation.</summary>
    IReadOnlyDictionary<string, string> Metadata { get; }
}
