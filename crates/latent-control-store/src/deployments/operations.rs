//! Managed deployment mutations share the ordinary route publication and writer.
mod commit;
mod prepare;
mod reads;
pub(super) mod table;
use super::{CompiledCatalog, PublicationView};
use crate::{
    deployment_operations::{budget::Charge, DeploymentOperationReceipt, DeploymentReadLease},
    VersionedDeployment,
};
use std::sync::Arc;

pub struct PreparedDeploymentOperation {
    owner: Arc<std::sync::atomic::AtomicBool>,
    previous: PublicationView,
    next_routes: Arc<CompiledCatalog>,
    next_operations: Arc<table::OperationTable>,
    receipt: DeploymentOperationReceipt,
    apply_result: Option<VersionedDeployment>,
    bytes: Vec<u8>,
    replayed: bool,
    reply: DeploymentReadLease,
    _scratch: Charge,
    _work: super::rollouts::WorkReservation,
}
impl PreparedDeploymentOperation {
    #[must_use]
    pub fn preview(&self) -> &DeploymentOperationReceipt {
        &self.receipt
    }
    #[must_use]
    pub fn replayed(&self) -> bool {
        self.replayed
    }
    #[must_use]
    pub fn apply_result(&self) -> Option<&VersionedDeployment> {
        self.apply_result.as_ref()
    }
}
