//! Bounded descriptive reads. None of these values admits a provider call.
mod usage;
pub use usage::{NodeUsage, TenantUsage};

use super::{busy, denied, plan::Binding, CompiledCapabilityPlan, PlatformError};
use latent_core::{
    DeploymentId, InvocationPrincipal, PublicationId, ReleaseDigest, RevisionId, RouteGeneration,
    TenantId,
};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, PolicySnapshotState, ResourceTarget,
};
use std::sync::Arc;

/// Trusted catalog adapter. The caller holds a bounded management read lease.
pub trait CapabilityInspectionSource: Send + Sync {
    fn inspect(
        &self,
        tenant: &TenantId,
        deployment: &DeploymentId,
    ) -> Result<InspectionPlan, PlatformError>;
}

/// Missing/rejected plans remain visible without reconstructing authority.
pub struct InspectionPlan {
    pub generation: RouteGeneration,
    pub catalog_transaction: u64,
    pub deployment: DeploymentId,
    pub revision: RevisionId,
    pub component: ReleaseDigest,
    pub publication: Option<PublicationId>,
    pub plan: Option<Arc<CompiledCapabilityPlan>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BindingState {
    Current,
    PolicyChanged,
    ProviderUnavailable,
    PublicationUnavailable,
    RouteChanged,
    Indeterminate,
}
impl BindingState {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::Current => "configured-current",
            Self::PolicyChanged => "policy-changed-or-revoked",
            Self::ProviderUnavailable => "provider-unavailable",
            Self::PublicationUnavailable => "publication-unavailable",
            Self::RouteChanged => "route-changed-or-unavailable",
            Self::Indeterminate => "inspection-indeterminate",
        }
    }
}
#[derive(Debug, Clone)]
pub struct Revision {
    pub id: String,
    pub revision: u64,
    pub digest: String,
}
impl From<latent_policy::capability::CapabilityPolicyRevision<'_>> for Revision {
    fn from(value: latent_policy::capability::CapabilityPolicyRevision<'_>) -> Self {
        Self {
            id: value.id.into(),
            revision: value.revision,
            digest: value.digest.into(),
        }
    }
}
#[derive(Debug, Clone)]
pub struct BindingInspection {
    pub capability: String,
    pub operations: Vec<String>,
    pub definition_digest: Option<String>,
    pub binding: Revision,
    pub policies: Vec<Revision>,
    pub provider_profile: String,
    pub configuration_digest: String,
    pub configuration_epoch: u64,
    pub state: BindingState,
}
#[derive(Debug)]
pub struct GrantExplanation {
    pub binding: Option<BindingInspection>,
    pub allowed: bool,
    pub reason: &'static str,
    pub requires_audit: bool,
    pub ceiling: Option<CapabilityCeiling>,
}

impl CompiledCapabilityPlan {
    #[must_use]
    pub fn inspection_matches(
        &self,
        tenant: &TenantId,
        deployment: &DeploymentId,
        revision: &RevisionId,
    ) -> bool {
        self.target.tenant == *tenant
            && self.target.deployment.as_ref() == Some(deployment)
            && self.target.revision == *revision
    }
    /// Currentness is sampled; it is rechecked independently at actual dispatch.
    pub fn inspect_bindings(
        &self,
        tenant: &TenantId,
    ) -> Result<Vec<BindingInspection>, PlatformError> {
        if self.target.tenant != *tenant {
            return Err(denied());
        }
        Ok(self
            .bindings
            .iter()
            .map(|binding| self.describe_binding(binding))
            .collect())
    }
    fn binding_state(&self, binding: &Binding) -> BindingState {
        let Ok(live) = self.owner.live.try_read() else {
            return BindingState::Indeterminate;
        };
        if !*live {
            return BindingState::Indeterminate;
        }
        let Ok(live) = binding.provider.live.try_read() else {
            return BindingState::Indeterminate;
        };
        if !*live {
            return BindingState::ProviderUnavailable;
        }
        match binding.policies.diagnostic_state() {
            PolicySnapshotState::Changed => return BindingState::PolicyChanged,
            PolicySnapshotState::Unavailable => return BindingState::Indeterminate,
            PolicySnapshotState::Current => {}
        }
        if let Err(error) = self.publication.check_for_catalog(&self.owner.catalog) {
            return if error.code == latent_core::PlatformErrorCode::Unavailable {
                BindingState::Indeterminate
            } else {
                BindingState::PublicationUnavailable
            };
        }
        if self.check_dependencies().is_err() || self.with_routes(&mut || Ok(())).is_err() {
            return BindingState::RouteChanged;
        }
        BindingState::Current
    }
    fn describe_binding(&self, binding: &Binding) -> BindingInspection {
        BindingInspection {
            capability: binding.provider.capability.clone(),
            operations: binding.operations.clone(),
            definition_digest: binding.definition_digest.as_ref().map(ToString::to_string),
            binding: binding.policies.binding_revision().into(),
            policies: binding
                .policies
                .policy_revisions()
                .map(Revision::from)
                .collect(),
            provider_profile: binding.provider.profile.clone(),
            configuration_digest: binding.provider.digest.clone(),
            configuration_epoch: binding.provider.epoch,
            state: self.binding_state(binding),
        }
    }
    /// Hypothetical evaluation using compiled restrictions. It neither reserves
    /// a live budget nor consumes a sealed decision's start fence.
    pub fn explain_grant(
        &self,
        principal: &InvocationPrincipal,
        capability: &str,
        operation: &str,
        resource: ResourceTarget<'_>,
    ) -> Result<GrantExplanation, PlatformError> {
        if principal.tenant.as_ref() != Some(&self.target.tenant) {
            return Err(denied());
        }
        let Some(binding) = self
            .bindings
            .iter()
            .find(|b| b.provider.capability == capability)
        else {
            return Ok(GrantExplanation {
                binding: None,
                allowed: false,
                reason: "capability-not-imported",
                requires_audit: false,
                ceiling: None,
            });
        };
        let description = self.describe_binding(binding);
        let mut result = GrantExplanation {
            reason: description.state.code(),
            binding: Some(description),
            allowed: false,
            requires_audit: false,
            ceiling: None,
        };
        if result
            .binding
            .as_ref()
            .is_none_or(|b| b.state != BindingState::Current)
        {
            return Ok(result);
        }
        let decision = binding.policies.authorize(
            EvaluationInput {
                principal,
                service: &self.target.service.0,
                publication: self.target.publication.as_str(),
                capability,
                operation,
                resource,
            },
            &CallRestrictions {
                imported_operations: &binding.operations,
                deployment: &binding.deployment,
                provider_configuration: &binding.provider.restriction,
                provider_profile: &binding.provider.profile,
                configuration_digest: &binding.provider.digest,
                configuration_epoch: binding.provider.epoch,
                remaining: CapabilityCeiling {
                    operations: 1_000_000,
                    input_bytes: 64 * 1024 * 1024,
                    output_bytes: 64 * 1024 * 1024,
                    wall_time_millis: 300_000,
                },
                input_bytes: 0,
                output_bytes: 0,
            },
            &self.publication,
        );
        match decision {
            Ok(decision) => {
                result.allowed = true;
                result.reason = "policy-allows-subject-to-live-admission";
                result.requires_audit = decision.requires_audit();
                result.ceiling = Some(decision.ceiling());
            }
            Err(error) => {
                result.reason = if error.code == latent_core::PlatformErrorCode::PermissionDenied {
                    "policy-denied"
                } else {
                    "inspection-indeterminate"
                }
            }
        }
        Ok(result)
    }
}
impl InspectionPlan {
    pub fn check_owner(
        &self,
        broker: &super::ActivationCapabilityBroker,
    ) -> Result<(), PlatformError> {
        if self
            .plan
            .as_ref()
            .is_some_and(|plan| !Arc::ptr_eq(&plan.owner, &broker.inner))
        {
            return Err(denied());
        }
        Ok(())
    }
}
