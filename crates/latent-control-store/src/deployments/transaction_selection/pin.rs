use super::{
    capacity, denied, unavailable, CapturedTransactionSelection, InstalledTransactionSelection,
};
use crate::deployments::{
    compiler::CompiledCatalog, publication::PublishedCatalog, DirectoryDeploymentRepository,
};
use latent_artifacts::ReleaseUseEligibility;
use latent_core::{
    native_capacity::NativeCapacityOwner, DeploymentId, PlatformError, RevisionId, RouteGeneration,
};
use latent_node::transaction_runtime::TransactionInstallationSelection;
use latent_routing::InvocationTarget;
use latent_state::namespace::{
    catalog::{NamespaceCatalog, NamespaceRead},
    lifecycle::NamespaceLifecycleHandle,
};
use std::sync::{Arc, RwLock, Weak};

pub(super) struct SelectionPin {
    current: Weak<RwLock<PublishedCatalog>>,
    catalog: Weak<CompiledCatalog>,
    transaction: u64,
    target: InvocationTarget,
    routing_key: Option<String>,
    pub(super) deployment: DeploymentId,
    revision: RevisionId,
    generation: RouteGeneration,
    pub(super) publication: ReleaseUseEligibility,
    namespace: NamespaceRead,
    lifecycle: NamespaceLifecycleHandle,
    entity: Option<String>,
    write: bool,
    config: super::super::DirectoryDeploymentRepositoryConfig,
}

// The remaining 16 KiB of the prepaid envelope covers this shell, the <=4096
// routing key, eight <=256-byte selector/revision strings, their allocation
// envelopes and the capture/transfer shells. Opaque read/publication capacities
// are measured separately before copies and must fit in the first 48 KiB.
const _: () =
    assert!(std::mem::size_of::<SelectionPin>() + 4096 + 8 * 256 + 11 * 128 + 512 <= 16 * 1024);

impl SelectionPin {
    #[allow(
        clippy::too_many_arguments,
        reason = "Original current owners and descriptive routing choices are independent"
    )]
    pub(super) fn capture(
        store: &DirectoryDeploymentRepository,
        target: &InvocationTarget,
        routing_key: Option<&str>,
        entity: Option<&str>,
        namespace: NamespaceRead,
        namespaces: &NamespaceCatalog,
        publication: &ReleaseUseEligibility,
        write: bool,
    ) -> Result<Self, PlatformError> {
        if [
            target.tenant.0.as_str(),
            target.service.0.as_str(),
            target.contract.0.as_str(),
            target.function.0.as_str(),
        ]
        .into_iter()
        .chain(target.route.as_deref())
        .chain(entity)
        .any(|text| text.is_empty() || text.len() > 256 || text.chars().any(char::is_control))
            || routing_key
                .is_some_and(|key| key.len() > store.config.max_routing_key_bytes.min(4096))
            || namespace
                .retained_bytes()
                .saturating_add(publication.retained_bytes())
                > 48 * 1024
        {
            return Err(capacity());
        }
        let current = store.current.try_read().map_err(|_| unavailable())?;
        if !current.confirmed {
            return Err(denied());
        }
        let record = current.select_record(target, routing_key, store.config)?;
        if record.deployment.metadata.tenant.as_ref() != Some(&target.tenant)
            || record.deployment.release != *publication.release()
            || record.publication.as_ref() != Some(publication.publication())
            || record.deployment.id.0.len() > 256
            || record.revision.0.len() > 256
            || store
                .lifecycle
                .as_ref()
                .is_none_or(|owner| !publication.belongs_to_catalog(owner))
        {
            return Err(denied());
        }
        let lifecycle = namespaces
            .lifecycle()
            .pin(&namespace)
            .map_err(|_| denied())?;
        Ok(Self {
            current: Arc::downgrade(&store.current),
            catalog: Arc::downgrade(&current.routes),
            transaction: current.transaction,
            target: target.clone(),
            routing_key: routing_key.map(str::to_owned),
            deployment: record.deployment.id.clone(),
            revision: record.revision.clone(),
            generation: current.generation,
            publication: publication.clone(),
            namespace,
            lifecycle,
            entity: entity.map(str::to_owned),
            write,
            config: store.config,
        })
    }

    pub(super) fn with_current(
        &self,
        publication: &ReleaseUseEligibility,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let owner = self.current.upgrade().ok_or_else(denied)?;
        let current = owner.try_read().map_err(|_| unavailable())?;
        if !current.confirmed
            || current.transaction != self.transaction
            || current.generation != self.generation
            || !self.catalog.ptr_eq(&Arc::downgrade(&current.routes))
            || publication.release() != self.publication.release()
            || publication.publication() != self.publication.publication()
            || publication.tenant() != self.publication.tenant()
        {
            return Err(denied());
        }
        let actual =
            current.select_record(&self.target, self.routing_key.as_deref(), self.config)?;
        if actual.deployment.id != self.deployment || actual.revision != self.revision {
            return Err(denied());
        }
        current.with_current_admission(&mut |checker| {
            let checker = checker.ok_or_else(denied)?;
            self.publication.check_with(checker)?;
            publication.check_with(checker)?;
            let mut result = None;
            self.lifecycle
                .with_current(&self.namespace, self.write, || {
                    result = Some(action());
                    Ok(())
                })
                .map_err(|_| denied())?;
            result.ok_or_else(denied)?
        })
    }
}

impl TransactionInstallationSelection for InstalledTransactionSelection {
    fn target(&self) -> &InvocationTarget {
        &self.pin.target
    }
    fn deployment(&self) -> &DeploymentId {
        &self.pin.deployment
    }
    fn deployment_revision(&self) -> &RevisionId {
        &self.pin.revision
    }
    fn route_generation(&self) -> RouteGeneration {
        self.pin.generation
    }
    fn namespace(&self) -> &NamespaceRead {
        &self.pin.namespace
    }
    fn entity(&self) -> Option<&str> {
        self.pin.entity.as_deref()
    }
    fn uses_namespace(&self, namespace: &NamespaceCatalog) -> bool {
        namespace.lifecycle().owns_handle(&self.pin.lifecycle)
    }
    fn uses_native_capacity(&self, native: &NativeCapacityOwner) -> bool {
        self.resident.is_from_owner(native)
    }
    fn with_current(
        &self,
        publication: &ReleaseUseEligibility,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        // Resident expiry grants no permission and refunds no physical metadata.
        // The canonical caller must retain its own original enforced admission
        // and enter that Native fence once, after the current source fences.
        self.pin.with_current(publication, action)
    }
}

#[cfg(test)]
mod tests;
