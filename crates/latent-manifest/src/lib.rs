//! Declarative manifest models, bounded JSON codecs, and Phase 1 validation.
//!
//! The JSON Schemas under `schemas/` are the wire-format authority. The
//! concrete [`JsonManifestCodec`] embeds and evaluates those schemas without
//! requiring file-system access. [`Phase1ManifestValidator`] adds the
//! cross-field admission rules that JSON Schema cannot express.

#![forbid(unsafe_code)]

mod bounded_codec;
#[path = "codec.rs"]
mod wire_codec;
mod json_number;
mod schema;
mod validation;

pub use bounded_codec::{JsonManifestCodec, ManifestLimits};
pub use validation::{Phase1ManifestValidator, MANIFEST_API_VERSION, PHASE1_FABRIC_VERSION};
pub use wire_codec::{ManifestDocument, ManifestKind};

use std::collections::BTreeMap;
use std::fmt;

use latent_core::{
    BindingId, CapabilityId, ContractId, DeploymentId, Metadata, PolicyId, ReleaseDigest,
    ResourceBudget, ServiceId, TenantId, TriggerId,
};
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Arbitrary JSON object retained by a trigger's schema-defined configuration
/// extension point.
pub type JsonObject = BTreeMap<String, Value>;

/// Common metadata attached to declarative resources.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObjectMetadata {
    pub name: String,
    pub tenant: Option<TenantId>,
    pub namespace: Option<String>,
    pub labels: Metadata,
    pub annotations: Metadata,
}

/// Execution backend requested by a capsule.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ExecutionBackendKind {
    #[serde(rename = "wasm-component")]
    WasmComponent,
    #[serde(rename = "ephemeral-process")]
    EphemeralProcess,
    #[serde(rename = "container")]
    Container,
    #[serde(rename = "microvm")]
    MicroVm,
    #[serde(rename = "remote-provider")]
    RemoteProvider,
}

/// Guest threading contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum ThreadingModel {
    SingleThreaded,
    Reentrant,
    Cooperative,
}

/// Persistence model requested by a capsule.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum StateModel {
    Stateless,
    TransactionalKeyed,
    Entity,
    DurableWorkflow,
}

/// One exported contract.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContractExport {
    pub contract: ContractId,
}

/// One imported contract and whether it is optional.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContractImport {
    pub contract: ContractId,
    pub optional: bool,
}

/// Capsule execution requirements.
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

/// Declarative capsule resource.
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

/// Deployment availability requirements.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AvailabilityPolicy {
    pub minimum_cached_copies: u32,
    pub minimum_zones: u32,
}

/// Deployment placement requirements.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlacementPolicy {
    pub trust_class: String,
    pub architectures: Vec<String>,
    pub regions: Vec<String>,
    pub zones: Vec<String>,
    pub required_features: Vec<String>,
}

/// One capability grant attached to a deployment.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityGrantSpec {
    pub capability: CapabilityId,
    pub policy: PolicyId,
    pub operations: Vec<String>,
    pub constraints: Metadata,
}

impl CapabilityGrantSpec {
    /// Builds a grant with no operation narrowing or additional constraints.
    #[must_use]
    pub fn new(capability: CapabilityId, policy: PolicyId) -> Self {
        Self {
            capability,
            policy,
            operations: Vec::new(),
            constraints: Metadata::new(),
        }
    }
}

/// Declarative deployment resource.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeploymentManifest {
    pub api_version: String,
    /// Domain identity derived from `metadata.name` by the JSON codec.
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

/// Binding implementation preference.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum BindingMode {
    Host,
    Inline,
    IsolatedLocal,
    Remote,
    Auto,
}

/// Consumer or provider endpoint in a binding.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BindingEndpoint {
    pub service: ServiceId,
    pub contract: ContractId,
    pub route: Option<String>,
}

/// Declarative binding resource.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BindingManifest {
    pub api_version: String,
    /// Domain identity derived from `metadata.name` by the JSON codec.
    pub id: BindingId,
    pub metadata: ObjectMetadata,
    pub consumer: BindingEndpoint,
    pub provider: BindingEndpoint,
    pub mode: BindingMode,
}

/// Supported trigger document variants.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TriggerKind {
    #[serde(rename = "HttpTrigger")]
    Http,
    #[serde(rename = "EventTrigger")]
    Event,
    #[serde(rename = "TimerTrigger")]
    Timer,
    #[serde(rename = "QueueTrigger")]
    Queue,
    #[serde(rename = "BlobTrigger")]
    Blob,
    #[serde(rename = "DirectInvocationTrigger")]
    Direct,
}

/// Invocation target carried by a trigger resource.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TriggerTarget {
    pub service: ServiceId,
    pub contract: ContractId,
    pub function: String,
    pub route: Option<String>,
}

/// Declarative trigger resource. Runtime trigger behavior remains outside this
/// crate; the configuration object is retained without semantic interpretation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TriggerManifest {
    pub api_version: String,
    /// Domain identity derived from `metadata.name` by the JSON codec.
    pub id: TriggerId,
    pub metadata: ObjectMetadata,
    pub kind: TriggerKind,
    pub target: TriggerTarget,
    pub configuration: JsonObject,
}

/// Declarative policy resource. Policy evaluation is intentionally outside the
/// manifest layer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyManifest {
    pub api_version: String,
    /// Domain identity derived from `metadata.name` by the JSON codec.
    pub id: PolicyId,
    pub metadata: ObjectMetadata,
    pub language: String,
    pub document: String,
}

/// Stable, path-addressed rejection returned by codecs and validators.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ManifestViolation {
    /// JSONPath-like location rooted at `$`.
    pub path: String,
    /// Stable lower-kebab-case machine code.
    pub code: String,
    /// Human-readable diagnostic. Callers must branch on `code`, not this text.
    pub message: String,
}

impl ManifestViolation {
    #[must_use]
    pub fn new(
        path: impl Into<String>,
        code: impl Into<String>,
        message: impl Into<String>,
    ) -> Self {
        Self {
            path: path.into(),
            code: code.into(),
            message: message.into(),
        }
    }
}

impl fmt::Display for ManifestViolation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{} [{}]: {}", self.path, self.code, self.message)
    }
}

/// Result returned by manifest parsing, encoding, and validation operations.
pub type ManifestResult<T> = Result<T, Vec<ManifestViolation>>;

/// Object-safe JSON codec seam used by catalog and API adapters.
pub trait ManifestCodec: Send + Sync {
    fn decode_capsule(&self, bytes: &[u8]) -> ManifestResult<CapsuleManifest>;
    fn encode_capsule(&self, manifest: &CapsuleManifest) -> ManifestResult<Vec<u8>>;

    fn decode_deployment(&self, bytes: &[u8]) -> ManifestResult<DeploymentManifest>;
    fn encode_deployment(&self, manifest: &DeploymentManifest) -> ManifestResult<Vec<u8>>;

    fn decode_binding(&self, bytes: &[u8]) -> ManifestResult<BindingManifest>;
    fn encode_binding(&self, manifest: &BindingManifest) -> ManifestResult<Vec<u8>>;

    fn decode_trigger(&self, bytes: &[u8]) -> ManifestResult<TriggerManifest>;
    fn encode_trigger(&self, manifest: &TriggerManifest) -> ManifestResult<Vec<u8>>;

    fn decode_policy(&self, bytes: &[u8]) -> ManifestResult<PolicyManifest>;
    fn encode_policy(&self, manifest: &PolicyManifest) -> ManifestResult<Vec<u8>>;
}

/// Object-safe semantic validation seam. Structural validation is performed by
/// [`ManifestCodec`]; these methods enforce Phase 1 cross-field rules and also
/// protect manually constructed domain values.
pub trait ManifestValidator: Send + Sync {
    fn validate_capsule(&self, manifest: &CapsuleManifest) -> ManifestResult<()>;
    fn validate_deployment(&self, manifest: &DeploymentManifest) -> ManifestResult<()>;
    fn validate_binding(&self, manifest: &BindingManifest) -> ManifestResult<()>;
    fn validate_trigger(&self, manifest: &TriggerManifest) -> ManifestResult<()>;
    fn validate_policy(&self, manifest: &PolicyManifest) -> ManifestResult<()>;

    fn validate_deployment_against_capsule(
        &self,
        deployment: &DeploymentManifest,
        capsule: &CapsuleManifest,
    ) -> ManifestResult<()>;
}

pub(crate) fn finish_violations(mut violations: Vec<ManifestViolation>) -> ManifestResult<()> {
    violations.sort();
    violations.dedup();
    if violations.is_empty() {
        Ok(())
    } else {
        Err(violations)
    }
}
