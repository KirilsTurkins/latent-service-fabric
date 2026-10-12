//! The signed metadata charge follows the real selected installation handle.
use latent_artifacts::ReleaseUseEligibility;
use latent_control_store::InstalledTransactionSelection;
use latent_core::{
    native_capacity::{NativeBufferPermit, NativeCapacityOwner},
    DeploymentId, PlatformError, RevisionId, RouteGeneration,
};
use latent_node::transaction_runtime::TransactionInstallationSelection;
use latent_routing::InvocationTarget;
use latent_state::namespace::catalog::{NamespaceCatalog, NamespaceRead};
use std::sync::Arc;

pub(super) struct ChargedSelection {
    selected: InstalledTransactionSelection,
    metadata: Arc<NativeBufferPermit>,
}
impl ChargedSelection {
    pub(super) fn new(
        selected: InstalledTransactionSelection,
        metadata: Arc<NativeBufferPermit>,
    ) -> Self {
        Self { selected, metadata }
    }
}
impl TransactionInstallationSelection for ChargedSelection {
    fn target(&self) -> &InvocationTarget {
        self.selected.target()
    }
    fn deployment(&self) -> &DeploymentId {
        self.selected.deployment()
    }
    fn deployment_revision(&self) -> &RevisionId {
        self.selected.deployment_revision()
    }
    fn route_generation(&self) -> RouteGeneration {
        self.selected.route_generation()
    }
    fn namespace(&self) -> &NamespaceRead {
        self.selected.namespace()
    }
    fn entity(&self) -> Option<&str> {
        self.selected.entity()
    }
    fn uses_namespace(&self, namespace: &NamespaceCatalog) -> bool {
        self.selected.uses_namespace(namespace)
    }
    fn uses_native_capacity(&self, native: &NativeCapacityOwner) -> bool {
        self.selected.uses_native_capacity(native) && self.metadata.is_from_owner(native)
    }
    fn with_current(
        &self,
        publication: &ReleaseUseEligibility,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        self.selected.with_current(publication, action)
    }
}
