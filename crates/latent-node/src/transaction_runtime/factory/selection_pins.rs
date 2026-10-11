//! Actual installed source-owner port, distinct from request DTO selection.
use super::{authorization, TransactionAdmissionOwners, TransactionInstallation};
use latent_artifacts::ReleaseUseEligibility;
use latent_core::{
    native_capacity::NativeCapacityOwner, DeploymentId, PlatformError, RevisionId, RouteGeneration,
};
use latent_routing::{InvocationTarget, ResolvedRevision};
use latent_state::namespace::catalog::{NamespaceCatalog, NamespaceRead};
use std::sync::Arc;

/// Trusted node/control producer. The production implementation captures the
/// actual current deployment repository and namespace lifecycle owners, keeping
/// prepaid resident metadata beside them. Implementations hold their real short
/// nonblocking fences through `action`; these accessors confer no permission.
/// The caller separately holds its original enforced admission and its final
/// Native fence. Resident ownership is physical retention, not a caller grant;
/// this port must not nest another entry into the same Native owner.
pub trait TransactionInstallationSelection: Send + Sync {
    fn target(&self) -> &InvocationTarget;
    fn deployment(&self) -> &DeploymentId;
    fn deployment_revision(&self) -> &RevisionId;
    fn route_generation(&self) -> RouteGeneration;
    fn namespace(&self) -> &NamespaceRead;
    fn entity(&self) -> Option<&str>;
    fn uses_namespace(&self, namespace: &NamespaceCatalog) -> bool;
    fn uses_native_capacity(&self, native: &NativeCapacityOwner) -> bool;
    fn with_current(
        &self,
        publication: &ReleaseUseEligibility,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError>;

    /// A DTO must describe this exact actual retained source. Permission still
    /// comes from the original publication/catalog/namespace owner's fence.
    fn check_resolved(
        &self,
        resolved: &ResolvedRevision,
        publication: &ReleaseUseEligibility,
    ) -> Result<(), PlatformError> {
        if resolved.target != *self.target()
            || resolved.revision != *self.deployment_revision()
            || resolved.route_generation != self.route_generation()
            || resolved.release != *publication.release()
            || resolved.publication.as_ref() != Some(publication.publication())
        {
            return Err(authorization::denied());
        }
        self.with_current(publication, &mut || Ok(()))
    }

    /// Match namespace/entity selectors against the original opaque read. This
    /// comparison creates no grant; admission separately checks current owners.
    fn check_selectors(
        &self,
        namespace: &str,
        incarnation: u64,
        entity: Option<&str>,
        operation: &str,
    ) -> Result<(), PlatformError> {
        if namespace != self.namespace().record().id.0
            || incarnation != self.namespace().record().version.incarnation
            || entity != self.entity()
            || operation != self.target().function.0
        {
            return Err(authorization::denied());
        }
        Ok(())
    }
}

impl TransactionInstallation {
    /// Canonical installation binds an actual source capture to this SAME
    /// existing native factory. Equal owner limits, namespace row numbers and
    /// caller-provided ResolvedRevision values do not establish these pins.
    pub fn with_current_selection(
        mut self,
        selection: Arc<dyn TransactionInstallationSelection>,
        owners: &TransactionAdmissionOwners,
    ) -> Result<Self, PlatformError> {
        let record = selection.namespace().record();
        if self.selection.is_some()
            || !selection.uses_namespace(&owners.namespaces)
            || !selection.uses_native_capacity(&owners.native)
            || record.id.0 != self.declaration.namespace
            || record.state_schema != self.declaration.state_schema
            || Some(&record.tenant) != self.publication.tenant()
            || selection.deployment().0 != self.declaration.deployment
            || selection.target().tenant != record.tenant
            || selection.target().service.0 != self.metadata.manifest().metadata.name
            || !self
                .declaration
                .operations
                .iter()
                .any(|operation| operation.operation == selection.target().function.0)
        {
            return Err(authorization::denied());
        }
        selection.with_current(&self.publication, &mut || Ok(()))?;
        self.selection = Some(selection);
        Ok(self)
    }
}
