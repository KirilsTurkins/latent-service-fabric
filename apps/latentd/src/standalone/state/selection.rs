use crate::config::state::OperationSettings;
use latent_artifacts::package::{
    artifact_blob_digest, decode_config, package_digest, LayerRole, PackageLimits,
};
use latent_artifacts::{ArtifactRepository, DirectoryArtifactRepository, ReleaseUseEligibility};
use latent_core::{ContractId, FunctionId, PlatformError};
use latent_manifest::{TransactionBinding, TransactionOperationMode};
use latent_routing::InvocationTarget;
use std::sync::Arc;

pub const COMPANION_PATH: &str = "transaction-binding.json";
pub const COMPANION_MEDIA: &str = "application/vnd.latent.transaction-binding.v1+json";
const PACKAGE_BYTES: usize = 32 * 1024 * 1024;

/// Only the loader constructs this descriptor from the exact admitted package.
/// It is a selection constraint; every admission seals current caller/policy.
pub struct InstalledTransactionOperation {
    pub(super) target: InvocationTarget,
    pub(super) publication: ReleaseUseEligibility,
    pub(super) companion: TransactionBinding,
    pub(super) declared_digest: String,
    pub(super) incarnation: u64,
    pub(super) result_policy: String,
    pub(super) policies: Vec<String>,
    pub(super) entity: Option<String>,
    pub(super) mode: TransactionOperationMode,
    pub(super) contract_digest: String,
}
impl InstalledTransactionOperation {
    #[must_use]
    pub fn target(&self) -> &InvocationTarget {
        &self.target
    }
    #[must_use]
    pub fn publication(&self) -> &ReleaseUseEligibility {
        &self.publication
    }
    #[must_use]
    pub fn namespace(&self) -> &str {
        &self.companion.namespace
    }
    #[must_use]
    pub const fn incarnation(&self) -> u64 {
        self.incarnation
    }
    #[must_use]
    pub fn state_schema(&self) -> &str {
        &self.companion.state_schema
    }
    #[must_use]
    pub fn companion_digest(&self) -> &str {
        &self.declared_digest
    }
    #[must_use]
    pub fn binding(&self) -> &str {
        &self.companion.binding
    }
    #[must_use]
    pub fn result_policy(&self) -> &str {
        &self.result_policy
    }
    #[must_use]
    pub fn entity(&self) -> Option<&str> {
        self.entity.as_deref()
    }
    #[must_use]
    pub const fn mode(&self) -> TransactionOperationMode {
        self.mode
    }
}

pub(crate) async fn load_operations(
    artifacts: &Arc<DirectoryArtifactRepository>,
    settings: Vec<OperationSettings>,
) -> Result<Vec<Arc<InstalledTransactionOperation>>, PlatformError> {
    let mut installed = Vec::with_capacity(settings.len());
    for input in settings {
        installed.push(Arc::new(load(artifacts, input).await?));
    }
    Ok(installed)
}

pub(super) async fn load(
    artifacts: &Arc<DirectoryArtifactRepository>,
    input: OperationSettings,
) -> Result<InstalledTransactionOperation, PlatformError> {
    let publication = artifacts
        .execution_eligibility_selected(&input.component, Some(&input.publication))?
        .filter(|proof| proof.tenant() == Some(&input.tenant) && proof.admission().is_some())
        .ok_or_else(super::denied)?;
    publication.check_current()?;
    let source = artifacts
        .retained_package_source_selected(
            &input.tenant,
            &input.component,
            Some(&input.publication),
            PACKAGE_BYTES,
        )
        .await?
        .ok_or_else(super::denied)?;
    if source.publication() != publication.publication()
        || source.tenant() != &input.tenant
        || source.component() != publication.release()
        || Some(source.package()) != publication.package()
    {
        return Err(super::denied());
    }
    let (manifest, configuration, layers) = source.into_parts();
    if Some(&package_digest(&manifest)) != publication.package() {
        return Err(super::denied());
    }
    let config = decode_config(&configuration, PackageLimits::default())?;
    let companion = companion(&config, &layers, &input.companion_digest)?;
    let contract_digest = config
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::Contracts)
        .ok_or_else(super::denied)?
        .digest
        .to_string();
    let entry = artifacts
        .get_selected_catalog_entry(
            publication.scope(),
            &latent_artifacts::PublicationRef {
                id: input.publication.clone(),
                scope: publication.scope().clone(),
            },
        )
        .await?
        .ok_or_else(super::denied)?;
    companion
        .check_links(&entry.service.0, &input.deployment, &input.binding)
        .map_err(|_| super::denied())?;
    let operation = companion
        .operations
        .iter()
        .find(|operation| operation.operation == input.function)
        .filter(|operation| {
            operation.input_format == "lsf-wit-values-v1"
                && operation.result_format == "lsf-wit-values-v1"
        })
        .ok_or_else(super::denied)?;
    let mode = operation.mode;
    publication.check_current()?;
    Ok(InstalledTransactionOperation {
        target: InvocationTarget {
            tenant: input.tenant,
            service: entry.service,
            contract: ContractId(input.contract),
            function: FunctionId(input.function),
            route: input.route,
        },
        publication,
        companion,
        declared_digest: input.companion_digest,
        incarnation: input.incarnation,
        result_policy: input.result_policy,
        policies: input.policies,
        entity: input.entity,
        mode,
        contract_digest,
    })
}

fn companion(
    config: &latent_artifacts::package::PackageConfig,
    layers: &[(String, Vec<u8>)],
    digest: &str,
) -> Result<TransactionBinding, PlatformError> {
    let layer = config
        .layers
        .iter()
        .find(|layer| layer.path == COMPANION_PATH)
        .filter(|layer| {
            layer.role == LayerRole::Asset
                && layer.media_type == COMPANION_MEDIA
                && layer.digest.as_str() == digest
                && layer.size <= 128 * 1024
        })
        .ok_or_else(super::denied)?;
    let bytes = &layers
        .iter()
        .find(|(path, _)| path == COMPANION_PATH)
        .ok_or_else(super::denied)?
        .1;
    if bytes.len() as u64 != layer.size || artifact_blob_digest(bytes).as_str() != digest {
        return Err(super::denied());
    }
    TransactionBinding::decode(bytes).map_err(|_| super::denied())
}
