using Profile = Latent.Sdk.Profile;

namespace Latent.Sdk.Transactions;

/// <summary>Original bounded admission and recovery data; these values grant no authority.</summary>
public sealed record RecoveryIdentity
{
    /// <summary>The original namespace incarnation.</summary>
    public NamespaceSelector? Namespace { get; init; }
    /// <summary>The original business identity, independent of route and revision.</summary>
    public CommandSelector? Command { get; init; }
    /// <summary>The original activation identity.</summary>
    public string? ActivationId { get; init; }
    /// <summary>The original management operation identity.</summary>
    public string? OperationId { get; init; }
    /// <summary>The host command identity, when observed.</summary>
    public string? CommandId { get; init; }
    /// <summary>The selected attempt; never silently replaced.</summary>
    public string? AttemptId { get; init; }
    /// <summary>The requested or observed receipt identity.</summary>
    public string? ReceiptId { get; init; }
    /// <summary>The requested effect identity.</summary>
    public string? EffectId { get; init; }
    /// <summary>The caller's explicit retry request identity.</summary>
    public string? RetryRequestId { get; init; }
    /// <summary>The original proven-abort fence; a transport error cannot create one.</summary>
    public AbortFence? ExpectedAbort { get; init; }
    /// <summary>The original stale-edit preconditions.</summary>
    public IReadOnlyList<ExpectedVersion>? ExpectedVersions { get; init; }
    /// <summary>The original namespace management precondition.</summary>
    public ulong? ExpectedGeneration { get; init; }
    /// <summary>The original node dispatcher action.</summary>
    public DispatcherAction? DispatcherAction { get; init; }
    /// <summary>The original dispatcher owner epoch and revision.</summary>
    public DispatcherGeneration? DispatcherExpectedGeneration { get; init; }
    /// <summary>The original record management precondition.</summary>
    public ReadOnlyMemory<byte>? ExpectedVersion { get; init; }
    /// <summary>The original policy precondition.</summary>
    public string? ExpectedPolicyDigest { get; init; }
    /// <summary>The observed stable canonical-input fingerprint.</summary>
    public ReadOnlyMemory<byte>? FingerprintSha256 { get; init; }
    /// <summary>The requested current publication; it is independent of captured execution identity.</summary>
    public Profile.PublicationRef? AuthorizationPublication { get; init; }
}

/// <summary>Bounded durable receipt knowledge retained independently of application result bytes.</summary>
public sealed record ObservedOutcome
{
    /// <summary>The command inspection, without application or diagnostic bodies.</summary>
    public CommandInspection? Command { get; init; }
    /// <summary>The state operation receipt.</summary>
    public StateOperationReceipt? State { get; init; }
    /// <summary>The namespace lifecycle receipt.</summary>
    public NamespaceOperationReceipt? Namespace { get; init; }
    /// <summary>The effect delivery observation; it does not prove a command abort.</summary>
    public EffectReceipt? Effect { get; init; }
    /// <summary>The durable logical dispatcher operation; it does not prove physical retirement.</summary>
    public DispatcherOperationReceipt? Dispatcher { get; init; }
}

/// <summary>Independent transport, audit, identity and durable outcome observations.</summary>
/// <param name="Transport">The maintained transport metadata.</param>
/// <param name="Identity">Original recovery facts.</param>
/// <param name="Observed">A validated bounded receipt, when available.</param>
public sealed record TransactionMetadata(Profile.ResponseMetadata Transport, RecoveryIdentity Identity, ObservedOutcome? Observed);

/// <summary>A fully owned transaction response and independent recovery metadata.</summary>
/// <typeparam name="Response">The exact response model.</typeparam>
/// <param name="Value">The owned decoded response.</param>
/// <param name="Metadata">Independent receipt and transport observations.</param>
public sealed record TransactionResponse<Response>(Response Value, TransactionMetadata Metadata);

/// <summary>A failure retaining the original identity and any validated durable receipt.</summary>
/// <param name="Transport">The maintained transport failure.</param>
/// <param name="Identity">Original recovery facts.</param>
/// <param name="Observed">A validated receipt retained through later failures.</param>
public sealed record TransactionFailure(Profile.ClientFailure Transport, RecoveryIdentity Identity, ObservedOutcome? Observed);

/// <summary>A transaction failure, separate from a business rejection returned as a response.</summary>
public sealed class TransactionException : Exception
{
    /// <summary>Independent failure, identity and receipt facts.</summary>
    public TransactionFailure Failure { get; }
    /// <summary>Constructs a typed failure without inferring remote nonexecution.</summary>
    public TransactionException(TransactionFailure failure) : base(failure.Transport.Message) { Failure = failure; }
}

/// <summary>Local cancellation; physical retirement and remote outcome remain separate facts.</summary>
public sealed class TransactionCancellationException : OperationCanceledException
{
    /// <summary>Original recovery and receipt facts.</summary>
    public TransactionFailure Failure { get; }
    /// <summary>Retains cancellation and receipt facts without authorizing a new attempt.</summary>
    public TransactionCancellationException(TransactionFailure failure, CancellationToken token) : base(failure.Transport.Message, token) { Failure = failure; }
}

/// <summary>The maintained transaction client; calls never automatically resubmit mutations or drain pages.</summary>
public interface ITransactionClient
{
    /// <summary>Submits the original command or its explicit fenced attempt once.</summary>
    ValueTask<TransactionResponse<InvokeCommandResponse>> InvokeCommandAsync(InvokeCommandRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Acquires a bounded fresh read-only query view.</summary>
    ValueTask<TransactionResponse<QueryResponse>> QueryAsync(QueryRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Reads a caller-scoped command using current result authority.</summary>
    ValueTask<TransactionResponse<LookupCommandResponse>> LookupCommandAsync(LookupCommandRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Recovers a commit receipt under current result authority.</summary>
    ValueTask<TransactionResponse<LookupCommitResponse>> LookupCommitAsync(LookupCommitRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Reads one effect delivery observation.</summary>
    ValueTask<TransactionResponse<GetEffectResponse>> GetEffectAsync(GetEffectRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Reads one bounded effect-history page.</summary>
    ValueTask<TransactionResponse<ListEffectHistoryResponse>> ListEffectHistoryAsync(ListEffectHistoryRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Requests logical cancellation without inferring a proven abort.</summary>
    ValueTask<TransactionResponse<CancelCommandResponse>> CancelCommandAsync(CancelCommandRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Inspects one installed namespace incarnation.</summary>
    ValueTask<TransactionResponse<InspectNamespaceResponse>> InspectNamespaceAsync(InspectNamespaceRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Submits a namespace mutation with its original generation precondition.</summary>
    ValueTask<TransactionResponse<MutateNamespaceResponse>> MutateNamespaceAsync(MutateNamespaceRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Reads one bounded entity-selection page.</summary>
    ValueTask<TransactionResponse<SelectEntityResponse>> SelectEntityAsync(SelectEntityRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Submits a guarded state-management operation once.</summary>
    ValueTask<TransactionResponse<MutateStateResponse>> MutateStateAsync(MutateStateRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Recovers one state or namespace operation receipt.</summary>
    ValueTask<TransactionResponse<GetStateOperationReceiptResponse>> GetStateOperationReceiptAsync(GetStateOperationReceiptRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Inspects the current node dispatcher using current operator authority.</summary>
    ValueTask<TransactionResponse<InspectDispatcherResponse>> InspectDispatcherAsync(InspectDispatcherRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Submits the original node dispatcher action once.</summary>
    ValueTask<TransactionResponse<ControlDispatcherResponse>> ControlDispatcherAsync(ControlDispatcherRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
    /// <summary>Recovers the exact original dispatcher action without republishing it.</summary>
    ValueTask<TransactionResponse<GetDispatcherOperationResponse>> GetDispatcherOperationAsync(GetDispatcherOperationRequest request, Profile.CallOptions options, CancellationToken cancellationToken = default);
}
