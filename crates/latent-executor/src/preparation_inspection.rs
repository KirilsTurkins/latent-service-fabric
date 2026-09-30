//! Safe observations from one owned, non-instantiated preparation. These fields
//! are descriptive and cannot substitute for admission or execution authority.
use crate::PreparationKey;
use latent_core::{diagnostic::DiagnosticProfile, ContractId, FunctionId, ReleaseDigest, ResourceBudget};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparationInspection {
    pub key: PreparationKey,
    pub component_digest: ReleaseDigest,
    pub profile: DiagnosticProfile,
    pub import_count: u64,
    pub function_count: u64,
    pub hostcall_fuel: u64,
    pub maximum_lifted_bytes: u64,
    pub maximum_type_nodes: u64,
    pub declared_budget: ResourceBudget,
    /// Same sealed source metadata fingerprint as the owned preparation. This
    /// is lsf-wasmtime-preparation-metadata-v2, not a signed document digest.
    pub sealed_metadata_fingerprint: Option<[u8; 32]>,
    pub imports: Vec<ContractId>,
    pub exports: Vec<(ContractId, FunctionId)>,
}
