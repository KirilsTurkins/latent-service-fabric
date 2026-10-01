// Generated from the authoritative transaction client descriptors.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CommandCancelDisposition(pub i32);

impl CommandCancelDisposition {
    pub const UNSPECIFIED: Self = Self(0);
    pub const REQUESTED: Self = Self(1);
    pub const ALREADY_COMMITTED: Self = Self(2);
    pub const ALREADY_TERMINAL: Self = Self(3);
    pub const NOT_FOUND: Self = Self(4);
    pub const RECOVERY_REQUIRED: Self = Self(5);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CommandOutcome(pub i32);

impl CommandOutcome {
    pub const UNSPECIFIED: Self = Self(0);
    pub const IN_PROGRESS: Self = Self(1);
    pub const COMMITTED: Self = Self(2);
    pub const REJECTED: Self = Self(3);
    pub const ABORTED: Self = Self(4);
    pub const UNKNOWN: Self = Self(5);
    pub const RECOVERY_REQUIRED: Self = Self(6);
    pub const EXPIRED: Self = Self(7);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DispatcherAction(pub i32);

impl DispatcherAction {
    pub const UNSPECIFIED: Self = Self(0);
    pub const PAUSE: Self = Self(1);
    pub const RESUME: Self = Self(2);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DispatcherFailure(pub i32);

impl DispatcherFailure {
    pub const UNSPECIFIED: Self = Self(0);
    pub const NONE: Self = Self(1);
    pub const AUTHORITY: Self = Self(2);
    pub const STORE: Self = Self(3);
    pub const WORKER: Self = Self(4);
    pub const RESTORE_CHECKPOINT: Self = Self(5);
    pub const ADMISSION_CLOSED: Self = Self(6);
    pub const CONFIGURATION: Self = Self(7);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct DispatcherScope(pub i32);

impl DispatcherScope {
    pub const UNSPECIFIED: Self = Self(0);
    pub const NODE: Self = Self(1);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct EffectDisposition(pub i32);

impl EffectDisposition {
    pub const UNSPECIFIED: Self = Self(0);
    pub const PENDING: Self = Self(1);
    pub const DISPATCHING: Self = Self(2);
    pub const PROVIDER_ACKNOWLEDGED: Self = Self(3);
    pub const KNOWN_FAILURE: Self = Self(4);
    pub const UNCERTAIN_AFTER_DISPATCH: Self = Self(5);
    pub const EXPIRED: Self = Self(6);
    pub const POLICY_BLOCKED: Self = Self(7);
    pub const ADMINISTRATIVELY_TERMINATED: Self = Self(8);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NamespaceMutationKind(pub i32);

impl NamespaceMutationKind {
    pub const UNSPECIFIED: Self = Self(0);
    pub const CREATE: Self = Self(1);
    pub const QUIESCE: Self = Self(2);
    pub const RETIRE: Self = Self(3);
    pub const DESTROY: Self = Self(4);
    pub const RECREATE: Self = Self(5);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct NamespaceStatus(pub i32);

impl NamespaceStatus {
    pub const UNSPECIFIED: Self = Self(0);
    pub const ACTIVE: Self = Self(1);
    pub const QUIESCING: Self = Self(2);
    pub const RETIRED: Self = Self(3);
    pub const TOMBSTONE: Self = Self(4);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct StateMutationKind(pub i32);

impl StateMutationKind {
    pub const UNSPECIFIED: Self = Self(0);
    pub const RETRY_KNOWN_FAILED_EFFECT: Self = Self(1);
    pub const TERMINATE_EFFECT: Self = Self(2);
    pub const PURGE_EXPIRED_PAYLOAD: Self = Self(3);
    pub const CHECKPOINT_NAMESPACE: Self = Self(4);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct StateOperationDisposition(pub i32);

impl StateOperationDisposition {
    pub const UNSPECIFIED: Self = Self(0);
    pub const COMMITTED: Self = Self(1);
    pub const CONFLICT: Self = Self(2);
    pub const REJECTED: Self = Self(3);
    pub const UNKNOWN: Self = Self(4);
    pub const RECOVERY_REQUIRED: Self = Self(5);
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AbortFence {
    pub command_id: String,
    pub attempt_id: String,
    pub transaction_id: String,
    pub owner_fence: Vec<u8>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct TransactionProfile {
    pub profile: String,
    pub host_abi_digest: String,
    pub preparation_profile_digest: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct NamespaceSelector {
    pub tenant: String,
    pub namespace: String,
    pub incarnation: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CommandSelector {
    pub namespace: Option<NamespaceSelector>,
    pub operation: String,
    pub entity: Option<String>,
    pub client_key: String,
    pub shared_recovery_scope: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LookupCommandRequest {
    pub profile: Option<TransactionProfile>,
    pub command: Option<CommandSelector>,
    pub attempt_id: Option<String>,
    pub authorization_publication: Option<crate::management::PublicationRef>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CancelCommandRequest {
    pub command: Option<LookupCommandRequest>,
    pub reason: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CommandKey {
    pub namespace: Option<NamespaceSelector>,
    pub recovery_scope: String,
    pub operation: String,
    pub entity: Option<String>,
    pub client_key: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SourceIdentity {
    pub publication_id: String,
    pub revision_id: String,
    pub release_digest: String,
    pub route_generation: u64,
    pub contract_digest: String,
    pub state_schema: String,
    pub input_format: String,
    pub result_format: String,
    pub component_digest: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CommitReceipt {
    pub command_id: String,
    pub attempt_id: String,
    pub transaction_id: String,
    pub committed_version: Vec<u8>,
    pub committed_at_unix_millis: u64,
    pub effect_ids: Vec<String>,
    pub receipt_id: String,
    pub source: Option<SourceIdentity>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LinkedRetention {
    pub record_format: String,
    pub record_version: u32,
    pub payload_expires_at_unix_millis: Option<u64>,
    pub identity_expires_at_unix_millis: Option<u64>,
    pub remaining_recovery_millis: Option<u64>,
    pub required_record_ids: Vec<String>,
    pub payload_available: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CommandInspection {
    pub key: Option<CommandKey>,
    pub command_id: String,
    pub attempt_id: String,
    pub fingerprint_sha256: Vec<u8>,
    pub outcome: CommandOutcome,
    pub metadata_durable: bool,
    pub application_state_committed: bool,
    pub source: Option<SourceIdentity>,
    pub success: Option<crate::management::Success>,
    pub business_rejection: Option<crate::management::DeclaredError>,
    pub technical_failure: Option<crate::management::PlatformError>,
    pub commit: Option<CommitReceipt>,
    pub proven_abort: Option<AbortFence>,
    pub retention: Option<LinkedRetention>,
    pub cleanup_failure: Option<crate::management::PlatformError>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CancelCommandResponse {
    pub disposition: CommandCancelDisposition,
    pub command: Option<CommandInspection>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DispatcherGeneration {
    pub owner_epoch: u64,
    pub revision: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ControlDispatcherRequest {
    pub profile: Option<TransactionProfile>,
    pub scope: DispatcherScope,
    pub operation_id: String,
    pub action: DispatcherAction,
    pub expected_generation: Option<DispatcherGeneration>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DispatcherOperationReceipt {
    pub operation_id: String,
    pub receipt_id: String,
    pub action: DispatcherAction,
    pub authenticated_operator: String,
    pub actor_tenant: String,
    pub before_generation: Option<DispatcherGeneration>,
    pub after_generation: Option<DispatcherGeneration>,
    pub observed_at_unix_millis: u64,
    pub clock_continuity_proven: bool,
    pub restore_review_required: bool,
    pub disposition: StateOperationDisposition,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ControlDispatcherResponse {
    pub receipt: Option<DispatcherOperationReceipt>,
    pub replayed: bool,
    pub published: bool,
    pub paused: bool,
    pub audit_ack: Option<crate::management::AuditAck>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
#[allow(clippy::struct_excessive_bools)]
pub struct DispatcherSnapshot {
    pub generation: Option<DispatcherGeneration>,
    pub paused: bool,
    pub pending_control: bool,
    pub restore_review_required: bool,
    pub admission_closed: bool,
    pub quarantined: bool,
    pub failure: DispatcherFailure,
    pub queued: u64,
    pub active_jobs: u64,
    pub retained_attempt_bytes: u64,
    pub live_workers: u64,
    pub accepted_effects: u64,
    pub physical_owners: u64,
    pub quarantined_physical_owners: u64,
    pub command_owners: u64,
    pub claims: u64,
    pub pending_effects: u64,
    pub uncertain_effects: u64,
    pub blocked_effects: u64,
    pub dead_letter_effects: u64,
    pub counts_observed_at_unix_millis: u64,
    pub clock_continuity_proven: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EffectReceipt {
    pub effect_id: String,
    pub command_id: String,
    pub command_attempt_id: String,
    pub dispatch_attempt: u32,
    pub disposition: EffectDisposition,
    pub provider_receipt: Option<String>,
    pub failure_code: Option<String>,
    pub occurred_at_unix_millis: u64,
    pub retention: Option<LinkedRetention>,
    pub management_operation_receipt_id: Option<String>,
    pub provider_profile: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct EntityInspection {
    pub entity: String,
    pub version: Vec<u8>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ExpectedVersion {
    pub key: Vec<u8>,
    pub absent: Option<bool>,
    pub version: Option<Vec<u8>>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetDispatcherOperationRequest {
    pub original: Option<ControlDispatcherRequest>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetDispatcherOperationResponse {
    pub receipt: Option<DispatcherOperationReceipt>,
    pub audit_ack: Option<crate::management::AuditAck>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetEffectRequest {
    pub profile: Option<TransactionProfile>,
    pub command: Option<CommandSelector>,
    pub effect_id: String,
    pub authorization_publication: Option<crate::management::PublicationRef>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetEffectResponse {
    pub effect: Option<EffectReceipt>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InspectNamespaceRequest {
    pub profile: Option<TransactionProfile>,
    pub namespace: Option<NamespaceSelector>,
    pub authorization_publication: Option<crate::management::PublicationRef>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetStateOperationReceiptRequest {
    pub namespace: Option<InspectNamespaceRequest>,
    pub operation_id: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct StateOperationReceipt {
    pub operation_id: String,
    pub receipt_id: String,
    pub mutation: StateMutationKind,
    pub namespace: Option<NamespaceSelector>,
    pub authenticated_operator: String,
    pub before_version: Vec<u8>,
    pub after_version: Vec<u8>,
    pub completed_at_unix_millis: u64,
    pub record_id: Option<String>,
    pub policy_digest: String,
    pub disposition: StateOperationDisposition,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct NamespaceOperationReceipt {
    pub operation_id: String,
    pub receipt_id: String,
    pub mutation: NamespaceMutationKind,
    pub namespace: Option<NamespaceSelector>,
    pub authenticated_operator: String,
    pub before_generation: Option<u64>,
    pub after_generation: u64,
    pub status: NamespaceStatus,
    pub state_schema: String,
    pub disposition: StateOperationDisposition,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetStateOperationReceiptResponse {
    pub receipt: Option<StateOperationReceipt>,
    pub namespace_receipt: Option<NamespaceOperationReceipt>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InspectDispatcherRequest {
    pub profile: Option<TransactionProfile>,
    pub scope: DispatcherScope,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InspectDispatcherResponse {
    pub dispatcher: Option<DispatcherSnapshot>,
    pub audit_ack: Option<crate::management::AuditAck>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ViewIdentity {
    pub namespace: Option<NamespaceSelector>,
    pub version: Vec<u8>,
    pub state_schema: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct NamespaceQuota {
    pub state_keys: u64,
    pub state_bytes: u64,
    pub result_rows: u64,
    pub result_bytes: u64,
    pub effect_rows: u64,
    pub effect_bytes: u64,
    pub payload_bytes: u64,
    pub recovery_bytes: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct NamespaceInspection {
    pub view: Option<ViewIdentity>,
    pub encoded_state_bytes: u64,
    pub command_count: u64,
    pub pending_effect_count: u64,
    pub retained_formats: Vec<LinkedRetention>,
    pub engine_profile: String,
    pub engine_profile_digest: String,
    pub status: NamespaceStatus,
    pub quota: Option<NamespaceQuota>,
    pub generation: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InspectNamespaceResponse {
    pub namespace: Option<NamespaceInspection>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RetryAttempt {
    pub request_id: String,
    pub expected_abort: Option<AbortFence>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InvokeCommandRequest {
    pub profile: Option<TransactionProfile>,
    pub invocation: Option<crate::management::InvokeRequest>,
    pub command: Option<CommandSelector>,
    pub input_format: String,
    pub expected_versions: Vec<ExpectedVersion>,
    pub retry_attempt: Option<RetryAttempt>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InvokeCommandResponse {
    pub invocation: Option<crate::management::InvokeResponse>,
    pub command: Option<CommandInspection>,
    pub replayed: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PageRequest {
    pub limit: u32,
    pub cursor: Option<Vec<u8>>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ListEffectHistoryRequest {
    pub effect: Option<GetEffectRequest>,
    pub page: Option<PageRequest>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PageResponse {
    pub next_cursor: Option<Vec<u8>>,
    pub returned_count: u32,
    pub encoded_bytes: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ListEffectHistoryResponse {
    pub receipts: Vec<EffectReceipt>,
    pub page: Option<PageResponse>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LookupCommandResponse {
    pub command: Option<CommandInspection>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LookupCommitRequest {
    pub profile: Option<TransactionProfile>,
    pub command: Option<CommandSelector>,
    pub receipt_id: String,
    pub authorization_publication: Option<crate::management::PublicationRef>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct LookupCommitResponse {
    pub command: Option<CommandInspection>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct NamespaceConfiguration {
    pub state_schema: String,
    pub quota: Option<NamespaceQuota>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MutateNamespaceRequest {
    pub namespace: Option<InspectNamespaceRequest>,
    pub operation_id: String,
    pub mutation: NamespaceMutationKind,
    pub expected_generation: Option<u64>,
    pub configuration: Option<NamespaceConfiguration>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MutateNamespaceResponse {
    pub receipt: Option<NamespaceOperationReceipt>,
    pub replayed: bool,
    pub audit_ack: Option<crate::management::AuditAck>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MutateStateRequest {
    pub namespace: Option<InspectNamespaceRequest>,
    pub operation_id: String,
    pub mutation: StateMutationKind,
    pub record_id: Option<String>,
    pub expected_version: Vec<u8>,
    pub expected_policy_digest: String,
    pub reason: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MutateStateResponse {
    pub receipt: Option<StateOperationReceipt>,
    pub audit_ack: Option<crate::management::AuditAck>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct QueryRequest {
    pub profile: Option<TransactionProfile>,
    pub invocation: Option<crate::management::InvokeRequest>,
    pub namespace: Option<NamespaceSelector>,
    pub entity: Option<String>,
    pub minimum_view_version: Option<Vec<u8>>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct QueryResponse {
    pub invocation: Option<crate::management::InvokeResponse>,
    pub view: Option<ViewIdentity>,
    pub source: Option<SourceIdentity>,
    pub observed_at_unix_millis: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SelectEntityRequest {
    pub namespace: Option<InspectNamespaceRequest>,
    pub prefix: Option<Vec<u8>>,
    pub page: Option<PageRequest>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SelectEntityResponse {
    pub entities: Vec<EntityInspection>,
    pub page: Option<PageResponse>,
}

/// Constructs a protocol descriptor; this value grants no authority.
#[must_use]
pub fn current_profile() -> TransactionProfile {
    TransactionProfile {
        profile: "lsf-transaction-v1".into(),
        host_abi_digest: "sha256:3b85f790f85ab23d36e492d7bd4a04a1b8aab87fc6f67dd7d7498bcf28129d35"
            .into(),
        preparation_profile_digest:
            "sha256:6acd7a248633dd01c9cdcbf8a1ed33fc5e6aa1d2edb09b7d89e53fda594b5507".into(),
    }
}
