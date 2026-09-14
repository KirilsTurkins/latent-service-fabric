use super::{capacity, denied, error, CompiledCatalog, PublishedCatalog};
use crate::deployments::{compiler::RevisionRecord, DirectoryDeploymentRepository};
use latent_capabilities::broker::{
    CapabilityPlanSource, CapabilityRouteFence, CompiledCapabilityPlan,
};
use latent_core::{DeploymentId, PlatformError, PlatformErrorCode, PublicationId, RevisionId};
use latent_routing::ResolvedRevision;
use std::sync::{Arc, Mutex, RwLock, Weak};

#[derive(Default)]
pub(in crate::deployments) struct Generations(Mutex<Vec<Weak<CompiledCatalog>>>);
impl Generations {
    pub(in crate::deployments) fn retain(
        &self,
        catalog: &Arc<CompiledCatalog>,
    ) -> Result<(), PlatformError> {
        let Some(owner) = &catalog.bindings.owner else {
            return Ok(());
        };
        let mut entries = self.0.try_lock().map_err(|_| busy())?;
        entries.retain(|entry| entry.strong_count() != 0);
        if entries
            .iter()
            .any(|entry| entry.ptr_eq(&Arc::downgrade(catalog)))
        {
            return Ok(());
        }
        if entries.len() >= owner.limits.maximum_retained_generations {
            return Err(capacity());
        }
        entries.push(Arc::downgrade(catalog));
        Ok(())
    }
}
impl CapabilityPlanSource for DirectoryDeploymentRepository {
    fn plan(
        &self,
        revision: &ResolvedRevision,
    ) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
        let current = self.current.try_read().map_err(|_| busy())?;
        if current.routes.generation == revision.route_generation {
            // Keep the publication read owner through lookup. Ordinary current
            // calls cannot become the last owner of a retired whole catalog.
            return lookup(&current.routes, revision);
        }
        drop(current);
        let entries = self.binding_generations.0.try_lock().map_err(|_| busy())?;
        let catalog = entries
            .iter()
            .filter_map(Weak::upgrade)
            .find(|c| c.generation == revision.route_generation)
            .ok_or_else(denied)?;
        lookup(&catalog, revision)
    }
}
fn lookup(
    catalog: &CompiledCatalog,
    revision: &ResolvedRevision,
) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
    let plan = catalog
        .bindings
        .plans
        .iter()
        .find(|plan| plan.matches_revision(revision))
        .ok_or_else(denied)?;
    plan.check_eligible()?;
    Ok(Arc::clone(plan))
}
pub(super) struct LocalTarget {
    deployment: DeploymentId,
    revision: RevisionId,
    publication: Option<PublicationId>,
}
impl LocalTarget {
    pub(super) fn new(record: &RevisionRecord) -> Self {
        Self {
            deployment: record.deployment.id.clone(),
            revision: record.revision.clone(),
            publication: record.publication.clone(),
        }
    }
}
pub(super) struct LocalFence {
    pub current: Weak<RwLock<PublishedCatalog>>,
    pub targets: Box<[LocalTarget]>,
}
impl CapabilityRouteFence for LocalFence {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        let owner = self.current.upgrade().ok_or_else(denied)?;
        let current = owner.try_read().map_err(|_| busy())?;
        if !current.confirmed {
            return Err(denied());
        }
        for target in &self.targets {
            let record = current
                .record_by_id(&target.deployment)
                .ok_or_else(denied)?;
            if record.revision != target.revision || record.publication != target.publication {
                return Err(denied());
            }
        }
        action()
    }
}
fn busy() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "binding-publication-busy")
}
