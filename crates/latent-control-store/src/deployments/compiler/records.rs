use std::collections::BTreeMap;
use std::sync::Arc;

use latent_core::{DeploymentId, Metadata, RevisionId};
use latent_manifest::{DeploymentManifest, ExecutionRequirements};

use super::CompiledCatalog;

pub(in crate::deployments) type DesiredDeployments =
    BTreeMap<DeploymentId, Arc<DeploymentManifest>>;
pub(in crate::deployments) type ObjectVersions = BTreeMap<DeploymentId, u64>;

/// A position is meaningful only within the catalog that constructed it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(in crate::deployments) struct RecordIndex(pub(in crate::deployments) usize);

/// Immutable payloads have no generation, positional indexes or repository owner.
#[derive(Debug, PartialEq, Eq)]
pub(in crate::deployments) struct RevisionRecord {
    pub deployment: Arc<DeploymentManifest>,
    pub revision: RevisionId,
    pub publication: Option<latent_core::PublicationId>,
    pub attributes: Metadata,
    pub execution: ExecutionRequirements,
}

impl RevisionRecord {
    /// Preserve the stored scope; a local-unscoped source is not tenant admission.
    pub fn publication_reference(
        &self,
        artifacts: &dyn latent_artifacts::ArtifactRepository,
    ) -> Result<Option<latent_artifacts::PublicationRef>, latent_core::PlatformError> {
        let Some(id) = &self.publication else {
            return Ok(None);
        };
        let tenant = self
            .deployment
            .metadata
            .tenant
            .as_ref()
            .ok_or_else(crate::deployment_operations::corrupt)?;
        let selected = artifacts
            .select_execution_publication(tenant, &self.deployment.release, Some(id))?
            .ok_or_else(crate::deployment_operations::corrupt)?;
        if selected.id != *id || selected.scope.tenant().is_some_and(|scope| scope != tenant) {
            return Err(crate::deployment_operations::corrupt());
        }
        Ok(Some(selected))
    }
}

impl CompiledCatalog {
    pub(in crate::deployments) fn record(&self, index: RecordIndex) -> &RevisionRecord {
        &self.records[index.0]
    }

    pub(in crate::deployments) fn record_by_id(
        &self,
        id: &DeploymentId,
    ) -> Option<&Arc<RevisionRecord>> {
        self.records
            .binary_search_by(|record| record.deployment.id.cmp(id))
            .ok()
            .map(|index| &self.records[index])
    }
}
