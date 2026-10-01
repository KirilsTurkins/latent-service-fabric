// Generated from the authoritative transaction client descriptors.
namespace Latent.Sdk.Transactions;

/// <summary>Open numeric CommandCancelDisposition value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct CommandCancelDisposition(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly CommandCancelDisposition Unspecified = new(0);
    /// <summary>The requested value.</summary>
    public static readonly CommandCancelDisposition Requested = new(1);
    /// <summary>The already committed value.</summary>
    public static readonly CommandCancelDisposition AlreadyCommitted = new(2);
    /// <summary>The already terminal value.</summary>
    public static readonly CommandCancelDisposition AlreadyTerminal = new(3);
    /// <summary>The not found value.</summary>
    public static readonly CommandCancelDisposition NotFound = new(4);
    /// <summary>The recovery required value.</summary>
    public static readonly CommandCancelDisposition RecoveryRequired = new(5);
}

/// <summary>Open numeric CommandOutcome value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct CommandOutcome(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly CommandOutcome Unspecified = new(0);
    /// <summary>The in progress value.</summary>
    public static readonly CommandOutcome InProgress = new(1);
    /// <summary>The committed value.</summary>
    public static readonly CommandOutcome Committed = new(2);
    /// <summary>The rejected value.</summary>
    public static readonly CommandOutcome Rejected = new(3);
    /// <summary>The aborted value.</summary>
    public static readonly CommandOutcome Aborted = new(4);
    /// <summary>The unknown value.</summary>
    public static readonly CommandOutcome Unknown = new(5);
    /// <summary>The recovery required value.</summary>
    public static readonly CommandOutcome RecoveryRequired = new(6);
    /// <summary>The expired value.</summary>
    public static readonly CommandOutcome Expired = new(7);
}

/// <summary>Open numeric DispatcherAction value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct DispatcherAction(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly DispatcherAction Unspecified = new(0);
    /// <summary>The pause value.</summary>
    public static readonly DispatcherAction Pause = new(1);
    /// <summary>The resume value.</summary>
    public static readonly DispatcherAction Resume = new(2);
}

/// <summary>Open numeric DispatcherFailure value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct DispatcherFailure(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly DispatcherFailure Unspecified = new(0);
    /// <summary>The none value.</summary>
    public static readonly DispatcherFailure None = new(1);
    /// <summary>The authority value.</summary>
    public static readonly DispatcherFailure Authority = new(2);
    /// <summary>The store value.</summary>
    public static readonly DispatcherFailure Store = new(3);
    /// <summary>The worker value.</summary>
    public static readonly DispatcherFailure Worker = new(4);
    /// <summary>The restore checkpoint value.</summary>
    public static readonly DispatcherFailure RestoreCheckpoint = new(5);
    /// <summary>The admission closed value.</summary>
    public static readonly DispatcherFailure AdmissionClosed = new(6);
    /// <summary>The configuration value.</summary>
    public static readonly DispatcherFailure Configuration = new(7);
}

/// <summary>Open numeric DispatcherScope value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct DispatcherScope(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly DispatcherScope Unspecified = new(0);
    /// <summary>The node value.</summary>
    public static readonly DispatcherScope Node = new(1);
}

/// <summary>Open numeric EffectDisposition value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct EffectDisposition(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly EffectDisposition Unspecified = new(0);
    /// <summary>The pending value.</summary>
    public static readonly EffectDisposition Pending = new(1);
    /// <summary>The dispatching value.</summary>
    public static readonly EffectDisposition Dispatching = new(2);
    /// <summary>The provider acknowledged value.</summary>
    public static readonly EffectDisposition ProviderAcknowledged = new(3);
    /// <summary>The known failure value.</summary>
    public static readonly EffectDisposition KnownFailure = new(4);
    /// <summary>The uncertain after dispatch value.</summary>
    public static readonly EffectDisposition UncertainAfterDispatch = new(5);
    /// <summary>The expired value.</summary>
    public static readonly EffectDisposition Expired = new(6);
    /// <summary>The policy blocked value.</summary>
    public static readonly EffectDisposition PolicyBlocked = new(7);
    /// <summary>The administratively terminated value.</summary>
    public static readonly EffectDisposition AdministrativelyTerminated = new(8);
}

/// <summary>Open numeric NamespaceMutationKind value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct NamespaceMutationKind(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly NamespaceMutationKind Unspecified = new(0);
    /// <summary>The create value.</summary>
    public static readonly NamespaceMutationKind Create = new(1);
    /// <summary>The quiesce value.</summary>
    public static readonly NamespaceMutationKind Quiesce = new(2);
    /// <summary>The retire value.</summary>
    public static readonly NamespaceMutationKind Retire = new(3);
    /// <summary>The destroy value.</summary>
    public static readonly NamespaceMutationKind Destroy = new(4);
    /// <summary>The recreate value.</summary>
    public static readonly NamespaceMutationKind Recreate = new(5);
}

/// <summary>Open numeric NamespaceStatus value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct NamespaceStatus(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly NamespaceStatus Unspecified = new(0);
    /// <summary>The active value.</summary>
    public static readonly NamespaceStatus Active = new(1);
    /// <summary>The quiescing value.</summary>
    public static readonly NamespaceStatus Quiescing = new(2);
    /// <summary>The retired value.</summary>
    public static readonly NamespaceStatus Retired = new(3);
    /// <summary>The tombstone value.</summary>
    public static readonly NamespaceStatus Tombstone = new(4);
}

/// <summary>Open numeric StateMutationKind value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct StateMutationKind(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly StateMutationKind Unspecified = new(0);
    /// <summary>The retry known failed effect value.</summary>
    public static readonly StateMutationKind RetryKnownFailedEffect = new(1);
    /// <summary>The terminate effect value.</summary>
    public static readonly StateMutationKind TerminateEffect = new(2);
    /// <summary>The purge expired payload value.</summary>
    public static readonly StateMutationKind PurgeExpiredPayload = new(3);
    /// <summary>The checkpoint namespace value.</summary>
    public static readonly StateMutationKind CheckpointNamespace = new(4);
}

/// <summary>Open numeric StateOperationDisposition value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct StateOperationDisposition(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly StateOperationDisposition Unspecified = new(0);
    /// <summary>The committed value.</summary>
    public static readonly StateOperationDisposition Committed = new(1);
    /// <summary>The conflict value.</summary>
    public static readonly StateOperationDisposition Conflict = new(2);
    /// <summary>The rejected value.</summary>
    public static readonly StateOperationDisposition Rejected = new(3);
    /// <summary>The unknown value.</summary>
    public static readonly StateOperationDisposition Unknown = new(4);
    /// <summary>The recovery required value.</summary>
    public static readonly StateOperationDisposition RecoveryRequired = new(5);
}

/// <summary>Transport-neutral AbortFence; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="CommandId">The exact command_id value with preserved presence.</param>
/// <param name="AttemptId">The exact attempt_id value with preserved presence.</param>
/// <param name="TransactionId">The exact transaction_id value with preserved presence.</param>
/// <param name="OwnerFence">The exact owner_fence value with preserved presence.</param>
public sealed record AbortFence(
    string CommandId,
    string AttemptId,
    string TransactionId,
    ReadOnlyMemory<byte> OwnerFence);

/// <summary>Transport-neutral TransactionProfile; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Profile">The exact profile value with preserved presence.</param>
/// <param name="HostAbiDigest">The exact host_abi_digest value with preserved presence.</param>
/// <param name="PreparationProfileDigest">The exact preparation_profile_digest value with preserved presence.</param>
public sealed record TransactionProfile(
    string Profile,
    string HostAbiDigest,
    string PreparationProfileDigest);

/// <summary>Transport-neutral NamespaceSelector; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Tenant">The exact tenant value with preserved presence.</param>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="Incarnation">The exact incarnation value with preserved presence.</param>
public sealed record NamespaceSelector(
    string Tenant,
    string Namespace,
    string Incarnation);

/// <summary>Transport-neutral CommandSelector; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="Operation">The exact operation value with preserved presence.</param>
/// <param name="Entity">The exact entity value with preserved presence.</param>
/// <param name="ClientKey">The exact client_key value with preserved presence.</param>
/// <param name="SharedRecoveryScope">The exact shared_recovery_scope value with preserved presence.</param>
public sealed record CommandSelector(
    NamespaceSelector? Namespace,
    string Operation,
    string? Entity,
    string ClientKey,
    string? SharedRecoveryScope);

/// <summary>Transport-neutral LookupCommandRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Profile">The exact profile value with preserved presence.</param>
/// <param name="Command">The exact command value with preserved presence.</param>
/// <param name="AttemptId">The exact attempt_id value with preserved presence.</param>
/// <param name="AuthorizationPublication">The exact authorization_publication value with preserved presence.</param>
public sealed record LookupCommandRequest(
    TransactionProfile? Profile,
    CommandSelector? Command,
    string? AttemptId,
    global::Latent.Sdk.Profile.PublicationRef? AuthorizationPublication);

/// <summary>Transport-neutral CancelCommandRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Command">The exact command value with preserved presence.</param>
/// <param name="Reason">The exact reason value with preserved presence.</param>
public sealed record CancelCommandRequest(
    LookupCommandRequest? Command,
    string Reason);

/// <summary>Transport-neutral CommandKey; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="RecoveryScope">The exact recovery_scope value with preserved presence.</param>
/// <param name="Operation">The exact operation value with preserved presence.</param>
/// <param name="Entity">The exact entity value with preserved presence.</param>
/// <param name="ClientKey">The exact client_key value with preserved presence.</param>
public sealed record CommandKey(
    NamespaceSelector? Namespace,
    string RecoveryScope,
    string Operation,
    string? Entity,
    string ClientKey);

/// <summary>Transport-neutral SourceIdentity; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="PublicationId">The exact publication_id value with preserved presence.</param>
/// <param name="RevisionId">The exact revision_id value with preserved presence.</param>
/// <param name="ReleaseDigest">The exact release_digest value with preserved presence.</param>
/// <param name="RouteGeneration">The exact route_generation value with preserved presence.</param>
/// <param name="ContractDigest">The exact contract_digest value with preserved presence.</param>
/// <param name="StateSchema">The exact state_schema value with preserved presence.</param>
/// <param name="InputFormat">The exact input_format value with preserved presence.</param>
/// <param name="ResultFormat">The exact result_format value with preserved presence.</param>
/// <param name="ComponentDigest">The exact component_digest value with preserved presence.</param>
public sealed record SourceIdentity(
    string PublicationId,
    string RevisionId,
    string ReleaseDigest,
    ulong RouteGeneration,
    string ContractDigest,
    string StateSchema,
    string InputFormat,
    string ResultFormat,
    string ComponentDigest);

/// <summary>Transport-neutral CommitReceipt; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="CommandId">The exact command_id value with preserved presence.</param>
/// <param name="AttemptId">The exact attempt_id value with preserved presence.</param>
/// <param name="TransactionId">The exact transaction_id value with preserved presence.</param>
/// <param name="CommittedVersion">The exact committed_version value with preserved presence.</param>
/// <param name="CommittedAtUnixMillis">The exact committed_at_unix_millis value with preserved presence.</param>
/// <param name="EffectIds">The exact effect_ids value with preserved presence.</param>
/// <param name="ReceiptId">The exact receipt_id value with preserved presence.</param>
/// <param name="Source">The exact source value with preserved presence.</param>
public sealed record CommitReceipt(
    string CommandId,
    string AttemptId,
    string TransactionId,
    ReadOnlyMemory<byte> CommittedVersion,
    ulong CommittedAtUnixMillis,
    IReadOnlyList<string> EffectIds,
    string ReceiptId,
    SourceIdentity? Source);

/// <summary>Transport-neutral LinkedRetention; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="RecordFormat">The exact record_format value with preserved presence.</param>
/// <param name="RecordVersion">The exact record_version value with preserved presence.</param>
/// <param name="PayloadExpiresAtUnixMillis">The exact payload_expires_at_unix_millis value with preserved presence.</param>
/// <param name="IdentityExpiresAtUnixMillis">The exact identity_expires_at_unix_millis value with preserved presence.</param>
/// <param name="RemainingRecoveryMillis">The exact remaining_recovery_millis value with preserved presence.</param>
/// <param name="RequiredRecordIds">The exact required_record_ids value with preserved presence.</param>
/// <param name="PayloadAvailable">The exact payload_available value with preserved presence.</param>
public sealed record LinkedRetention(
    string RecordFormat,
    uint RecordVersion,
    ulong? PayloadExpiresAtUnixMillis,
    ulong? IdentityExpiresAtUnixMillis,
    ulong? RemainingRecoveryMillis,
    IReadOnlyList<string> RequiredRecordIds,
    bool PayloadAvailable);

/// <summary>Transport-neutral CommandInspection; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Key">The exact key value with preserved presence.</param>
/// <param name="CommandId">The exact command_id value with preserved presence.</param>
/// <param name="AttemptId">The exact attempt_id value with preserved presence.</param>
/// <param name="FingerprintSha256">The exact fingerprint_sha256 value with preserved presence.</param>
/// <param name="Outcome">The exact outcome value with preserved presence.</param>
/// <param name="MetadataDurable">The exact metadata_durable value with preserved presence.</param>
/// <param name="ApplicationStateCommitted">The exact application_state_committed value with preserved presence.</param>
/// <param name="Source">The exact source value with preserved presence.</param>
/// <param name="Success">The exact success value with preserved presence.</param>
/// <param name="BusinessRejection">The exact business_rejection value with preserved presence.</param>
/// <param name="TechnicalFailure">The exact technical_failure value with preserved presence.</param>
/// <param name="Commit">The exact commit value with preserved presence.</param>
/// <param name="ProvenAbort">The exact proven_abort value with preserved presence.</param>
/// <param name="Retention">The exact retention value with preserved presence.</param>
/// <param name="CleanupFailure">The exact cleanup_failure value with preserved presence.</param>
public sealed record CommandInspection(
    CommandKey? Key,
    string CommandId,
    string AttemptId,
    ReadOnlyMemory<byte> FingerprintSha256,
    CommandOutcome Outcome,
    bool MetadataDurable,
    bool ApplicationStateCommitted,
    SourceIdentity? Source,
    global::Latent.Sdk.Profile.Success? Success,
    global::Latent.Sdk.Profile.DeclaredError? BusinessRejection,
    global::Latent.Sdk.Profile.PlatformError? TechnicalFailure,
    CommitReceipt? Commit,
    AbortFence? ProvenAbort,
    LinkedRetention? Retention,
    global::Latent.Sdk.Profile.PlatformError? CleanupFailure);

/// <summary>Transport-neutral CancelCommandResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Disposition">The exact disposition value with preserved presence.</param>
/// <param name="Command">The exact command value with preserved presence.</param>
public sealed record CancelCommandResponse(
    CommandCancelDisposition Disposition,
    CommandInspection? Command);

/// <summary>Transport-neutral DispatcherGeneration; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="OwnerEpoch">The exact owner_epoch value with preserved presence.</param>
/// <param name="Revision">The exact revision value with preserved presence.</param>
public sealed record DispatcherGeneration(
    ulong OwnerEpoch,
    ulong Revision);

/// <summary>Transport-neutral ControlDispatcherRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Profile">The exact profile value with preserved presence.</param>
/// <param name="Scope">The exact scope value with preserved presence.</param>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
/// <param name="Action">The exact action value with preserved presence.</param>
/// <param name="ExpectedGeneration">The exact expected_generation value with preserved presence.</param>
public sealed record ControlDispatcherRequest(
    TransactionProfile? Profile,
    DispatcherScope Scope,
    string OperationId,
    DispatcherAction Action,
    DispatcherGeneration? ExpectedGeneration);

/// <summary>Transport-neutral DispatcherOperationReceipt; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
/// <param name="ReceiptId">The exact receipt_id value with preserved presence.</param>
/// <param name="Action">The exact action value with preserved presence.</param>
/// <param name="AuthenticatedOperator">The exact authenticated_operator value with preserved presence.</param>
/// <param name="ActorTenant">The exact actor_tenant value with preserved presence.</param>
/// <param name="BeforeGeneration">The exact before_generation value with preserved presence.</param>
/// <param name="AfterGeneration">The exact after_generation value with preserved presence.</param>
/// <param name="ObservedAtUnixMillis">The exact observed_at_unix_millis value with preserved presence.</param>
/// <param name="ClockContinuityProven">The exact clock_continuity_proven value with preserved presence.</param>
/// <param name="RestoreReviewRequired">The exact restore_review_required value with preserved presence.</param>
/// <param name="Disposition">The exact disposition value with preserved presence.</param>
public sealed record DispatcherOperationReceipt(
    string OperationId,
    string ReceiptId,
    DispatcherAction Action,
    string AuthenticatedOperator,
    string ActorTenant,
    DispatcherGeneration? BeforeGeneration,
    DispatcherGeneration? AfterGeneration,
    ulong ObservedAtUnixMillis,
    bool ClockContinuityProven,
    bool RestoreReviewRequired,
    StateOperationDisposition Disposition);

/// <summary>Transport-neutral ControlDispatcherResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Receipt">The exact receipt value with preserved presence.</param>
/// <param name="Replayed">The exact replayed value with preserved presence.</param>
/// <param name="Published">The exact published value with preserved presence.</param>
/// <param name="Paused">The exact paused value with preserved presence.</param>
/// <param name="AuditAck">The exact audit_ack value with preserved presence.</param>
public sealed record ControlDispatcherResponse(
    DispatcherOperationReceipt? Receipt,
    bool Replayed,
    bool Published,
    bool Paused,
    global::Latent.Sdk.Profile.AuditAck? AuditAck);

/// <summary>Transport-neutral DispatcherSnapshot; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Generation">The exact generation value with preserved presence.</param>
/// <param name="Paused">The exact paused value with preserved presence.</param>
/// <param name="PendingControl">The exact pending_control value with preserved presence.</param>
/// <param name="RestoreReviewRequired">The exact restore_review_required value with preserved presence.</param>
/// <param name="AdmissionClosed">The exact admission_closed value with preserved presence.</param>
/// <param name="Quarantined">The exact quarantined value with preserved presence.</param>
/// <param name="Failure">The exact failure value with preserved presence.</param>
/// <param name="Queued">The exact queued value with preserved presence.</param>
/// <param name="ActiveJobs">The exact active_jobs value with preserved presence.</param>
/// <param name="RetainedAttemptBytes">The exact retained_attempt_bytes value with preserved presence.</param>
/// <param name="LiveWorkers">The exact live_workers value with preserved presence.</param>
/// <param name="AcceptedEffects">The exact accepted_effects value with preserved presence.</param>
/// <param name="PhysicalOwners">The exact physical_owners value with preserved presence.</param>
/// <param name="QuarantinedPhysicalOwners">The exact quarantined_physical_owners value with preserved presence.</param>
/// <param name="CommandOwners">The exact command_owners value with preserved presence.</param>
/// <param name="Claims">The exact claims value with preserved presence.</param>
/// <param name="PendingEffects">The exact pending_effects value with preserved presence.</param>
/// <param name="UncertainEffects">The exact uncertain_effects value with preserved presence.</param>
/// <param name="BlockedEffects">The exact blocked_effects value with preserved presence.</param>
/// <param name="DeadLetterEffects">The exact dead_letter_effects value with preserved presence.</param>
/// <param name="CountsObservedAtUnixMillis">The exact counts_observed_at_unix_millis value with preserved presence.</param>
/// <param name="ClockContinuityProven">The exact clock_continuity_proven value with preserved presence.</param>
public sealed record DispatcherSnapshot(
    DispatcherGeneration? Generation,
    bool Paused,
    bool PendingControl,
    bool RestoreReviewRequired,
    bool AdmissionClosed,
    bool Quarantined,
    DispatcherFailure Failure,
    ulong Queued,
    ulong ActiveJobs,
    ulong RetainedAttemptBytes,
    ulong LiveWorkers,
    ulong AcceptedEffects,
    ulong PhysicalOwners,
    ulong QuarantinedPhysicalOwners,
    ulong CommandOwners,
    ulong Claims,
    ulong PendingEffects,
    ulong UncertainEffects,
    ulong BlockedEffects,
    ulong DeadLetterEffects,
    ulong CountsObservedAtUnixMillis,
    bool ClockContinuityProven);

/// <summary>Transport-neutral EffectReceipt; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="EffectId">The exact effect_id value with preserved presence.</param>
/// <param name="CommandId">The exact command_id value with preserved presence.</param>
/// <param name="CommandAttemptId">The exact command_attempt_id value with preserved presence.</param>
/// <param name="DispatchAttempt">The exact dispatch_attempt value with preserved presence.</param>
/// <param name="Disposition">The exact disposition value with preserved presence.</param>
/// <param name="ProviderReceipt">The exact provider_receipt value with preserved presence.</param>
/// <param name="FailureCode">The exact failure_code value with preserved presence.</param>
/// <param name="OccurredAtUnixMillis">The exact occurred_at_unix_millis value with preserved presence.</param>
/// <param name="Retention">The exact retention value with preserved presence.</param>
/// <param name="ManagementOperationReceiptId">The exact management_operation_receipt_id value with preserved presence.</param>
/// <param name="ProviderProfile">The exact provider_profile value with preserved presence.</param>
public sealed record EffectReceipt(
    string EffectId,
    string CommandId,
    string CommandAttemptId,
    uint DispatchAttempt,
    EffectDisposition Disposition,
    string? ProviderReceipt,
    string? FailureCode,
    ulong OccurredAtUnixMillis,
    LinkedRetention? Retention,
    string? ManagementOperationReceiptId,
    string ProviderProfile);

/// <summary>Transport-neutral EntityInspection; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Entity">The exact entity value with preserved presence.</param>
/// <param name="Version">The exact version value with preserved presence.</param>
public sealed record EntityInspection(
    string Entity,
    ReadOnlyMemory<byte> Version);

/// <summary>Transport-neutral ExpectedVersion; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Key">The exact key value with preserved presence.</param>
/// <param name="Absent">The exact absent value with preserved presence.</param>
/// <param name="Version">The exact version value with preserved presence.</param>
public sealed record ExpectedVersion(
    ReadOnlyMemory<byte> Key,
    bool? Absent,
    ReadOnlyMemory<byte>? Version);

/// <summary>Transport-neutral GetDispatcherOperationRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Original">The exact original value with preserved presence.</param>
public sealed record GetDispatcherOperationRequest(
    ControlDispatcherRequest? Original);

/// <summary>Transport-neutral GetDispatcherOperationResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Receipt">The exact receipt value with preserved presence.</param>
/// <param name="AuditAck">The exact audit_ack value with preserved presence.</param>
public sealed record GetDispatcherOperationResponse(
    DispatcherOperationReceipt? Receipt,
    global::Latent.Sdk.Profile.AuditAck? AuditAck);

/// <summary>Transport-neutral GetEffectRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Profile">The exact profile value with preserved presence.</param>
/// <param name="Command">The exact command value with preserved presence.</param>
/// <param name="EffectId">The exact effect_id value with preserved presence.</param>
/// <param name="AuthorizationPublication">The exact authorization_publication value with preserved presence.</param>
public sealed record GetEffectRequest(
    TransactionProfile? Profile,
    CommandSelector? Command,
    string EffectId,
    global::Latent.Sdk.Profile.PublicationRef? AuthorizationPublication);

/// <summary>Transport-neutral GetEffectResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Effect">The exact effect value with preserved presence.</param>
public sealed record GetEffectResponse(
    EffectReceipt? Effect);

/// <summary>Transport-neutral InspectNamespaceRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Profile">The exact profile value with preserved presence.</param>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="AuthorizationPublication">The exact authorization_publication value with preserved presence.</param>
public sealed record InspectNamespaceRequest(
    TransactionProfile? Profile,
    NamespaceSelector? Namespace,
    global::Latent.Sdk.Profile.PublicationRef? AuthorizationPublication);

/// <summary>Transport-neutral GetStateOperationReceiptRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
public sealed record GetStateOperationReceiptRequest(
    InspectNamespaceRequest? Namespace,
    string OperationId);

/// <summary>Transport-neutral StateOperationReceipt; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
/// <param name="ReceiptId">The exact receipt_id value with preserved presence.</param>
/// <param name="Mutation">The exact mutation value with preserved presence.</param>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="AuthenticatedOperator">The exact authenticated_operator value with preserved presence.</param>
/// <param name="BeforeVersion">The exact before_version value with preserved presence.</param>
/// <param name="AfterVersion">The exact after_version value with preserved presence.</param>
/// <param name="CompletedAtUnixMillis">The exact completed_at_unix_millis value with preserved presence.</param>
/// <param name="RecordId">The exact record_id value with preserved presence.</param>
/// <param name="PolicyDigest">The exact policy_digest value with preserved presence.</param>
/// <param name="Disposition">The exact disposition value with preserved presence.</param>
public sealed record StateOperationReceipt(
    string OperationId,
    string ReceiptId,
    StateMutationKind Mutation,
    NamespaceSelector? Namespace,
    string AuthenticatedOperator,
    ReadOnlyMemory<byte> BeforeVersion,
    ReadOnlyMemory<byte> AfterVersion,
    ulong CompletedAtUnixMillis,
    string? RecordId,
    string PolicyDigest,
    StateOperationDisposition Disposition);

/// <summary>Transport-neutral NamespaceOperationReceipt; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
/// <param name="ReceiptId">The exact receipt_id value with preserved presence.</param>
/// <param name="Mutation">The exact mutation value with preserved presence.</param>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="AuthenticatedOperator">The exact authenticated_operator value with preserved presence.</param>
/// <param name="BeforeGeneration">The exact before_generation value with preserved presence.</param>
/// <param name="AfterGeneration">The exact after_generation value with preserved presence.</param>
/// <param name="Status">The exact status value with preserved presence.</param>
/// <param name="StateSchema">The exact state_schema value with preserved presence.</param>
/// <param name="Disposition">The exact disposition value with preserved presence.</param>
public sealed record NamespaceOperationReceipt(
    string OperationId,
    string ReceiptId,
    NamespaceMutationKind Mutation,
    NamespaceSelector? Namespace,
    string AuthenticatedOperator,
    ulong? BeforeGeneration,
    ulong AfterGeneration,
    NamespaceStatus Status,
    string StateSchema,
    StateOperationDisposition Disposition);

/// <summary>Transport-neutral GetStateOperationReceiptResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Receipt">The exact receipt value with preserved presence.</param>
/// <param name="NamespaceReceipt">The exact namespace_receipt value with preserved presence.</param>
public sealed record GetStateOperationReceiptResponse(
    StateOperationReceipt? Receipt,
    NamespaceOperationReceipt? NamespaceReceipt);

/// <summary>Transport-neutral InspectDispatcherRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Profile">The exact profile value with preserved presence.</param>
/// <param name="Scope">The exact scope value with preserved presence.</param>
public sealed record InspectDispatcherRequest(
    TransactionProfile? Profile,
    DispatcherScope Scope);

/// <summary>Transport-neutral InspectDispatcherResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Dispatcher">The exact dispatcher value with preserved presence.</param>
/// <param name="AuditAck">The exact audit_ack value with preserved presence.</param>
public sealed record InspectDispatcherResponse(
    DispatcherSnapshot? Dispatcher,
    global::Latent.Sdk.Profile.AuditAck? AuditAck);

/// <summary>Transport-neutral ViewIdentity; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="Version">The exact version value with preserved presence.</param>
/// <param name="StateSchema">The exact state_schema value with preserved presence.</param>
public sealed record ViewIdentity(
    NamespaceSelector? Namespace,
    ReadOnlyMemory<byte> Version,
    string StateSchema);

/// <summary>Transport-neutral NamespaceQuota; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="StateKeys">The exact state_keys value with preserved presence.</param>
/// <param name="StateBytes">The exact state_bytes value with preserved presence.</param>
/// <param name="ResultRows">The exact result_rows value with preserved presence.</param>
/// <param name="ResultBytes">The exact result_bytes value with preserved presence.</param>
/// <param name="EffectRows">The exact effect_rows value with preserved presence.</param>
/// <param name="EffectBytes">The exact effect_bytes value with preserved presence.</param>
/// <param name="PayloadBytes">The exact payload_bytes value with preserved presence.</param>
/// <param name="RecoveryBytes">The exact recovery_bytes value with preserved presence.</param>
public sealed record NamespaceQuota(
    ulong StateKeys,
    ulong StateBytes,
    ulong ResultRows,
    ulong ResultBytes,
    ulong EffectRows,
    ulong EffectBytes,
    ulong PayloadBytes,
    ulong RecoveryBytes);

/// <summary>Transport-neutral NamespaceInspection; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="View">The exact view value with preserved presence.</param>
/// <param name="EncodedStateBytes">The exact encoded_state_bytes value with preserved presence.</param>
/// <param name="CommandCount">The exact command_count value with preserved presence.</param>
/// <param name="PendingEffectCount">The exact pending_effect_count value with preserved presence.</param>
/// <param name="RetainedFormats">The exact retained_formats value with preserved presence.</param>
/// <param name="EngineProfile">The exact engine_profile value with preserved presence.</param>
/// <param name="EngineProfileDigest">The exact engine_profile_digest value with preserved presence.</param>
/// <param name="Status">The exact status value with preserved presence.</param>
/// <param name="Quota">The exact quota value with preserved presence.</param>
/// <param name="Generation">The exact generation value with preserved presence.</param>
public sealed record NamespaceInspection(
    ViewIdentity? View,
    ulong EncodedStateBytes,
    ulong CommandCount,
    ulong PendingEffectCount,
    IReadOnlyList<LinkedRetention> RetainedFormats,
    string EngineProfile,
    string EngineProfileDigest,
    NamespaceStatus Status,
    NamespaceQuota? Quota,
    ulong Generation);

/// <summary>Transport-neutral InspectNamespaceResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
public sealed record InspectNamespaceResponse(
    NamespaceInspection? Namespace);

/// <summary>Transport-neutral RetryAttempt; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="RequestId">The exact request_id value with preserved presence.</param>
/// <param name="ExpectedAbort">The exact expected_abort value with preserved presence.</param>
public sealed record RetryAttempt(
    string RequestId,
    AbortFence? ExpectedAbort);

/// <summary>Transport-neutral InvokeCommandRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Profile">The exact profile value with preserved presence.</param>
/// <param name="Invocation">The exact invocation value with preserved presence.</param>
/// <param name="Command">The exact command value with preserved presence.</param>
/// <param name="InputFormat">The exact input_format value with preserved presence.</param>
/// <param name="ExpectedVersions">The exact expected_versions value with preserved presence.</param>
/// <param name="RetryAttempt">The exact retry_attempt value with preserved presence.</param>
public sealed record InvokeCommandRequest(
    TransactionProfile? Profile,
    global::Latent.Sdk.Profile.InvokeRequest? Invocation,
    CommandSelector? Command,
    string InputFormat,
    IReadOnlyList<ExpectedVersion> ExpectedVersions,
    RetryAttempt? RetryAttempt);

/// <summary>Transport-neutral InvokeCommandResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Invocation">The exact invocation value with preserved presence.</param>
/// <param name="Command">The exact command value with preserved presence.</param>
/// <param name="Replayed">The exact replayed value with preserved presence.</param>
public sealed record InvokeCommandResponse(
    global::Latent.Sdk.Profile.InvokeResponse? Invocation,
    CommandInspection? Command,
    bool Replayed);

/// <summary>Transport-neutral PageRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Limit">The exact limit value with preserved presence.</param>
/// <param name="Cursor">The exact cursor value with preserved presence.</param>
public sealed record PageRequest(
    uint Limit,
    ReadOnlyMemory<byte>? Cursor);

/// <summary>Transport-neutral ListEffectHistoryRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Effect">The exact effect value with preserved presence.</param>
/// <param name="Page">The exact page value with preserved presence.</param>
public sealed record ListEffectHistoryRequest(
    GetEffectRequest? Effect,
    PageRequest? Page);

/// <summary>Transport-neutral PageResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="NextCursor">The exact next_cursor value with preserved presence.</param>
/// <param name="ReturnedCount">The exact returned_count value with preserved presence.</param>
/// <param name="EncodedBytes">The exact encoded_bytes value with preserved presence.</param>
public sealed record PageResponse(
    ReadOnlyMemory<byte>? NextCursor,
    uint ReturnedCount,
    ulong EncodedBytes);

/// <summary>Transport-neutral ListEffectHistoryResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Receipts">The exact receipts value with preserved presence.</param>
/// <param name="Page">The exact page value with preserved presence.</param>
public sealed record ListEffectHistoryResponse(
    IReadOnlyList<EffectReceipt> Receipts,
    PageResponse? Page);

/// <summary>Transport-neutral LookupCommandResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Command">The exact command value with preserved presence.</param>
public sealed record LookupCommandResponse(
    CommandInspection? Command);

/// <summary>Transport-neutral LookupCommitRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Profile">The exact profile value with preserved presence.</param>
/// <param name="Command">The exact command value with preserved presence.</param>
/// <param name="ReceiptId">The exact receipt_id value with preserved presence.</param>
/// <param name="AuthorizationPublication">The exact authorization_publication value with preserved presence.</param>
public sealed record LookupCommitRequest(
    TransactionProfile? Profile,
    CommandSelector? Command,
    string ReceiptId,
    global::Latent.Sdk.Profile.PublicationRef? AuthorizationPublication);

/// <summary>Transport-neutral LookupCommitResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Command">The exact command value with preserved presence.</param>
public sealed record LookupCommitResponse(
    CommandInspection? Command);

/// <summary>Transport-neutral NamespaceConfiguration; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="StateSchema">The exact state_schema value with preserved presence.</param>
/// <param name="Quota">The exact quota value with preserved presence.</param>
public sealed record NamespaceConfiguration(
    string StateSchema,
    NamespaceQuota? Quota);

/// <summary>Transport-neutral MutateNamespaceRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
/// <param name="Mutation">The exact mutation value with preserved presence.</param>
/// <param name="ExpectedGeneration">The exact expected_generation value with preserved presence.</param>
/// <param name="Configuration">The exact configuration value with preserved presence.</param>
public sealed record MutateNamespaceRequest(
    InspectNamespaceRequest? Namespace,
    string OperationId,
    NamespaceMutationKind Mutation,
    ulong? ExpectedGeneration,
    NamespaceConfiguration? Configuration);

/// <summary>Transport-neutral MutateNamespaceResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Receipt">The exact receipt value with preserved presence.</param>
/// <param name="Replayed">The exact replayed value with preserved presence.</param>
/// <param name="AuditAck">The exact audit_ack value with preserved presence.</param>
public sealed record MutateNamespaceResponse(
    NamespaceOperationReceipt? Receipt,
    bool Replayed,
    global::Latent.Sdk.Profile.AuditAck? AuditAck);

/// <summary>Transport-neutral MutateStateRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
/// <param name="Mutation">The exact mutation value with preserved presence.</param>
/// <param name="RecordId">The exact record_id value with preserved presence.</param>
/// <param name="ExpectedVersion">The exact expected_version value with preserved presence.</param>
/// <param name="ExpectedPolicyDigest">The exact expected_policy_digest value with preserved presence.</param>
/// <param name="Reason">The exact reason value with preserved presence.</param>
public sealed record MutateStateRequest(
    InspectNamespaceRequest? Namespace,
    string OperationId,
    StateMutationKind Mutation,
    string? RecordId,
    ReadOnlyMemory<byte> ExpectedVersion,
    string ExpectedPolicyDigest,
    string Reason);

/// <summary>Transport-neutral MutateStateResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Receipt">The exact receipt value with preserved presence.</param>
/// <param name="AuditAck">The exact audit_ack value with preserved presence.</param>
public sealed record MutateStateResponse(
    StateOperationReceipt? Receipt,
    global::Latent.Sdk.Profile.AuditAck? AuditAck);

/// <summary>Transport-neutral QueryRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Profile">The exact profile value with preserved presence.</param>
/// <param name="Invocation">The exact invocation value with preserved presence.</param>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="Entity">The exact entity value with preserved presence.</param>
/// <param name="MinimumViewVersion">The exact minimum_view_version value with preserved presence.</param>
public sealed record QueryRequest(
    TransactionProfile? Profile,
    global::Latent.Sdk.Profile.InvokeRequest? Invocation,
    NamespaceSelector? Namespace,
    string? Entity,
    ReadOnlyMemory<byte>? MinimumViewVersion);

/// <summary>Transport-neutral QueryResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Invocation">The exact invocation value with preserved presence.</param>
/// <param name="View">The exact view value with preserved presence.</param>
/// <param name="Source">The exact source value with preserved presence.</param>
/// <param name="ObservedAtUnixMillis">The exact observed_at_unix_millis value with preserved presence.</param>
public sealed record QueryResponse(
    global::Latent.Sdk.Profile.InvokeResponse? Invocation,
    ViewIdentity? View,
    SourceIdentity? Source,
    ulong ObservedAtUnixMillis);

/// <summary>Transport-neutral SelectEntityRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="Prefix">The exact prefix value with preserved presence.</param>
/// <param name="Page">The exact page value with preserved presence.</param>
public sealed record SelectEntityRequest(
    InspectNamespaceRequest? Namespace,
    ReadOnlyMemory<byte>? Prefix,
    PageRequest? Page);

/// <summary>Transport-neutral SelectEntityResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Entities">The exact entities value with preserved presence.</param>
/// <param name="Page">The exact page value with preserved presence.</param>
public sealed record SelectEntityResponse(
    IReadOnlyList<EntityInspection> Entities,
    PageResponse? Page);

/// <summary>Constructs a protocol descriptor; this value grants no authority.</summary>
public static class CurrentTransactionProfile
{
    /// <summary>Returns the exact maintained wire and preparation profile.</summary>
    public static TransactionProfile Create() => new("lsf-transaction-v1", "sha256:3b85f790f85ab23d36e492d7bd4a04a1b8aab87fc6f67dd7d7498bcf28129d35", "sha256:6acd7a248633dd01c9cdcbf8a1ed33fc5e6aa1d2edb09b7d89e53fda594b5507");
}
