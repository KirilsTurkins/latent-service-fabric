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
    pub local_target: Option<ResolvedRevision>,
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
    route_fence: Option<Arc<dyn CapabilityRouteFence>>,
    pub(super) dependencies: Vec<ReleaseUseEligibility>,
    _metadata: Charge,
    _slot: Charge,
}
impl CompiledCapabilityPlan {
    /// Validated plan identity, for a bounded trusted route source.
    #[must_use]
    pub fn matches_revision(&self, revision: &ResolvedRevision) -> bool {
        self.target.matches(revision)
    }
    /// Public currentness check grants no call admission by itself.
    pub fn check_eligible(&self) -> Result<(), PlatformError> {
        self.check_current()?;
        self.with_routes(&mut || Ok(()))
    }
    pub(super) fn with_routes(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if let Some(fence) = &self.route_fence {
            fence.with_current(action)
        } else {
            action()
        }
    }
    // Preliminary check only. Call admission rechecks these tokens together
    // inside the consumer's catalog fence without recursively acquiring it.
    pub(super) fn check_dependencies(&self) -> Result<(), PlatformError> {
        for dependency in &self.dependencies {
            dependency.check_for_catalog(&self.owner.catalog)?;
        }
        Ok(())
    }
    pub(super) fn check_current(&self) -> Result<(), PlatformError> {
        self.publication.check_for_catalog(&self.owner.catalog)?;
        self.check_dependencies()?;
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
/// Trusted control snapshot fence for exact isolated-local provider revisions.
/// Implementations hold a nonblocking current-route read guard across `action`.
/// Neither the guard nor action may perform I/O, wait, or invoke a provider.
pub trait CapabilityRouteFence: Send + Sync {
    fn with_current(
        &self,
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError>;
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
    /// Holds installation and policy ownership through a bounded control commit.
    /// This is never used by an activation or around provider I/O.
    pub fn with_current_plans(
        &self,
        plans: &[Arc<CompiledCapabilityPlan>],
        action: &mut dyn FnMut() -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if plans.len() > 256 {
            return Err(super::capacity());
        }
        let live = self.inner.live.try_read().map_err(|_| busy())?;
        if !*live {
            return Err(denied());
        }
        let mut guards = Vec::new();
        let mut policies = Vec::new();
        for plan in plans {
            if !Arc::ptr_eq(&self.inner, &plan.owner) {
                return Err(denied());
            }
            plan.check_current()?;
            for binding in &plan.bindings {
                let guard = binding.provider.live.try_read().map_err(|_| busy())?;
                if !*guard {
                    return Err(denied());
                }
                guards.push(guard);
                policies.push(&binding.policies);
            }
        }
        self.inner
            .policies
            .with_current_snapshots(&policies, action)
    }
    pub fn compile_plan(
        &self,
        revision: &ResolvedRevision,
        imports: &[CapabilityBindingSpec<'_>],
        publication: &ReleaseUseEligibility,
        deadline: Instant,
    ) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
        self.compile_routed_plan(revision, imports, publication, &[], &[], None, deadline)
    }
    /// Exact local dependency tokens and a route fence are supplied only by the
    /// configured control compiler. Existing host-only embedding remains valid.
    #[expect(
        clippy::too_many_arguments,
        reason = "closed route, publication and installation proofs accompany the bounded compile request"
    )]
    pub fn compile_routed_plan(
        &self,
        revision: &ResolvedRevision,
        imports: &[CapabilityBindingSpec<'_>],
        publication: &ReleaseUseEligibility,
        dependencies: &[ReleaseUseEligibility],
        local_targets: &[ResolvedRevision],
        route_fence: Option<Arc<dyn CapabilityRouteFence>>,
        deadline: Instant,
    ) -> Result<Arc<CompiledCapabilityPlan>, PlatformError> {
        let live = self.inner.live.try_read().map_err(|_| busy())?;
        if !*live {
            return Err(denied());
        }
        if imports.len() > 11
            || dependencies.len() > 11
            || local_targets.len() > imports.len()
            || (!dependencies.is_empty() && route_fence.is_none())
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
        for dependency in dependencies {
            dependency.check_for_catalog(&self.inner.catalog)?;
            dependency.authorize_tenant(&revision.target.tenant)?;
        }
        validate_local_targets(
            revision,
            imports,
            dependencies,
            local_targets,
            route_fence.is_some(),
        )?;
        if self.inner.clock.monotonic_now() >= deadline {
            return Err(super::error(
                latent_core::PlatformErrorCode::DeadlineExceeded,
                "capability-plan-deadline",
            ));
        }
        let slot = self.inner.counters.acquire(Kind::Plan, 1)?;
        let bytes = metadata_bytes(&self.inner, imports, dependencies, local_targets.len())?;
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
                local_target: local_targets
                    .iter()
                    .find(|t| t.target.contract.0 == provider.capability)
                    .cloned(),
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
            dependencies: dependencies.to_vec(),
            route_fence,
            _metadata: metadata,
            _slot: slot,
        }))
    }
}

fn validate_local_targets(
    revision: &ResolvedRevision,
    imports: &[CapabilityBindingSpec<'_>],
    dependencies: &[ReleaseUseEligibility],
    local_targets: &[ResolvedRevision],
    has_fence: bool,
) -> Result<(), PlatformError> {
    let mut local_contracts = std::collections::BTreeSet::new();
    for target in local_targets {
        if !has_fence
            || target.target.tenant != revision.target.tenant
            || target.route_generation != revision.route_generation
            || !token(&target.target.service.0)
            || !token(&target.revision.0)
            || !target.target.function.0.is_empty()
            || !target.attributes.is_empty()
            || target
                .target
                .route
                .as_ref()
                .is_some_and(|route| !token(route))
            || !local_contracts.insert(&target.target.contract)
            || !imports
                .iter()
                .any(|i| i.provider.capability() == target.target.contract.0)
            || !dependencies.iter().any(|d| {
                d.release() == &target.release
                    && target.publication.as_ref() == Some(d.publication())
            })
        {
            return Err(invalid());
        }
    }
    Ok(())
}

fn metadata_bytes(
    owner: &Arc<Inner>,
    imports: &[CapabilityBindingSpec<'_>],
    dependencies: &[ReleaseUseEligibility],
    local_target_count: usize,
) -> Result<usize, PlatformError> {
    let mut bytes = 4096usize;
    // At most eleven checked targets, with bounded identifiers and no
    // arbitrary attributes. Includes the compiler's matching route fence.
    bytes = bytes
        .checked_add(local_target_count * 8192)
        .ok_or_else(super::capacity)?;
    for dependency in dependencies {
        bytes = bytes
            .checked_add(dependency.retained_bytes())
            .ok_or_else(super::capacity)?;
    }
    for import in imports {
        if !Arc::ptr_eq(owner, &import.provider.entry.owner)
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
    Ok(bytes)
}
