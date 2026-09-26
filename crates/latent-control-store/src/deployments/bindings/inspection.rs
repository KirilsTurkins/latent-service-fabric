use super::{denied, error};
use crate::deployments::DirectoryDeploymentRepository;
use latent_capabilities::broker::diagnostics::{CapabilityInspectionSource, InspectionPlan};
use latent_core::{DeploymentId, PlatformError, PlatformErrorCode, TenantId};

fn busy() -> PlatformError {
    error(PlatformErrorCode::Unavailable, "capability-inspection-busy")
}
impl CapabilityInspectionSource for DirectoryDeploymentRepository {
    fn inspect(
        &self,
        tenant: &TenantId,
        deployment: &DeploymentId,
    ) -> Result<InspectionPlan, PlatformError> {
        let current = self.current.try_read().map_err(|_| busy())?;
        if !current.confirmed {
            return Err(busy());
        }
        let record = current
            .routes
            .record_by_id(deployment)
            .filter(|record| record.deployment.metadata.tenant.as_ref() == Some(tenant))
            .ok_or_else(denied)?;
        // Admission lookup would hide stale plans and unavailable providers.
        let plan = current
            .routes
            .bindings
            .plans
            .iter()
            .find(|plan| plan.inspection_matches(tenant, deployment, &record.revision))
            .cloned();
        Ok(InspectionPlan {
            generation: current.routes.generation,
            catalog_transaction: current.transaction,
            deployment: deployment.clone(),
            revision: record.revision.clone(),
            component: record.deployment.release.clone(),
            publication: record.publication.clone(),
            plan,
        })
    }
}
