use super::{
    busy, checked_text, denied, invalid, token, ActivationCapabilityBroker, Charge, Inner, Kind,
    PlatformError, ProviderReference,
};
use latent_artifacts::ReleaseUseEligibility;
use latent_core::{PublicationId, ReleaseDigest, RevisionId, RouteGeneration, ServiceId, TenantId};
use latent_policy::capability::{GrantRestriction, PolicySnapshot, MAX_DOCUMENT_BYTES};
use latent_routing::ResolvedRevision;
use std::{sync::Arc, time::Instant};

/// Privileged compiler input. This does not install a provider or grant access.
/// The runtime independently compares these imports with the prepared component.
pub struct CapabilityBindingSpec<'a> {
    pub provider: &'a ProviderReference,
    pub imported_operations: &'a [String],
    pub policy_ids: &'a [String],
    pub provider_binding_id: &'a str,
    pub deployment_restriction_json: &'a [u8],
}
pub(super) struct Binding {
    pub provider: Arc<super::provider::Provider>,
    pub operations: Vec<String>,
    pub policies: PolicySnapshot,
    pub deployment: GrantRestriction,
}
pub(super) struct Target {
    pub tenant: TenantId,
    pub service: ServiceId,
    revision: RevisionId,
    release: ReleaseDigest,
    pub publication: PublicationId,
    generation: RouteGeneration,
}
impl Target {
    pub(super) fn matches(&self, revision: &ResolvedRevision) -> bool {
        self.tenant == revision.target.tenant
            && self.service == revision.target.service
            && self.revision == revision.revision
            && self.release == revision.release
            && revision.publication.as_ref() == Some(&self.publication)
            && self.generation == revision.route_generation
    }
}
/// Immutable sealed plan. It contains no provider connection, guest instance,
/// public credential or mutable route. #207 supplies coherent route publication.
pub struct CompiledCapabilityPlan {
    pub(super) owner: Arc<Inner>,
    pub(super) target: Target,
    pub(super) publication: ReleaseUseEligibility,
    pub(super) bindings: Vec<Binding>,
    _metadata: Charge,
    _slot: Charge,
}
impl CompiledCapabilityPlan {
    pub(super) fn check_current(&self) -> Result<(), PlatformError> {
        self.publication.check_for_catalog(&self.owner.catalog)?;
        for binding in &self.bindings {
            if !*binding.provider.live.try_read().map_err(|_| busy())? {
                return Err(denied());
            }
            binding.policies.check_provider_configuration(
                &binding.provider.capability,
                &binding.provider.profile,
                &binding.provider.digest,
                binding.provider.epoch,
            )?;
        }
        Ok(())
    }
}
/// Trusted node-owned lookup. Implementations must be bounded and return plans
/// from the pinned control snapshot; no guest field or public DTO is authority.
pub trait CapabilityPlanSource: Send + Sync {
    fn plan(
        &self,
        revision: &ResolvedRevision,
    ) -> Result<Arc<CompiledCapabilityPlan>, PlatformError>;
}
impl ActivationCapabilityBroker {
    pub fn compile_plan(
        &self,
        revision: &ResolvedRevision,
        imports: &[CapabilityBindingSpec<'_>],
        publication: &ReleaseUseEligibility,
        deadline: Instant,
    ) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
        let live = self.inner.live.try_read().map_err(|_| busy())?;
        if !*live {
            return Err(denied());
        }
        if imports.len() > 11
            || revision.route_generation.0 == 0
            || !token(&revision.revision.0)
            || !token(&revision.target.tenant.0)
            || !token(&revision.target.service.0)
            || publication.tenant() != Some(&revision.target.tenant)
            || publication.release() != &revision.release
            || revision.publication.as_ref() != Some(publication.publication())
        {
            return Err(invalid());
        }
        publication.check_for_catalog(&self.inner.catalog)?;
        if self.inner.clock.monotonic_now() >= deadline {
            return Err(super::error(
                latent_core::PlatformErrorCode::DeadlineExceeded,
                "capability-plan-deadline",
            ));
        }
        let slot = self.inner.counters.acquire(Kind::Plan, 1)?;
        let mut bytes = 4096usize;
        for import in imports {
            if !Arc::ptr_eq(&self.inner, &import.provider.entry.owner)
                || import.imported_operations.is_empty()
                || import.imported_operations.len() > 16
                || import.imported_operations.iter().any(|op| !token(op))
                || import.deployment_restriction_json.len() > MAX_DOCUMENT_BYTES
            {
                return Err(invalid());
            }
            bytes = bytes
                .checked_add(4096 + import.deployment_restriction_json.len() * 16)
                .ok_or_else(super::capacity)?;
        }
        let metadata = self.inner.counters.acquire(Kind::Metadata, bytes)?;
        let mut bindings: Vec<Binding> = Vec::with_capacity(imports.len());
        for import in imports {
            let provider = &import.provider.entry;
            let installed = provider.live.try_read().map_err(|_| busy())?;
            if !*installed
                || bindings
                    .iter()
                    .any(|b| b.provider.capability == provider.capability)
            {
                return Err(denied());
            }
            let imported = GrantRestriction {
                operations: import.imported_operations.to_vec(),
                resources: None,
                ceiling: None,
            };
            imported.validate(&provider.capability)?;
            let deployment =
                GrantRestriction::parse(import.deployment_restriction_json, &provider.capability)?;
            let policies = self.inner.policies.snapshot(
                &revision.target.tenant,
                import.policy_ids,
                import.provider_binding_id,
                deadline,
            )?;
            policies.check_provider_configuration(
                &provider.capability,
                &provider.profile,
                &provider.digest,
                provider.epoch,
            )?;
            bindings.push(Binding {
                provider: Arc::clone(provider),
                operations: imported.operations,
                policies,
                deployment,
            });
        }
        publication.check_for_catalog(&self.inner.catalog)?;
        if self.inner.clock.monotonic_now() >= deadline {
            return Err(super::error(
                latent_core::PlatformErrorCode::DeadlineExceeded,
                "capability-plan-deadline",
            ));
        }
        Ok(Arc::new(CompiledCapabilityPlan {
            owner: Arc::clone(&self.inner),
            target: Target {
                tenant: TenantId(checked_text(&revision.target.tenant.0)?),
                service: ServiceId(checked_text(&revision.target.service.0)?),
                revision: RevisionId(checked_text(&revision.revision.0)?),
                release: revision.release.clone(),
                publication: publication.publication().clone(),
                generation: revision.route_generation,
            },
            publication: publication.clone(),
            bindings,
            _metadata: metadata,
            _slot: slot,
        }))
    }
}
