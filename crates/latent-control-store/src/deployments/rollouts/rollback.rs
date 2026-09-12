use super::super::{
    compiler::compile_catalog_with_runtime, next_generation, observation::Work, CompiledCatalog,
    DirectoryDeploymentRepository, PublicationView,
};
use super::{
    comparison, prepare,
    table::{self, StoredRollout},
};
use crate::rollouts::{codec, conflict, corrupt, error, Result, RolloutState};
use latent_core::{PlatformErrorCode, RouteGeneration};
use std::sync::Arc;

pub(super) fn validate_target(
    current: &PublicationView,
    row: &StoredRollout,
    generation: RouteGeneration,
) -> Result<()> {
    if !current.confirmed {
        return Err(error(
            PlatformErrorCode::Unavailable,
            "rollout-durability-uncertain",
        ));
    }
    let target = row.status.rollback_target.as_ref().ok_or_else(|| {
        error(
            PlatformErrorCode::Unavailable,
            "rollout-rollback-target-unavailable",
        )
    })?;
    if target.historical_route_generation != generation
        || !matches!(
            row.status.state,
            RolloutState::Running
                | RolloutState::Paused
                | RolloutState::Completed
                | RolloutState::Aborted
        )
    {
        return Err(conflict());
    }
    target.validate().map_err(|_| corrupt())?;
    if target.manifest_digest != codec::hash(row.base_manifest.as_bytes())
        || generation >= current.routes.generation
    {
        return Err(corrupt());
    }
    if !prepare::cohort_matches(&current.routes, row)? {
        return Err(error(
            PlatformErrorCode::StateConflict,
            "rollout-cohort-conflict",
        ));
    }
    Ok(())
}
impl DirectoryDeploymentRepository {
    pub(super) async fn prepare_rollback_routes(
        &self,
        previous: &PublicationView,
        row: &StoredRollout,
        timestamp: u64,
    ) -> Result<Arc<CompiledCatalog>> {
        comparison::rollback(
            self.artifacts.as_ref(),
            self.lifecycle.as_ref(),
            self.admission.as_ref(),
            &row.status.tenant,
            &row.status.candidate,
            &row.status.base,
        )
        .await?;
        let generation = next_generation(previous.routes.generation)?;
        let mut desired = previous.routes.deployments.clone();
        let mut versions = previous.routes.versions.clone();
        let base = table::decode_manifest(&row.base_manifest)?;
        desired.remove(&row.status.candidate.deployment_id);
        versions.remove(&row.status.candidate.deployment_id);
        versions.insert(base.id.clone(), generation.0);
        desired.insert(base.id.clone(), Arc::new(base));
        Ok(Arc::new(
            compile_catalog_with_runtime(
                desired,
                versions,
                generation,
                timestamp,
                self.artifacts.as_ref(),
                self.config,
                Some(&previous.routes),
                &mut Work::default(),
                self.runtime_profile.as_deref(),
                self.lifecycle.as_ref(),
            )
            .await?,
        ))
    }
}
