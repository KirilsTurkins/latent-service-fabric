use crate::{
    deployment_operations::{
        DeploymentOperationLimits, DeploymentOperationLookup, DeploymentOperationRead,
        DeploymentOperationSnapshot, Result,
    },
    deployments::{
        observation::Source, DirectoryDeploymentRepository, DirectoryDeploymentRepositoryConfig,
    },
    VersionedDeployment,
};
use latent_artifacts::{ArtifactRepository, LifecycleAuthorityHandle};
use latent_core::{DeploymentId, TenantId};
use std::{path::PathBuf, sync::Arc};
impl DirectoryDeploymentRepository {
    /// Bookkeeping only: reserves bounded request and audit scratch before caller allocations.
    pub fn reserve_operation_request(
        &self,
    ) -> Result<crate::deployment_operations::DeploymentReadLease> {
        self.operation_budget.read(0)
    }
    #[must_use]
    pub fn operation_limits(&self) -> DeploymentOperationLimits {
        self.operation_budget.limits
    }
    pub async fn open_with_operation_limits(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        limits: DeploymentOperationLimits,
    ) -> Result<Self> {
        Self::open_inner_with_control_limits(
            root,
            artifacts,
            config,
            Source::default(),
            None,
            None,
            None,
            crate::rollouts::RolloutLimits::default(),
            limits,
        )
        .await
    }
    #[expect(
        clippy::too_many_arguments,
        reason = "lowerable control limits compose with the exact catalog/runtime owners"
    )]
    pub async fn open_with_catalog_and_control_limits(
        root: impl Into<PathBuf>,
        artifacts: Arc<dyn ArtifactRepository>,
        config: DirectoryDeploymentRepositoryConfig,
        lifecycle: LifecycleAuthorityHandle,
        profile: Arc<latent_manifest::RuntimeCompatibilityProfile>,
        rollouts: crate::rollouts::RolloutLimits,
        operations: DeploymentOperationLimits,
    ) -> Result<Self> {
        let admission = lifecycle.required_authority().cloned();
        Self::open_inner_with_control_limits(
            root,
            artifacts,
            config,
            Source::default(),
            admission,
            Some(profile),
            Some(lifecycle),
            rollouts,
            operations,
        )
        .await
    }
    pub async fn get_operation(
        &self,
        tenant: &TenantId,
        operation_id: &str,
    ) -> Result<DeploymentOperationRead<DeploymentOperationLookup>> {
        crate::deployment_operations::validation::token(&tenant.0, 1024)?;
        crate::deployment_operations::validation::token(operation_id, 128)?;
        if tenant.0.len() > self.config.max_identifier_bytes {
            return Err(crate::deployment_operations::invalid());
        }
        let current = self.read_publication();
        let found = current.operations.find(tenant, operation_id);
        let bytes = if found.is_some() {
            2 * crate::deployment_operations::MAX_RECEIPT_BYTES + 1024
        } else {
            512
        };
        let lease = self.operation_budget.read(bytes)?;
        let value = if let Some(found) = found {
            if current.confirmed {
                DeploymentOperationLookup::Found(found.clone())
            } else {
                DeploymentOperationLookup::Uncertain
            }
        } else {
            DeploymentOperationLookup::Unknown {
                retained_floor: current.operations.floor(),
                high_watermark: current.operations.data.operation_sequence,
            }
        };
        Ok(DeploymentOperationRead::new(value, lease))
    }
    pub async fn get_operation_snapshot(
        &self,
        tenant: &TenantId,
        id: &DeploymentId,
    ) -> Result<DeploymentOperationRead<DeploymentOperationSnapshot>> {
        self.validate_target(tenant, id)?;
        let current = self.read_publication();
        let record = current
            .routes
            .record_by_id(id)
            .filter(|r| r.deployment.metadata.tenant.as_ref() == Some(tenant));
        let bytes = if let Some(record) = record {
            record
                .attributes
                .get("lsf.deployment")
                .ok_or_else(crate::deployment_operations::corrupt)?
                .len()
                .saturating_mul(2)
                .saturating_add(4096)
        } else {
            512
        };
        let lease = self.operation_budget.read(bytes)?;
        let deployment = record.map(|r| VersionedDeployment {
            manifest: r.deployment.as_ref().clone(),
            generation: current.routes.versions[id],
        });
        Ok(DeploymentOperationRead::new(
            DeploymentOperationSnapshot {
                deployment,
                state_version: current.transaction,
                route_generation: current.routes.generation,
                confirmed: current.confirmed,
            },
            lease,
        ))
    }
}
