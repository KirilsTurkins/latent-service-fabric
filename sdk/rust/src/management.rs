use std::collections::BTreeMap;
use std::future::Future;
use std::pin::Pin;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct AuditAckStatus(pub i32);

impl AuditAckStatus {
    pub const UNSPECIFIED: Self = Self(0);
    pub const DURABLE: Self = Self(1);
    pub const OUTCOME_UNKNOWN: Self = Self(2);
    pub const AUDIT_UNAVAILABLE: Self = Self(3);
    pub const DISABLED: Self = Self(4);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CancelDisposition(pub i32);

impl CancelDisposition {
    pub const UNSPECIFIED: Self = Self(0);
    pub const ACCEPTED: Self = Self(1);
    pub const ALREADY_TERMINAL: Self = Self(2);
    pub const NOT_FOUND: Self = Self(3);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct CapabilityPolicyRecordKind(pub i32);

impl CapabilityPolicyRecordKind {
    pub const UNSPECIFIED: Self = Self(0);
    pub const POLICY: Self = Self(1);
    pub const PROVIDER_BINDING: Self = Self(2);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct FailureCategory(pub i32);

impl FailureCategory {
    pub const UNSPECIFIED: Self = Self(0);
    pub const LOCAL_CANCELLED: Self = Self(1);
    pub const DEADLINE: Self = Self(2);
    pub const TRANSPORT: Self = Self(3);
    pub const RPC: Self = Self(4);
    pub const DECODE: Self = Self(5);
    pub const LIMIT: Self = Self(6);
    pub const INVALID_REQUEST: Self = Self(7);
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct OutcomeKnowledge(pub i32);

impl OutcomeKnowledge {
    pub const UNSPECIFIED: Self = Self(0);
    pub const NOT_DISPATCHED: Self = Self(1);
    pub const UNKNOWN: Self = Self(2);
    pub const OBSERVED: Self = Self(3);
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ResourceBudget {
    pub cpu_fuel: u64,
    pub memory_bytes: u64,
    pub child_calls: u32,
    pub outbound_requests: u32,
    pub state_read_bytes: u64,
    pub state_write_bytes: u64,
    pub blob_read_bytes: u64,
    pub blob_write_bytes: u64,
    pub log_bytes: u64,
    pub effect_count: u32,
    pub wall_time_limit_millis: Option<u64>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ErrorDetail {
    pub kind: String,
    pub fields: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PlatformError {
    pub code: String,
    pub message: String,
    pub retryable: bool,
    pub detail_items: Vec<ErrorDetail>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ObjectMetadata {
    pub name: String,
    pub tenant: Option<String>,
    pub namespace: Option<String>,
    pub labels: BTreeMap<String, String>,
    pub annotations: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PageRequest {
    pub page_size: u32,
    pub page_token: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PageResponse {
    pub next_page_token: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct AuditAck {
    pub status: AuditAckStatus,
    pub attempt_sequence: Option<u64>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InvocationTarget {
    pub tenant: String,
    pub service: String,
    pub contract: String,
    pub function: String,
    pub route: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InvokeRequest {
    pub activation_id: Option<String>,
    pub parent_activation_id: Option<String>,
    pub root_activation_id: Option<String>,
    pub target: Option<InvocationTarget>,
    pub payload: Vec<u8>,
    pub media_type: String,
    pub deadline_unix_millis: Option<u64>,
    pub priority: u32,
    pub idempotency_key: Option<String>,
    pub budget: Option<ResourceBudget>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BudgetConsumption {
    pub cpu_fuel: u64,
    pub peak_memory_bytes: u64,
    pub wall_time_micros: u64,
    pub child_calls: u32,
    pub outbound_requests: u32,
    pub state_read_bytes: u64,
    pub state_write_bytes: u64,
    pub blob_read_bytes: u64,
    pub blob_write_bytes: u64,
    pub log_bytes: u64,
    pub effect_count: u32,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Success {
    pub payload: Vec<u8>,
    pub media_type: String,
    pub committed_state_version: Option<String>,
    pub effect_ids: Vec<String>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DeclaredError {
    pub code: String,
    pub message: String,
    pub payload: Vec<u8>,
    pub media_type: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct InvokeResponse {
    pub activation_id: String,
    pub revision_id: String,
    pub release_digest: String,
    pub route_generation: u64,
    pub success: Option<Success>,
    pub declared_error: Option<DeclaredError>,
    pub platform_failure: Option<PlatformError>,
    pub consumption: Option<BudgetConsumption>,
    pub publication_id: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CancelRequest {
    pub activation_id: String,
    pub reason: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CancelResponse {
    pub disposition: CancelDisposition,
    pub terminal_state: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetActivationRequest {
    pub activation_id: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ActivationSuccessSummary {
    pub committed_state_version: Option<String>,
    pub effect_ids: Vec<String>,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ActivationStatus {
    pub activation_id: String,
    pub phase: String,
    pub terminal_state: Option<String>,
    pub last_updated_unix_millis: u64,
    pub metadata: BTreeMap<String, String>,
    pub succeeded: Option<ActivationSuccessSummary>,
    pub declared_error: Option<DeclaredError>,
    pub platform_failure: Option<PlatformError>,
    pub final_consumption: Option<BudgetConsumption>,
    pub terminal_at_unix_millis: Option<u64>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Policy {
    pub id: String,
    pub metadata: Option<ObjectMetadata>,
    pub document: String,
    pub generation: u64,
    pub language: String,
    pub record_kind: CapabilityPolicyRecordKind,
    pub content_digest: String,
    pub revoked: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ApplyPolicyRequest {
    pub policy: Option<Policy>,
    pub expected_generation: Option<u64>,
    pub operation_id: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapabilityPolicyOperation {
    pub operation_id: String,
    pub tenant: String,
    pub id: String,
    pub record_kind: CapabilityPolicyRecordKind,
    pub generation: u64,
    pub content_digest: String,
    pub revoked: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ApplyPolicyResponse {
    pub policy: Option<Policy>,
    pub receipt: Option<CapabilityPolicyOperation>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetPolicyRequest {
    pub id: String,
    pub record_kind: CapabilityPolicyRecordKind,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetPolicyResponse {
    pub policy: Option<Policy>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetPolicyOperationRequest {
    pub operation_id: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GetPolicyOperationResponse {
    pub receipt: Option<CapabilityPolicyOperation>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ListPoliciesRequest {
    pub record_kind: CapabilityPolicyRecordKind,
    pub page: Option<PageRequest>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ListPoliciesResponse {
    pub policies: Vec<Policy>,
    pub catalog_generation: u64,
    pub page: Option<PageResponse>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapabilityInspectionPolicy {
    pub id: String,
    pub revision: u64,
    pub digest: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapabilityBindingInspection {
    pub definition_digest: Option<String>,
    pub provider_binding: Option<CapabilityInspectionPolicy>,
    pub policies: Vec<CapabilityInspectionPolicy>,
    pub provider_profile: String,
    pub provider_configuration_digest: String,
    pub provider_configuration_epoch: u64,
    pub state: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapabilityDescriptor {
    pub id: String,
    pub contract: String,
    pub provider: String,
    pub operations: Vec<String>,
    pub attributes: BTreeMap<String, String>,
    pub inspection: Option<CapabilityBindingInspection>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ListCapabilitiesRequest {
    pub contract_prefix: Option<String>,
    pub provider: Option<String>,
    pub page: Option<PageRequest>,
    pub deployment_id: String,
    pub include_node_usage: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapabilityInspectionRevision {
    pub deployment_id: String,
    pub revision_id: String,
    pub component_digest: String,
    pub publication_id: Option<String>,
    pub route_generation: u64,
    pub catalog_transaction: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapabilityResourceUsage {
    pub scope: String,
    pub counters: BTreeMap<String, u64>,
    pub unavailable: Vec<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ListCapabilitiesResponse {
    pub capabilities: Vec<CapabilityDescriptor>,
    pub page: Option<PageResponse>,
    pub revision: Option<CapabilityInspectionRevision>,
    pub tenant_usage: Option<CapabilityResourceUsage>,
    pub node_usage: Option<CapabilityResourceUsage>,
    pub state: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CapabilityInspectionCeiling {
    pub operations: u32,
    pub input_bytes: u64,
    pub output_bytes: u64,
    pub wall_time_millis: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PublicationRef {
    pub id: String,
    pub tenant: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ReleaseSelector {
    pub component_digest: Option<String>,
    pub publication: Option<PublicationRef>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PublicationIdentity {
    pub publication: PublicationRef,
    pub component_digest: String,
    pub package_digest: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CallOptions {
    pub timeout_millis: Option<u64>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RequestIdentity {
    pub activation_id: Option<String>,
    pub operation_id: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct UnsupportedWireValue {
    pub field: String,
    pub value: String,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ResponseMetadata {
    pub identity: RequestIdentity,
    pub outcome: OutcomeKnowledge,
    pub audit_ack: Option<AuditAck>,
    pub audit_status: Option<String>,
    pub audit_attempt_sequence: Option<u64>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ClientFailure {
    pub category: FailureCategory,
    pub message: String,
    pub grpc_status: Option<i32>,
    pub platform_error: Option<PlatformError>,
    pub dispatched: bool,
    pub outcome: OutcomeKnowledge,
    pub identity: RequestIdentity,
    pub audit_ack: Option<AuditAck>,
    pub audit_status: Option<String>,
    pub unsupported_wire_value: Option<UnsupportedWireValue>,
    pub audit_attempt_sequence: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ClientResponse<Response> {
    pub value: Response,
    pub metadata: ResponseMetadata,
}

pub type ClientFuture<'call, Response> =
    Pin<Box<dyn Future<Output = Result<ClientResponse<Response>, ClientFailure>> + Send + 'call>>;

pub trait ClientProfile: Send + Sync {
    fn invoke(
        &self,
        request: InvokeRequest,
        options: CallOptions,
    ) -> ClientFuture<'_, InvokeResponse>;

    fn cancel(
        &self,
        request: CancelRequest,
        options: CallOptions,
    ) -> ClientFuture<'_, CancelResponse>;

    fn get_activation(
        &self,
        request: GetActivationRequest,
        options: CallOptions,
    ) -> ClientFuture<'_, ActivationStatus>;

    fn get_policy(
        &self,
        request: GetPolicyRequest,
        options: CallOptions,
    ) -> ClientFuture<'_, GetPolicyResponse>;

    fn list_policies(
        &self,
        request: ListPoliciesRequest,
        options: CallOptions,
    ) -> ClientFuture<'_, ListPoliciesResponse>;

    fn list_capabilities(
        &self,
        request: ListCapabilitiesRequest,
        options: CallOptions,
    ) -> ClientFuture<'_, ListCapabilitiesResponse>;

    fn apply_policy(
        &self,
        request: ApplyPolicyRequest,
        options: CallOptions,
    ) -> ClientFuture<'_, ApplyPolicyResponse>;

    fn get_policy_operation(
        &self,
        request: GetPolicyOperationRequest,
        options: CallOptions,
    ) -> ClientFuture<'_, GetPolicyOperationResponse>;
}

impl std::fmt::Display for ClientFailure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for ClientFailure {}

#[must_use]
pub fn parse_u64_decimal(value: &str) -> Option<u64> {
    let parsed = value.parse::<u64>().ok()?;
    (parsed.to_string() == value).then_some(parsed)
}
