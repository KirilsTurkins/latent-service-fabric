using System.Globalization;

namespace Latent.Sdk.Profile;

/// <summary>Open numeric AuditAckStatus value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct AuditAckStatus(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly AuditAckStatus Unspecified = new(0);
    /// <summary>The durable value.</summary>
    public static readonly AuditAckStatus Durable = new(1);
    /// <summary>The outcome unknown value.</summary>
    public static readonly AuditAckStatus OutcomeUnknown = new(2);
    /// <summary>The audit unavailable value.</summary>
    public static readonly AuditAckStatus AuditUnavailable = new(3);
    /// <summary>The disabled value.</summary>
    public static readonly AuditAckStatus Disabled = new(4);
}

/// <summary>Open numeric CancelDisposition value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct CancelDisposition(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly CancelDisposition Unspecified = new(0);
    /// <summary>The accepted value.</summary>
    public static readonly CancelDisposition Accepted = new(1);
    /// <summary>The already terminal value.</summary>
    public static readonly CancelDisposition AlreadyTerminal = new(2);
    /// <summary>The not found value.</summary>
    public static readonly CancelDisposition NotFound = new(3);
}

/// <summary>Open numeric CapabilityPolicyRecordKind value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct CapabilityPolicyRecordKind(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly CapabilityPolicyRecordKind Unspecified = new(0);
    /// <summary>The policy value.</summary>
    public static readonly CapabilityPolicyRecordKind Policy = new(1);
    /// <summary>The provider binding value.</summary>
    public static readonly CapabilityPolicyRecordKind ProviderBinding = new(2);
}

/// <summary>Open numeric FailureCategory value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct FailureCategory(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly FailureCategory Unspecified = new(0);
    /// <summary>The local cancelled value.</summary>
    public static readonly FailureCategory LocalCancelled = new(1);
    /// <summary>The deadline value.</summary>
    public static readonly FailureCategory Deadline = new(2);
    /// <summary>The transport value.</summary>
    public static readonly FailureCategory Transport = new(3);
    /// <summary>The rpc value.</summary>
    public static readonly FailureCategory Rpc = new(4);
    /// <summary>The decode value.</summary>
    public static readonly FailureCategory Decode = new(5);
    /// <summary>The limit value.</summary>
    public static readonly FailureCategory Limit = new(6);
    /// <summary>The invalid request value.</summary>
    public static readonly FailureCategory InvalidRequest = new(7);
}

/// <summary>Open numeric OutcomeKnowledge value; unknown integers are retained.</summary>
/// <param name="Value">The exact signed protobuf enum value.</param>
public readonly record struct OutcomeKnowledge(int Value)
{
    /// <summary>The unspecified value.</summary>
    public static readonly OutcomeKnowledge Unspecified = new(0);
    /// <summary>The not dispatched value.</summary>
    public static readonly OutcomeKnowledge NotDispatched = new(1);
    /// <summary>The unknown value.</summary>
    public static readonly OutcomeKnowledge Unknown = new(2);
    /// <summary>The observed value.</summary>
    public static readonly OutcomeKnowledge Observed = new(3);
}

/// <summary>Transport-neutral ResourceBudget; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="CpuFuel">The exact cpu_fuel value with preserved presence.</param>
/// <param name="MemoryBytes">The exact memory_bytes value with preserved presence.</param>
/// <param name="ChildCalls">The exact child_calls value with preserved presence.</param>
/// <param name="OutboundRequests">The exact outbound_requests value with preserved presence.</param>
/// <param name="StateReadBytes">The exact state_read_bytes value with preserved presence.</param>
/// <param name="StateWriteBytes">The exact state_write_bytes value with preserved presence.</param>
/// <param name="BlobReadBytes">The exact blob_read_bytes value with preserved presence.</param>
/// <param name="BlobWriteBytes">The exact blob_write_bytes value with preserved presence.</param>
/// <param name="LogBytes">The exact log_bytes value with preserved presence.</param>
/// <param name="EffectCount">The exact effect_count value with preserved presence.</param>
/// <param name="WallTimeLimitMillis">The exact wall_time_limit_millis value with preserved presence.</param>
public sealed record ResourceBudget(
    ulong CpuFuel,
    ulong MemoryBytes,
    uint ChildCalls,
    uint OutboundRequests,
    ulong StateReadBytes,
    ulong StateWriteBytes,
    ulong BlobReadBytes,
    ulong BlobWriteBytes,
    ulong LogBytes,
    uint EffectCount,
    ulong? WallTimeLimitMillis);

/// <summary>Transport-neutral ErrorDetail; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Kind">The exact kind value with preserved presence.</param>
/// <param name="Fields">The exact fields value with preserved presence.</param>
public sealed record ErrorDetail(
    string Kind,
    IReadOnlyDictionary<string, string> Fields);

/// <summary>Transport-neutral PlatformError; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Code">The exact code value with preserved presence.</param>
/// <param name="Message">The exact message value with preserved presence.</param>
/// <param name="Retryable">The exact retryable value with preserved presence.</param>
/// <param name="DetailItems">The exact detail_items value with preserved presence.</param>
public sealed record PlatformError(
    string Code,
    string Message,
    bool Retryable,
    IReadOnlyList<ErrorDetail> DetailItems);

/// <summary>Transport-neutral ObjectMetadata; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Name">The exact name value with preserved presence.</param>
/// <param name="Tenant">The exact tenant value with preserved presence.</param>
/// <param name="Namespace">The exact namespace value with preserved presence.</param>
/// <param name="Labels">The exact labels value with preserved presence.</param>
/// <param name="Annotations">The exact annotations value with preserved presence.</param>
public sealed record ObjectMetadata(
    string Name,
    string? Tenant,
    string? Namespace,
    IReadOnlyDictionary<string, string> Labels,
    IReadOnlyDictionary<string, string> Annotations);

/// <summary>Transport-neutral PageRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="PageSize">The exact page_size value with preserved presence.</param>
/// <param name="PageToken">The exact page_token value with preserved presence.</param>
public sealed record PageRequest(
    uint PageSize,
    string? PageToken);

/// <summary>Transport-neutral PageResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="NextPageToken">The exact next_page_token value with preserved presence.</param>
public sealed record PageResponse(
    string? NextPageToken);

/// <summary>Transport-neutral AuditAck; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Status">The exact status value with preserved presence.</param>
/// <param name="AttemptSequence">The exact attempt_sequence value with preserved presence.</param>
public sealed record AuditAck(
    AuditAckStatus Status,
    ulong? AttemptSequence);

/// <summary>Transport-neutral InvocationTarget; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Tenant">The exact tenant value with preserved presence.</param>
/// <param name="Service">The exact service value with preserved presence.</param>
/// <param name="Contract">The exact contract value with preserved presence.</param>
/// <param name="Function">The exact function value with preserved presence.</param>
/// <param name="Route">The exact route value with preserved presence.</param>
public sealed record InvocationTarget(
    string Tenant,
    string Service,
    string Contract,
    string Function,
    string? Route);

/// <summary>Transport-neutral InvokeRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="ActivationId">The exact activation_id value with preserved presence.</param>
/// <param name="ParentActivationId">The exact parent_activation_id value with preserved presence.</param>
/// <param name="RootActivationId">The exact root_activation_id value with preserved presence.</param>
/// <param name="Target">The exact target value with preserved presence.</param>
/// <param name="Payload">The exact payload value with preserved presence.</param>
/// <param name="MediaType">The exact media_type value with preserved presence.</param>
/// <param name="DeadlineUnixMillis">The exact deadline_unix_millis value with preserved presence.</param>
/// <param name="Priority">The exact priority value with preserved presence.</param>
/// <param name="IdempotencyKey">The exact idempotency_key value with preserved presence.</param>
/// <param name="Budget">The exact budget value with preserved presence.</param>
/// <param name="Metadata">The exact metadata value with preserved presence.</param>
public sealed record InvokeRequest(
    string? ActivationId,
    string? ParentActivationId,
    string? RootActivationId,
    InvocationTarget? Target,
    ReadOnlyMemory<byte> Payload,
    string MediaType,
    ulong? DeadlineUnixMillis,
    uint Priority,
    string? IdempotencyKey,
    ResourceBudget? Budget,
    IReadOnlyDictionary<string, string> Metadata);

/// <summary>Transport-neutral BudgetConsumption; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="CpuFuel">The exact cpu_fuel value with preserved presence.</param>
/// <param name="PeakMemoryBytes">The exact peak_memory_bytes value with preserved presence.</param>
/// <param name="WallTimeMicros">The exact wall_time_micros value with preserved presence.</param>
/// <param name="ChildCalls">The exact child_calls value with preserved presence.</param>
/// <param name="OutboundRequests">The exact outbound_requests value with preserved presence.</param>
/// <param name="StateReadBytes">The exact state_read_bytes value with preserved presence.</param>
/// <param name="StateWriteBytes">The exact state_write_bytes value with preserved presence.</param>
/// <param name="BlobReadBytes">The exact blob_read_bytes value with preserved presence.</param>
/// <param name="BlobWriteBytes">The exact blob_write_bytes value with preserved presence.</param>
/// <param name="LogBytes">The exact log_bytes value with preserved presence.</param>
/// <param name="EffectCount">The exact effect_count value with preserved presence.</param>
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

/// <summary>Transport-neutral Success; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Payload">The exact payload value with preserved presence.</param>
/// <param name="MediaType">The exact media_type value with preserved presence.</param>
/// <param name="CommittedStateVersion">The exact committed_state_version value with preserved presence.</param>
/// <param name="EffectIds">The exact effect_ids value with preserved presence.</param>
/// <param name="Metadata">The exact metadata value with preserved presence.</param>
public sealed record Success(
    ReadOnlyMemory<byte> Payload,
    string MediaType,
    string? CommittedStateVersion,
    IReadOnlyList<string> EffectIds,
    IReadOnlyDictionary<string, string> Metadata);

/// <summary>Transport-neutral DeclaredError; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Code">The exact code value with preserved presence.</param>
/// <param name="Message">The exact message value with preserved presence.</param>
/// <param name="Payload">The exact payload value with preserved presence.</param>
/// <param name="MediaType">The exact media_type value with preserved presence.</param>
/// <param name="Metadata">The exact metadata value with preserved presence.</param>
public sealed record DeclaredError(
    string Code,
    string Message,
    ReadOnlyMemory<byte> Payload,
    string MediaType,
    IReadOnlyDictionary<string, string> Metadata);

/// <summary>Transport-neutral InvokeResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="ActivationId">The exact activation_id value with preserved presence.</param>
/// <param name="RevisionId">The exact revision_id value with preserved presence.</param>
/// <param name="ReleaseDigest">The exact release_digest value with preserved presence.</param>
/// <param name="RouteGeneration">The exact route_generation value with preserved presence.</param>
/// <param name="Success">The exact success value with preserved presence.</param>
/// <param name="DeclaredError">The exact declared_error value with preserved presence.</param>
/// <param name="PlatformFailure">The exact platform_failure value with preserved presence.</param>
/// <param name="Consumption">The exact consumption value with preserved presence.</param>
/// <param name="PublicationId">The exact publication_id value with preserved presence.</param>
public sealed record InvokeResponse(
    string ActivationId,
    string RevisionId,
    string ReleaseDigest,
    ulong RouteGeneration,
    Success? Success,
    DeclaredError? DeclaredError,
    PlatformError? PlatformFailure,
    BudgetConsumption? Consumption,
    string? PublicationId);

/// <summary>Transport-neutral CancelRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="ActivationId">The exact activation_id value with preserved presence.</param>
/// <param name="Reason">The exact reason value with preserved presence.</param>
public sealed record CancelRequest(
    string ActivationId,
    string Reason);

/// <summary>Transport-neutral CancelResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Disposition">The exact disposition value with preserved presence.</param>
/// <param name="TerminalState">The exact terminal_state value with preserved presence.</param>
public sealed record CancelResponse(
    CancelDisposition Disposition,
    string? TerminalState);

/// <summary>Transport-neutral GetActivationRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="ActivationId">The exact activation_id value with preserved presence.</param>
public sealed record GetActivationRequest(
    string ActivationId);

/// <summary>Transport-neutral ActivationSuccessSummary; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="CommittedStateVersion">The exact committed_state_version value with preserved presence.</param>
/// <param name="EffectIds">The exact effect_ids value with preserved presence.</param>
/// <param name="Metadata">The exact metadata value with preserved presence.</param>
public sealed record ActivationSuccessSummary(
    string? CommittedStateVersion,
    IReadOnlyList<string> EffectIds,
    IReadOnlyDictionary<string, string> Metadata);

/// <summary>Transport-neutral ActivationStatus; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="ActivationId">The exact activation_id value with preserved presence.</param>
/// <param name="Phase">The exact phase value with preserved presence.</param>
/// <param name="TerminalState">The exact terminal_state value with preserved presence.</param>
/// <param name="LastUpdatedUnixMillis">The exact last_updated_unix_millis value with preserved presence.</param>
/// <param name="Metadata">The exact metadata value with preserved presence.</param>
/// <param name="Succeeded">The exact succeeded value with preserved presence.</param>
/// <param name="DeclaredError">The exact declared_error value with preserved presence.</param>
/// <param name="PlatformFailure">The exact platform_failure value with preserved presence.</param>
/// <param name="FinalConsumption">The exact final_consumption value with preserved presence.</param>
/// <param name="TerminalAtUnixMillis">The exact terminal_at_unix_millis value with preserved presence.</param>
public sealed record ActivationStatus(
    string ActivationId,
    string Phase,
    string? TerminalState,
    ulong LastUpdatedUnixMillis,
    IReadOnlyDictionary<string, string> Metadata,
    ActivationSuccessSummary? Succeeded,
    DeclaredError? DeclaredError,
    PlatformError? PlatformFailure,
    BudgetConsumption? FinalConsumption,
    ulong? TerminalAtUnixMillis);

/// <summary>Transport-neutral Policy; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Id">The exact id value with preserved presence.</param>
/// <param name="Metadata">The exact metadata value with preserved presence.</param>
/// <param name="Document">The exact document value with preserved presence.</param>
/// <param name="Generation">The exact generation value with preserved presence.</param>
/// <param name="Language">The exact language value with preserved presence.</param>
/// <param name="RecordKind">The exact record_kind value with preserved presence.</param>
/// <param name="ContentDigest">The exact content_digest value with preserved presence.</param>
/// <param name="Revoked">The exact revoked value with preserved presence.</param>
public sealed record Policy(
    string Id,
    ObjectMetadata? Metadata,
    string Document,
    ulong Generation,
    string Language,
    CapabilityPolicyRecordKind RecordKind,
    string ContentDigest,
    bool Revoked);

/// <summary>Transport-neutral ApplyPolicyRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Policy">The exact policy value with preserved presence.</param>
/// <param name="ExpectedGeneration">The exact expected_generation value with preserved presence.</param>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
public sealed record ApplyPolicyRequest(
    Policy? Policy,
    ulong? ExpectedGeneration,
    string OperationId);

/// <summary>Transport-neutral CapabilityPolicyOperation; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
/// <param name="Tenant">The exact tenant value with preserved presence.</param>
/// <param name="Id">The exact id value with preserved presence.</param>
/// <param name="RecordKind">The exact record_kind value with preserved presence.</param>
/// <param name="Generation">The exact generation value with preserved presence.</param>
/// <param name="ContentDigest">The exact content_digest value with preserved presence.</param>
/// <param name="Revoked">The exact revoked value with preserved presence.</param>
public sealed record CapabilityPolicyOperation(
    string OperationId,
    string Tenant,
    string Id,
    CapabilityPolicyRecordKind RecordKind,
    ulong Generation,
    string ContentDigest,
    bool Revoked);

/// <summary>Transport-neutral ApplyPolicyResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Policy">The exact policy value with preserved presence.</param>
/// <param name="Receipt">The exact receipt value with preserved presence.</param>
public sealed record ApplyPolicyResponse(
    Policy? Policy,
    CapabilityPolicyOperation? Receipt);

/// <summary>Transport-neutral GetPolicyRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Id">The exact id value with preserved presence.</param>
/// <param name="RecordKind">The exact record_kind value with preserved presence.</param>
public sealed record GetPolicyRequest(
    string Id,
    CapabilityPolicyRecordKind RecordKind);

/// <summary>Transport-neutral GetPolicyResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Policy">The exact policy value with preserved presence.</param>
public sealed record GetPolicyResponse(
    Policy? Policy);

/// <summary>Transport-neutral GetPolicyOperationRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
public sealed record GetPolicyOperationRequest(
    string OperationId);

/// <summary>Transport-neutral GetPolicyOperationResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Receipt">The exact receipt value with preserved presence.</param>
public sealed record GetPolicyOperationResponse(
    CapabilityPolicyOperation? Receipt);

/// <summary>Transport-neutral ListPoliciesRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="RecordKind">The exact record_kind value with preserved presence.</param>
/// <param name="Page">The exact page value with preserved presence.</param>
public sealed record ListPoliciesRequest(
    CapabilityPolicyRecordKind RecordKind,
    PageRequest? Page);

/// <summary>Transport-neutral ListPoliciesResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Policies">The exact policies value with preserved presence.</param>
/// <param name="CatalogGeneration">The exact catalog_generation value with preserved presence.</param>
/// <param name="Page">The exact page value with preserved presence.</param>
public sealed record ListPoliciesResponse(
    IReadOnlyList<Policy> Policies,
    ulong CatalogGeneration,
    PageResponse? Page);

/// <summary>Transport-neutral CapabilityInspectionPolicy; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Id">The exact id value with preserved presence.</param>
/// <param name="Revision">The exact revision value with preserved presence.</param>
/// <param name="Digest">The exact digest value with preserved presence.</param>
public sealed record CapabilityInspectionPolicy(
    string Id,
    ulong Revision,
    string Digest);

/// <summary>Transport-neutral CapabilityBindingInspection; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="DefinitionDigest">The exact definition_digest value with preserved presence.</param>
/// <param name="ProviderBinding">The exact provider_binding value with preserved presence.</param>
/// <param name="Policies">The exact policies value with preserved presence.</param>
/// <param name="ProviderProfile">The exact provider_profile value with preserved presence.</param>
/// <param name="ProviderConfigurationDigest">The exact provider_configuration_digest value with preserved presence.</param>
/// <param name="ProviderConfigurationEpoch">The exact provider_configuration_epoch value with preserved presence.</param>
/// <param name="State">The exact state value with preserved presence.</param>
public sealed record CapabilityBindingInspection(
    string? DefinitionDigest,
    CapabilityInspectionPolicy? ProviderBinding,
    IReadOnlyList<CapabilityInspectionPolicy> Policies,
    string ProviderProfile,
    string ProviderConfigurationDigest,
    ulong ProviderConfigurationEpoch,
    string State);

/// <summary>Transport-neutral CapabilityDescriptor; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Id">The exact id value with preserved presence.</param>
/// <param name="Contract">The exact contract value with preserved presence.</param>
/// <param name="Provider">The exact provider value with preserved presence.</param>
/// <param name="Operations">The exact operations value with preserved presence.</param>
/// <param name="Attributes">The exact attributes value with preserved presence.</param>
/// <param name="Inspection">The exact inspection value with preserved presence.</param>
public sealed record CapabilityDescriptor(
    string Id,
    string Contract,
    string Provider,
    IReadOnlyList<string> Operations,
    IReadOnlyDictionary<string, string> Attributes,
    CapabilityBindingInspection? Inspection);

/// <summary>Transport-neutral ListCapabilitiesRequest; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="ContractPrefix">The exact contract_prefix value with preserved presence.</param>
/// <param name="Provider">The exact provider value with preserved presence.</param>
/// <param name="Page">The exact page value with preserved presence.</param>
/// <param name="DeploymentId">The exact deployment_id value with preserved presence.</param>
/// <param name="IncludeNodeUsage">The exact include_node_usage value with preserved presence.</param>
public sealed record ListCapabilitiesRequest(
    string? ContractPrefix,
    string? Provider,
    PageRequest? Page,
    string DeploymentId,
    bool IncludeNodeUsage);

/// <summary>Transport-neutral CapabilityInspectionRevision; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="DeploymentId">The exact deployment_id value with preserved presence.</param>
/// <param name="RevisionId">The exact revision_id value with preserved presence.</param>
/// <param name="ComponentDigest">The exact component_digest value with preserved presence.</param>
/// <param name="PublicationId">The exact publication_id value with preserved presence.</param>
/// <param name="RouteGeneration">The exact route_generation value with preserved presence.</param>
/// <param name="CatalogTransaction">The exact catalog_transaction value with preserved presence.</param>
public sealed record CapabilityInspectionRevision(
    string DeploymentId,
    string RevisionId,
    string ComponentDigest,
    string? PublicationId,
    ulong RouteGeneration,
    ulong CatalogTransaction);

/// <summary>Transport-neutral CapabilityResourceUsage; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Scope">The exact scope value with preserved presence.</param>
/// <param name="Counters">The exact counters value with preserved presence.</param>
/// <param name="Unavailable">The exact unavailable value with preserved presence.</param>
public sealed record CapabilityResourceUsage(
    string Scope,
    IReadOnlyDictionary<string, ulong> Counters,
    IReadOnlyList<string> Unavailable);

/// <summary>Transport-neutral ListCapabilitiesResponse; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Capabilities">The exact capabilities value with preserved presence.</param>
/// <param name="Page">The exact page value with preserved presence.</param>
/// <param name="Revision">The exact revision value with preserved presence.</param>
/// <param name="TenantUsage">The exact tenant_usage value with preserved presence.</param>
/// <param name="NodeUsage">The exact node_usage value with preserved presence.</param>
/// <param name="State">The exact state value with preserved presence.</param>
public sealed record ListCapabilitiesResponse(
    IReadOnlyList<CapabilityDescriptor> Capabilities,
    PageResponse? Page,
    CapabilityInspectionRevision? Revision,
    CapabilityResourceUsage? TenantUsage,
    CapabilityResourceUsage? NodeUsage,
    string State);

/// <summary>Transport-neutral CapabilityInspectionCeiling; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Operations">The exact operations value with preserved presence.</param>
/// <param name="InputBytes">The exact input_bytes value with preserved presence.</param>
/// <param name="OutputBytes">The exact output_bytes value with preserved presence.</param>
/// <param name="WallTimeMillis">The exact wall_time_millis value with preserved presence.</param>
public sealed record CapabilityInspectionCeiling(
    uint Operations,
    ulong InputBytes,
    ulong OutputBytes,
    ulong WallTimeMillis);

/// <summary>Transport-neutral PublicationRef; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Id">The exact id value with preserved presence.</param>
/// <param name="Tenant">The exact tenant value with preserved presence.</param>
public sealed record PublicationRef(
    string Id,
    string Tenant);

/// <summary>Transport-neutral ReleaseSelector; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="ComponentDigest">The exact component_digest value with preserved presence.</param>
/// <param name="Publication">The exact publication value with preserved presence.</param>
public sealed record ReleaseSelector(
    string? ComponentDigest,
    PublicationRef? Publication);

/// <summary>Transport-neutral PublicationIdentity; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Publication">The exact publication value with preserved presence.</param>
/// <param name="ComponentDigest">The exact component_digest value with preserved presence.</param>
/// <param name="PackageDigest">The exact package_digest value with preserved presence.</param>
public sealed record PublicationIdentity(
    PublicationRef Publication,
    string ComponentDigest,
    string PackageDigest);

/// <summary>Transport-neutral CallOptions; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="TimeoutMillis">The exact timeout_millis value with preserved presence.</param>
public sealed record CallOptions(
    ulong? TimeoutMillis);

/// <summary>Transport-neutral RequestIdentity; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="ActivationId">The exact activation_id value with preserved presence.</param>
/// <param name="OperationId">The exact operation_id value with preserved presence.</param>
public sealed record RequestIdentity(
    string? ActivationId,
    string? OperationId);

/// <summary>Transport-neutral UnsupportedWireValue; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Field">The exact field value with preserved presence.</param>
/// <param name="Value">The exact value value with preserved presence.</param>
public sealed record UnsupportedWireValue(
    string Field,
    string Value);

/// <summary>Transport-neutral ResponseMetadata; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Identity">The exact identity value with preserved presence.</param>
/// <param name="Outcome">The exact outcome value with preserved presence.</param>
/// <param name="AuditAck">The exact audit_ack value with preserved presence.</param>
/// <param name="AuditStatus">The exact audit_status value with preserved presence.</param>
/// <param name="AuditAttemptSequence">The exact audit_attempt_sequence value with preserved presence.</param>
public sealed record ResponseMetadata(
    RequestIdentity Identity,
    OutcomeKnowledge Outcome,
    AuditAck? AuditAck,
    string? AuditStatus,
    ulong? AuditAttemptSequence);

/// <summary>Transport-neutral ClientFailure; see the shared client profile for authority and lifetime rules.</summary>
/// <param name="Category">The exact category value with preserved presence.</param>
/// <param name="Message">The exact message value with preserved presence.</param>
/// <param name="GrpcStatus">The exact grpc_status value with preserved presence.</param>
/// <param name="PlatformError">The exact platform_error value with preserved presence.</param>
/// <param name="Dispatched">The exact dispatched value with preserved presence.</param>
/// <param name="Outcome">The exact outcome value with preserved presence.</param>
/// <param name="Identity">The exact identity value with preserved presence.</param>
/// <param name="AuditAck">The exact audit_ack value with preserved presence.</param>
/// <param name="AuditStatus">The exact audit_status value with preserved presence.</param>
/// <param name="UnsupportedWireValue">The exact unsupported_wire_value value with preserved presence.</param>
/// <param name="AuditAttemptSequence">The exact audit_attempt_sequence value with preserved presence.</param>
public sealed record ClientFailure(
    FailureCategory Category,
    string Message,
    int? GrpcStatus,
    PlatformError? PlatformError,
    bool Dispatched,
    OutcomeKnowledge Outcome,
    RequestIdentity Identity,
    AuditAck? AuditAck,
    string? AuditStatus,
    UnsupportedWireValue? UnsupportedWireValue,
    ulong? AuditAttemptSequence);

/// <summary>A fully owned unary response and independent recovery metadata.</summary>
/// <typeparam name="Response">The response model.</typeparam>
/// <param name="Value">The decoded response.</param>
/// <param name="Metadata">The independent outcome and audit observations.</param>
public sealed record ClientResponse<Response>(Response Value, ResponseMetadata Metadata);

/// <summary>The common eight-operation client profile; cancellation is local, not server cleanup.</summary>
public interface IClientProfile
{
    /// <summary>Calls Invoke once within a bounded local deadline.</summary>
    ValueTask<ClientResponse<InvokeResponse>> InvokeAsync(
        InvokeRequest request,
        CallOptions options,
        CancellationToken cancellationToken = default);

    /// <summary>Calls Cancel once within a bounded local deadline.</summary>
    ValueTask<ClientResponse<CancelResponse>> CancelAsync(
        CancelRequest request,
        CallOptions options,
        CancellationToken cancellationToken = default);

    /// <summary>Calls GetActivation once within a bounded local deadline.</summary>
    ValueTask<ClientResponse<ActivationStatus>> GetActivationAsync(
        GetActivationRequest request,
        CallOptions options,
        CancellationToken cancellationToken = default);

    /// <summary>Calls GetPolicy once within a bounded local deadline.</summary>
    ValueTask<ClientResponse<GetPolicyResponse>> GetPolicyAsync(
        GetPolicyRequest request,
        CallOptions options,
        CancellationToken cancellationToken = default);

    /// <summary>Calls ListPolicies once within a bounded local deadline.</summary>
    ValueTask<ClientResponse<ListPoliciesResponse>> ListPoliciesAsync(
        ListPoliciesRequest request,
        CallOptions options,
        CancellationToken cancellationToken = default);

    /// <summary>Calls ListCapabilities once within a bounded local deadline.</summary>
    ValueTask<ClientResponse<ListCapabilitiesResponse>> ListCapabilitiesAsync(
        ListCapabilitiesRequest request,
        CallOptions options,
        CancellationToken cancellationToken = default);

    /// <summary>Calls ApplyPolicy once within a bounded local deadline.</summary>
    ValueTask<ClientResponse<ApplyPolicyResponse>> ApplyPolicyAsync(
        ApplyPolicyRequest request,
        CallOptions options,
        CancellationToken cancellationToken = default);

    /// <summary>Calls GetPolicyOperation once within a bounded local deadline.</summary>
    ValueTask<ClientResponse<GetPolicyOperationResponse>> GetPolicyOperationAsync(
        GetPolicyOperationRequest request,
        CallOptions options,
        CancellationToken cancellationToken = default);

}

/// <summary>A typed local or RPC failure, separate from an invocation outcome.</summary>
public sealed class ClientException : Exception
{
    /// <summary>Retained, redacted failure and recovery facts.</summary>
    public ClientFailure Failure { get; }

    /// <summary>Retains failure facts without changing operation knowledge.</summary>
    public ClientException(ClientFailure failure) : base(failure.Message) { Failure = failure; }
}

/// <summary>Local cancellation with retained dispatch and recovery facts.</summary>
public sealed class ClientCancellationException : OperationCanceledException
{
    /// <summary>The independent failure and recovery facts.</summary>
    public ClientFailure Failure { get; }

    /// <summary>Retains local cancellation without implying server cleanup.</summary>
    public ClientCancellationException(ClientFailure failure, CancellationToken cancellationToken)
        : base(failure.Message, cancellationToken) { Failure = failure; }
}

/// <summary>Lossless canonical unsigned decimal conversion for shared fixtures.</summary>
public static class UnsignedDecimal
{
    /// <summary>Parses zero through UInt64.MaxValue without signs, whitespace or leading zeroes.</summary>
    public static ulong Parse(string value)
    {
        if (value.Length == 0 || value.Length > 20 || (value.Length > 1 && value[0] == '0'))
            throw new FormatException("invalid uint64 decimal");
        foreach (char digit in value)
            if (digit < '0' || digit > '9') throw new FormatException("invalid uint64 digit");
        return ulong.Parse(value, NumberStyles.None, CultureInfo.InvariantCulture);
    }

    /// <summary>Formats all unsigned bits as canonical decimal.</summary>
    public static string Format(ulong value) => value.ToString(CultureInfo.InvariantCulture);
}
