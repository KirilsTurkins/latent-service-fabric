use latent_activation::ActivationEnvelope;
use latent_artifacts::ReleaseUseEligibility;
use latent_capabilities::namespace::RecoverySelection;
use latent_core::{transaction_contract::identity, PlatformError, StateNamespaceId};
use latent_manifest::{TransactionBinding, TransactionOperationMode};
use latent_routing::InvocationTarget;

use super::super::authorization::denied;

/// One approved operation from the exact deployed companion declaration.
/// Construction requires the real selected catalog publication owner. Its
/// currentness is subsequently fenced by the existing policy intersection.
pub struct QuerySelection {
    pub(super) target: InvocationTarget,
    pub(super) publication: ReleaseUseEligibility,
    pub(super) namespace: StateNamespaceId,
    pub(super) incarnation: u64,
    pub(super) schema: String,
    pub(super) entity: Option<String>,
    pub(super) recovery: RecoverySelection,
    pub(super) result_policy: String,
    pub(super) binding: String,
    pub(super) input_media_type: String,
    pub(super) minimum_generation: Option<u64>,
}

pub struct QueryScope {
    pub incarnation: u64,
    pub entity: Option<String>,
    pub recovery: RecoverySelection,
    pub result_policy: String,
    pub minimum_generation: Option<u64>,
}

impl QuerySelection {
    /// `capsule` and `deployment` come from the pinned deployed manifest, and
    /// `companion` from its bounded verified metadata. Request headers cannot
    /// select a namespace, schema, result policy or recovery mode.
    pub fn installed(
        target: InvocationTarget,
        publication: ReleaseUseEligibility,
        companion: &TransactionBinding,
        capsule: &str,
        deployment: &str,
        scope: QueryScope,
    ) -> Result<Self, PlatformError> {
        companion
            .check_links(capsule, deployment, &companion.binding)
            .map_err(|_| denied())?;
        identity(&scope.result_policy).map_err(|_| denied())?;
        if let Some(entity) = &scope.entity {
            identity(entity).map_err(|_| denied())?;
        }
        if scope.incarnation == 0 || publication.tenant() != Some(&target.tenant) {
            return Err(denied());
        }
        let operation = companion
            .operations
            .iter()
            .find(|operation| operation.operation == target.function.0)
            .filter(|operation| operation.mode == TransactionOperationMode::FreshQuery)
            .ok_or_else(denied)?;
        // The format identity is independent of the transport media type. This
        // initial shared profile supports the existing bounded typed codec.
        if operation.input_format != "lsf-wit-values-v1"
            || operation.result_format != "lsf-wit-values-v1"
        {
            return Err(denied());
        }
        Ok(Self {
            target,
            publication,
            namespace: StateNamespaceId(companion.namespace.clone()),
            incarnation: scope.incarnation,
            schema: companion.state_schema.clone(),
            entity: scope.entity,
            recovery: scope.recovery,
            result_policy: scope.result_policy,
            binding: companion.binding.clone(),
            input_media_type: "application/vnd.latent.wit-values.v1+json".into(),
            minimum_generation: scope.minimum_generation,
        })
    }

    pub(super) fn accepts(&self, envelope: &ActivationEnvelope) -> Result<(), PlatformError> {
        let revision = envelope.resolved_revision.as_ref().ok_or_else(denied)?;
        if envelope.target != self.target
            || revision.target != self.target
            || revision.release != *self.publication.release()
            || revision.publication.as_ref() != Some(self.publication.publication())
            || envelope.principal.tenant.as_ref() != Some(&self.target.tenant)
            || envelope.parent_activation_id.is_some()
            || envelope.retry_attempt != 0
            || envelope.input_media_type != self.input_media_type
        {
            return Err(denied());
        }
        Ok(())
    }
}
