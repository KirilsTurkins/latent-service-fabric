namespace Latent.Sdk;

/// <summary>
/// Specifies the resources available to an activation.
/// </summary>
/// <param name="CpuFuel">The maximum CPU fuel available to the activation.</param>
/// <param name="MemoryBytes">The maximum memory, in bytes, available to the activation.</param>
/// <param name="WallDeadlineUnixMillis">The optional Unix-time deadline, in milliseconds.</param>
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
    ulong? WallDeadlineUnixMillis,
    uint ChildCalls,
    uint OutboundRequests,
    ulong StateReadBytes,
    ulong StateWriteBytes,
    ulong BlobReadBytes,
    ulong BlobWriteBytes,
    ulong LogBytes,
    uint EffectCount);

/// <summary>
/// Describes the resources consumed by an activation.
/// </summary>
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

/// <summary>
/// Identifies the function to invoke.
/// </summary>
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

/// <summary>
/// Specifies options for an invocation.
/// </summary>
/// <param name="DeadlineUnixMillis">The optional Unix-time invocation deadline, in milliseconds.</param>
/// <param name="Priority">The invocation priority.</param>
/// <param name="IdempotencyKey">The optional key used to identify equivalent invocations.</param>
/// <param name="Budget">The resource budget available to the invocation.</param>
/// <param name="Metadata">Additional invocation metadata.</param>
public sealed record InvokeOptions(
    ulong? DeadlineUnixMillis,
    byte Priority,
    string? IdempotencyKey,
    ResourceBudget Budget,
    IReadOnlyDictionary<string, string> Metadata);

/// <summary>
/// Represents a request to invoke a target function.
/// </summary>
/// <param name="Target">The function to invoke.</param>
/// <param name="Payload">The invocation payload.</param>
/// <param name="MediaType">The media type of <paramref name="Payload"/>.</param>
/// <param name="Options">The invocation options.</param>
public sealed record InvokeRequest(
    InvocationTarget Target,
    ReadOnlyMemory<byte> Payload,
    string MediaType,
    InvokeOptions Options);

/// <summary>
/// Represents a response returned by an invocation.
/// </summary>
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

/// <summary>
/// Describes a failure returned by the platform.
/// </summary>
/// <param name="Code">The platform-defined failure code.</param>
/// <param name="Message">A human-readable description of the failure.</param>
/// <param name="Retryable">Whether retrying the operation may succeed.</param>
/// <param name="Details">Additional failure details.</param>
public sealed record PlatformFailure(
    string Code,
    string Message,
    bool Retryable,
    IReadOnlyDictionary<string, string> Details);

/// <summary>
/// Defines operations for invoking and cancelling Latent activations.
/// </summary>
public interface ILatentClient
{
    /// <summary>
    /// Invokes a target function.
    /// </summary>
    /// <param name="request">The invocation request.</param>
    /// <param name="cancellationToken">A token that cancels the invocation request.</param>
    /// <returns>The response returned by the completed invocation.</returns>
    ValueTask<InvokeResponse> InvokeAsync(
        InvokeRequest request,
        CancellationToken cancellationToken = default);

    /// <summary>
    /// Requests cancellation of an activation.
    /// </summary>
    /// <param name="activationId">The identifier of the activation to cancel.</param>
    /// <param name="reason">The reason for cancellation.</param>
    /// <param name="cancellationToken">A token that cancels the cancellation request.</param>
    /// <returns>A task that completes when the cancellation request has been sent.</returns>
    ValueTask CancelAsync(
        string activationId,
        string reason,
        CancellationToken cancellationToken = default);
}

/// <summary>
/// Exposes contextual information for a guest activation.
/// </summary>
public interface IGuestContext
{
    /// <summary>
    /// Gets the identifier of the current activation.
    /// </summary>
    string ActivationId { get; }

    /// <summary>
    /// Gets the identifier of the root activation in the call tree.
    /// </summary>
    string RootActivationId { get; }

    /// <summary>
    /// Gets the identifier of the parent activation, if one exists.
    /// </summary>
    string? ParentActivationId { get; }

    /// <summary>
    /// Gets the optional Unix-time deadline, in milliseconds, for the activation.
    /// </summary>
    ulong? DeadlineUnixMillis { get; }

    /// <summary>
    /// Gets the resource budget remaining for the activation.
    /// </summary>
    ResourceBudget RemainingBudget { get; }

    /// <summary>
    /// Gets additional metadata associated with the activation.
    /// </summary>
    IReadOnlyDictionary<string, string> Metadata { get; }
}
