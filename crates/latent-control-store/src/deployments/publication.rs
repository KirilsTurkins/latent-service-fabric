use super::{operations::table::OperationTable, rollouts::table::RolloutTable, CompiledCatalog};
use std::sync::Arc;
pub(super) struct PublishedCatalog {
    pub transaction: u64,
    pub routes: Arc<CompiledCatalog>,
    pub rollouts: Arc<RolloutTable>,
    pub operations: Arc<OperationTable>,
    pub confirmed: bool,
}
impl std::ops::Deref for PublishedCatalog {
    type Target = CompiledCatalog;
    fn deref(&self) -> &CompiledCatalog {
        &self.routes
    }
}
pub(super) struct PublicationView {
    pub transaction: u64,
    pub routes: Arc<CompiledCatalog>,
    pub rollouts: Arc<RolloutTable>,
    pub operations: Arc<OperationTable>,
    pub confirmed: bool,
}
impl PublishedCatalog {
    pub fn capture(&self) -> PublicationView {
        PublicationView {
            transaction: self.transaction,
            routes: Arc::clone(&self.routes),
            rollouts: Arc::clone(&self.rollouts),
            operations: Arc::clone(&self.operations),
            confirmed: self.confirmed,
        }
    }
}
impl PublicationView {
    pub fn has_control(&self) -> bool {
        self.rollouts.enabled || self.operations.enabled
    }
}
