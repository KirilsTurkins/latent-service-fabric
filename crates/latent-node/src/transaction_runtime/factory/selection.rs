use super::{Arc, PlatformError, PolicyCallBinding, RecoverySelection, ResultPolicy};
use latent_activation::ActivationEnvelope;
use latent_artifacts::{ReleaseUseEligibility, VerifiedArtifactMetadata};
use latent_commit::atomic::{RetryRequest, SourceIdentity};
use latent_core::transaction_contract::{CommandFingerprint, Precondition, Value};
use latent_manifest::{DeploymentManifest, TransactionBinding, TransactionOperationMode};

/// Installation requires verified executable metadata, the real selected
/// publication capability and the exact trusted deployment/companion links.
/// Policy bindings remain constraints checked by the existing policy owner.
pub struct TransactionInstallation {
    pub(super) metadata: VerifiedArtifactMetadata,
    pub(super) declaration: TransactionBinding,
    pub(super) publication: ReleaseUseEligibility,
    pub(super) state: Arc<PolicyCallBinding>,
    pub(super) intents: Option<Arc<PolicyCallBinding>>,
    pub(super) recovery: RecoverySelection,
    pub(super) result_read_policy: String,
    pub(super) result_policy: ResultPolicy,
}
impl TransactionInstallation {
    /// Descriptive selection from the trusted installed manifest and companion.
    /// Actual admission still resolves and seals this publication and policy.
    #[must_use]
    pub fn operation_for(
        &self,
        target: &latent_routing::InvocationTarget,
        namespace: &str,
        mode: TransactionOperationMode,
    ) -> Option<&latent_manifest::TransactionOperation> {
        if namespace != self.declaration.namespace
            || target.service.0 != self.metadata.manifest().metadata.name
            || Some(&target.tenant) != self.publication.tenant()
            || !self
                .metadata
                .manifest()
                .exports
                .iter()
                .any(|export| export.contract == target.contract)
        {
            return None;
        }
        self.declaration
            .operations
            .iter()
            .find(|operation| operation.operation == target.function.0 && operation.mode == mode)
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "Independent trusted installation owners are explicit"
    )]
    pub fn new(
        metadata: VerifiedArtifactMetadata,
        declaration: TransactionBinding,
        deployment: &DeploymentManifest,
        publication: ReleaseUseEligibility,
        state: Arc<PolicyCallBinding>,
        intents: Option<Arc<PolicyCallBinding>>,
        recovery: RecoverySelection,
        result_read_policy: String,
        result_policy: ResultPolicy,
    ) -> Result<Self, PlatformError> {
        declaration
            .check_links(
                &metadata.manifest().metadata.name,
                &deployment.id.0,
                &state.binding,
            )
            .map_err(|_| {
                super::error(
                    latent_core::PlatformErrorCode::IncompatibleContract,
                    "transaction-installation-links",
                )
            })?;
        latent_core::transaction_contract::identity(&result_read_policy)
            .map_err(|_| super::authorization::denied())?;
        result_policy.validate().map_err(super::atomic)?;
        if metadata.is_web_execution_projection()
            || metadata.verified_digest() != publication.release()
            || deployment.release != *publication.release()
            || deployment.publication.as_ref() != Some(publication.publication())
            || deployment.metadata.tenant.as_ref() != publication.tenant()
            || metadata.manifest().metadata.tenant.as_ref() != publication.tenant()
            || deployment.service.0 != metadata.manifest().metadata.name
        {
            return Err(super::authorization::denied());
        }
        Ok(Self {
            metadata,
            declaration,
            publication,
            state,
            intents,
            recovery,
            result_read_policy,
            result_policy,
        })
    }

    pub(super) fn source(
        &self,
        envelope: &ActivationEnvelope,
    ) -> Result<SourceIdentity, PlatformError> {
        let resolved = envelope
            .resolved_revision
            .as_ref()
            .ok_or_else(super::authorization::denied)?;
        if resolved.target != envelope.target {
            return Err(super::authorization::denied());
        }
        self.source_for_resolved(resolved)
    }

    /// Project the already resolved exact source without creating authority.
    /// A response must separately retain its actual original data-read owner.
    pub fn source_for_resolved(
        &self,
        resolved: &latent_routing::ResolvedRevision,
    ) -> Result<SourceIdentity, PlatformError> {
        let operation = self
            .declaration
            .operations
            .iter()
            .find(|operation| operation.operation == resolved.target.function.0)
            .ok_or_else(super::authorization::denied)?;
        let contract = self
            .metadata
            .contracts()
            .iter()
            .find(|contract| contract.id == resolved.target.contract)
            .ok_or_else(super::authorization::denied)?;
        if resolved.release != *self.publication.release()
            || resolved.publication.as_ref() != Some(self.publication.publication())
            || resolved.target.service.0 != self.metadata.manifest().metadata.name
            || Some(&resolved.target.tenant) != self.publication.tenant()
            || !self
                .metadata
                .manifest()
                .exports
                .iter()
                .any(|export| export.contract == resolved.target.contract)
        {
            return Err(super::authorization::denied());
        }
        let source = SourceIdentity {
            publication: self.publication.publication().as_str().to_owned(),
            revision: resolved.revision.0.clone(),
            release_digest: self.publication.release().0.clone(),
            component_digest: self.metadata.verified_digest().0.clone(),
            contract_digest: contract.digest.clone(),
            route_generation: resolved.route_generation.0,
            state_schema: self.declaration.state_schema.clone(),
            input_format: operation.input_format.clone(),
            result_format: operation.result_format.clone(),
        };
        source.validate().map_err(super::atomic)?;
        Ok(source)
    }
}

/// Descriptive request selectors, with no source/publication/policy grant.
pub struct TransactionSelection {
    pub namespace: String,
    pub incarnation: u64,
    pub entity: Option<String>,
    pub operation: String,
    pub mode: TransactionOperationMode,
    pub client_key: Option<String>,
    pub expected_versions: Vec<Precondition>,
    pub minimum_view_version: Option<Vec<u8>>,
    pub input_format: String,
    pub retry: Option<RetryRequest>,
}
impl TransactionSelection {
    pub(super) fn validate(
        &self,
        installation: &TransactionInstallation,
    ) -> Result<(), PlatformError> {
        let mode = self.mode == TransactionOperationMode::StrictCommand;
        let operation = installation
            .declaration
            .operations
            .iter()
            .find(|operation| operation.operation == self.operation)
            .ok_or_else(super::authorization::denied)?;
        if self.namespace != installation.declaration.namespace
            || self.incarnation == 0
            || operation.mode != self.mode
            || operation.input_format != self.input_format
            || mode != self.client_key.is_some()
            || (!mode && (!self.expected_versions.is_empty() || self.retry.is_some()))
            || (mode && self.minimum_view_version.is_some())
            || self.minimum_view_version.as_ref().is_some_and(|bytes| {
                bytes.len() != latent_state::session::version::VIEW_TOKEN_BYTES
            })
        {
            return Err(super::authorization::denied());
        }
        for identity in std::iter::once(&self.operation)
            .chain(self.client_key.as_ref())
            .chain(self.entity.as_ref())
        {
            latent_core::transaction_contract::identity(identity)
                .map_err(|_| super::authorization::denied())?;
        }
        // Apply the canonical precondition count/key/version checks before any
        // native submission, including duplicate and explicit-absence rules.
        CommandFingerprint {
            input_format: self.input_format.clone(),
            input: Value {
                bytes: Vec::new(),
                media_type: "application/octet-stream".into(),
                metadata: Vec::new(),
            },
            expected_versions: self.expected_versions.clone(),
        }
        .visit_identity_bytes(|_| {})
        .map_err(|_| super::authorization::denied())
    }
}
