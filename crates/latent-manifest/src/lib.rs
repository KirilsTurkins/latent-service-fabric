//! Declarative capsule, deployment, binding, trigger, and policy documents.

#![forbid(unsafe_code)]

use latent_core::{
    BindingId, CapabilityId, ContractId, DeploymentId, Metadata, PolicyId, ReleaseDigest,
    ResourceBudget, ServiceId, TenantId, TriggerId,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObjectMetadata {
    pub name: String,
    pub tenant: Option<TenantId>,
    pub namespace: Option<String>,
    pub labels: Metadata,
    pub annotations: Metadata,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExecutionBackendKind {
    WasmComponent,
    EphemeralProcess,
    Container,
    MicroVm,
    RemoteProvider,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ThreadingModel {
    SingleThreaded,
    Reentrant,
    Cooperative,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StateModel {
    Stateless,
    TransactionalKeyed,
    Entity,
    DurableWorkflow,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContractExport {
    pub contract: ContractId,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContractImport {
    pub contract: ContractId,
    pub optional: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionRequirements {
    pub backend: ExecutionBackendKind,
    pub threading: ThreadingModel,
    pub state_model: StateModel,
    pub resource_budget_ceiling: ResourceBudget,
    pub host_call_depth_maximum: u32,
    pub component_call_depth_maximum: u32,
    pub snapshot_eligible: bool,
    pub fusion_eligible: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapsuleManifest {
    pub api_version: String,
    pub metadata: ObjectMetadata,
    pub semantic_version: String,
    pub component_digest: ReleaseDigest,
    pub world: ContractId,
    pub exports: Vec<ContractExport>,
    pub imports: Vec<ContractImport>,
    pub execution: ExecutionRequirements,
    pub minimum_fabric_version: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AvailabilityPolicy {
    pub minimum_cached_copies: u32,
    pub minimum_zones: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlacementPolicy {
    pub trust_class: String,
    pub architectures: Vec<String>,
    pub regions: Vec<String>,
    pub zones: Vec<String>,
    pub required_features: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityGrantSpec {
    pub capability: CapabilityId,
    pub policy: PolicyId,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeploymentManifest {
    pub api_version: String,
    pub id: DeploymentId,
    pub metadata: ObjectMetadata,
    pub service: ServiceId,
    pub release: ReleaseDigest,
    pub route_weight: u16,
    pub grants: Vec<CapabilityGrantSpec>,
    pub resources: ResourceBudget,
    pub availability: AvailabilityPolicy,
    pub placement: PlacementPolicy,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BindingMode {
    Host,
    Inline,
    IsolatedLocal,
    Remote,
    Auto,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BindingEndpoint {
    pub service: ServiceId,
    pub contract: ContractId,
    pub route: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BindingManifest {
    pub api_version: String,
    pub id: BindingId,
    pub metadata: ObjectMetadata,
    pub consumer: BindingEndpoint,
    pub provider: BindingEndpoint,
    pub mode: BindingMode,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TriggerKind {
    Http,
    Event,
    Timer,
    Queue,
    Blob,
    Direct,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TriggerTarget {
    pub service: ServiceId,
    pub contract: ContractId,
    pub function: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TriggerManifest {
    pub api_version: String,
    pub id: TriggerId,
    pub metadata: ObjectMetadata,
    pub kind: TriggerKind,
    pub target: TriggerTarget,
    pub configuration: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyManifest {
    pub api_version: String,
    pub id: PolicyId,
    pub metadata: ObjectMetadata,
    pub document: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManifestViolation {
    pub path: String,
    pub code: String,
    pub message: String,
}

pub trait ManifestCodec: Send + Sync {
    fn decode_capsule(&self, bytes: &[u8]) -> Result<CapsuleManifest, Vec<ManifestViolation>>;
    fn decode_deployment(&self, bytes: &[u8])
        -> Result<DeploymentManifest, Vec<ManifestViolation>>;
    fn decode_binding(&self, bytes: &[u8]) -> Result<BindingManifest, Vec<ManifestViolation>>;
    fn decode_trigger(&self, bytes: &[u8]) -> Result<TriggerManifest, Vec<ManifestViolation>>;
    fn decode_policy(&self, bytes: &[u8]) -> Result<PolicyManifest, Vec<ManifestViolation>>;
}

pub trait ManifestValidator: Send + Sync {
    fn validate_capsule(&self, manifest: &CapsuleManifest) -> Vec<ManifestViolation>;
    fn validate_deployment(&self, manifest: &DeploymentManifest) -> Vec<ManifestViolation>;
    fn validate_binding(&self, manifest: &BindingManifest) -> Vec<ManifestViolation>;
    fn validate_trigger(&self, manifest: &TriggerManifest) -> Vec<ManifestViolation>;
    fn validate_policy(&self, manifest: &PolicyManifest) -> Vec<ManifestViolation>;
}
