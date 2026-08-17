//! Execution backend, preparation, cell, cancellation, and guest-outcome interfaces.

#![forbid(unsafe_code)]

use latent_activation::ActivationEnvelope;
use latent_artifacts::CapsuleArtifact;
use latent_core::{
    ActivationId, BoxFuture, BudgetConsumption, CapabilityId, CellId, Metadata, Payload,
    PlatformError, ReleaseDigest, ResourceBudget,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparationKey {
    pub release: ReleaseDigest,
    pub engine_version: String,
    pub engine_configuration_digest: String,
    pub target_triple: String,
    pub cpu_feature_set: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedComponent {
    pub key: PreparationKey,
    pub backend: String,
    pub opaque_handle: String,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BoundImport {
    pub capability: CapabilityId,
    pub contract: String,
    pub opaque_handle: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionCell {
    pub id: CellId,
    pub class: String,
    pub maximum_memory_bytes: u64,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionRequest {
    pub activation: ActivationEnvelope,
    pub prepared: PreparedComponent,
    pub cell: ExecutionCell,
    pub imports: Vec<BoundImport>,
    pub budget: ResourceBudget,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GuestTrap {
    pub code: String,
    pub message: String,
    pub guest_backtrace: Vec<String>,
    pub metadata: Metadata,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GuestOutcome {
    Returned {
        output: Payload,
        output_media_type: String,
        consumption: BudgetConsumption,
    },
    Trapped {
        trap: GuestTrap,
        consumption: BudgetConsumption,
    },
    Interrupted {
        reason: String,
        consumption: BudgetConsumption,
    },
}

pub trait ExecutionCancellation: Send + Sync {
    fn activation_id(&self) -> &ActivationId;
    fn is_cancelled(&self) -> bool;
    fn reason(&self) -> Option<String>;
}

pub trait ExecutionBackend: Send + Sync {
    fn backend_id(&self) -> &str;

    fn prepare<'a>(
        &'a self,
        artifact: &'a CapsuleArtifact,
        key: &'a PreparationKey,
    ) -> BoxFuture<'a, Result<PreparedComponent, PlatformError>>;

    fn invoke<'a>(
        &'a self,
        request: ExecutionRequest,
        cancellation: &'a dyn ExecutionCancellation,
    ) -> BoxFuture<'a, Result<GuestOutcome, PlatformError>>;

    fn release<'a>(
        &'a self,
        prepared: PreparedComponent,
    ) -> BoxFuture<'a, Result<(), PlatformError>>;
}

pub trait ExecutionBackendRegistry: Send + Sync {
    fn get(&self, backend_id: &str) -> Option<&dyn ExecutionBackend>;
    fn list(&self) -> Vec<String>;
}
