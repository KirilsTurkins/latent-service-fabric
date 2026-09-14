use super::super::{
    capacity, denied, identifier, invalid, operation, publication, unavailable, CapabilityCeiling,
    GrantRestriction, ResourceTarget,
};
use super::{
    mutation::check_deadline,
    ownership::{Owner, Stamp},
    Compiled, PolicyReadLease, PolicyStore, RecordKind,
};
use latent_artifacts::ReleaseUseEligibility;
use latent_core::{InvocationPrincipal, PlatformError, TenantId};
use std::{
    sync::{atomic::Ordering, Arc},
    time::Instant,
};

struct Pinned {
    stamp: Arc<Stamp>,
    revision: u64,
    document: Arc<Compiled>,
}
/// Immutable validated rows from one configured owner. Retaining this snapshot
/// does not keep an old revision eligible after update/revocation or shutdown.
pub struct PolicySnapshot {
    owner: Arc<Owner>,
    tenant: TenantId,
    policies: Vec<Pinned>,
    binding: Pinned,
    lease: PolicyReadLease,
}
/// Facts must come from the transport/activation's trusted context. Claims and
/// guest-supplied metadata are deliberately not consumed by the language.
pub struct EvaluationInput<'a> {
    pub principal: &'a InvocationPrincipal,
    pub service: &'a str,
    pub publication: &'a str,
    pub capability: &'a str,
    pub operation: &'a str,
    pub resource: ResourceTarget<'a>,
}
/// These restrictions are supplied by the trusted binding compiler/provider
/// owner (#207), never taken from a guest's claimed grant. A present import must
/// name an actual operation; unlike a deployment restriction, [] imports none.
pub struct CallRestrictions<'a> {
    pub imported_operations: &'a [String],
    pub deployment: &'a GrantRestriction,
    pub provider_configuration: &'a GrantRestriction,
    pub provider_profile: &'a str,
    pub configuration_digest: &'a str,
    pub configuration_epoch: u64,
    pub remaining: CapabilityCeiling,
    pub input_bytes: u64,
    pub output_bytes: u64,
}
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Explanation {
    Allow,
    Deny,
    Indeterminate,
}

/// Borrowed sealed decision. A descriptive Allow or a copied generation cannot
/// construct this type; its only final admission path rechecks both live owners.
pub struct SealedPolicyDecision<'a> {
    snapshot: &'a PolicySnapshot,
    publication: &'a ReleaseUseEligibility,
    input: EvaluationInput<'a>,
    ceiling: CapabilityCeiling,
}
impl PolicyStore {
    pub fn snapshot(
        &self,
        tenant: &TenantId,
        policies: &[String],
        binding: &str,
        deadline: Instant,
    ) -> Result<PolicySnapshot, PlatformError> {
        check_deadline(deadline)?;
        if !identifier(&tenant.0)
            || !identifier(binding)
            || policies.is_empty()
            || policies.len() > 8
            || !super::super::unique(policies, |id| identifier(id))
        {
            return Err(invalid());
        }
        let lease = self.owner.lease()?;
        let state = self.lock()?;
        let pin = |kind, id: &str| -> Result<Pinned, PlatformError> {
            let index = state
                .image
                .records
                .iter()
                .position(|row| row.matches(&tenant.0, kind, id))
                .ok_or_else(denied)?;
            let row = &state.loaded[index];
            Ok(Pinned {
                stamp: Arc::clone(&row.stamp),
                revision: state.image.records[index].revision,
                document: Arc::clone(row.document.as_ref().ok_or_else(denied)?),
            })
        };
        let policies = policies
            .iter()
            .map(|id| pin(RecordKind::Policy, id))
            .collect::<Result<Vec<_>, _>>()?;
        let binding = pin(RecordKind::ProviderBinding, binding)?;
        check_deadline(deadline)?;
        Ok(PolicySnapshot {
            owner: Arc::clone(&self.owner),
            tenant: tenant.clone(),
            policies,
            binding,
            lease,
        })
    }
    /// A short synchronous final-start boundary. Reserve actual invocation and
    /// provider capacity before entering; the closure must not wait or perform
    /// I/O. Accepted calls retain their real resource owners until cleanup.
    pub fn with_current(
        &self,
        decision: &SealedPolicyDecision<'_>,
        action: &mut dyn FnMut(
            &EvaluationInput<'_>,
            CapabilityCeiling,
        ) -> Result<(), PlatformError>,
    ) -> Result<(), PlatformError> {
        if !Arc::ptr_eq(&self.owner, &decision.snapshot.owner) {
            return Err(denied());
        }
        let _fence = self.owner.fence.try_read().map_err(|_| unavailable())?;
        decision.snapshot.check()?;
        decision.publication.check_for_catalog(&self.catalog)?;
        decision.publication.with_current(&mut |checker| {
            checker.check_eligibility(decision.publication)?;
            decision.snapshot.check()?;
            action(&decision.input, decision.ceiling)
        })
    }
}
impl PolicySnapshot {
    fn check(&self) -> Result<(), PlatformError> {
        self.owner.check()?;
        if self
            .policies
            .iter()
            .chain(std::iter::once(&self.binding))
            .any(|row| row.stamp.revision.load(Ordering::Acquire) != row.revision)
        {
            return Err(denied());
        }
        Ok(())
    }
    /// Checks a trusted installed provider against the pinned binding metadata.
    /// This is a compilation check only; it does not authorize an operation.
    pub fn check_provider_configuration(
        &self,
        capability: &str,
        profile: &str,
        digest: &str,
        epoch: u64,
    ) -> Result<(), PlatformError> {
        self.check()?;
        let Compiled::Binding(binding) = self.binding.document.as_ref() else {
            return Err(denied());
        };
        if binding.capability() != capability
            || binding.provider_profile() != profile
            || binding.configuration_digest() != digest
            || binding.configuration_epoch() != epoch
        {
            return Err(denied());
        }
        Ok(())
    }
    fn evaluate(&self, input: &EvaluationInput<'_>) -> Option<CapabilityCeiling> {
        if input.principal.tenant.as_ref() != Some(&self.tenant)
            || !identifier(&input.principal.subject)
            || !identifier(input.service)
            || !publication(input.publication)
            || !operation(input.capability, input.operation)
            || !input.resource.valid()
        {
            return None;
        }
        let mut ceiling: Option<CapabilityCeiling> = None;
        for pinned in &self.policies {
            let Compiled::Policy(policy) = pinned.document.as_ref() else {
                return None;
            };
            let allowed = policy.evaluate(
                input.principal,
                input.service,
                input.publication,
                input.capability,
                input.operation,
                &input.resource,
            )?;
            ceiling = Some(ceiling.map_or(allowed, |old| old.intersect(allowed)));
        }
        let Compiled::Binding(binding) = self.binding.document.as_ref() else {
            return None;
        };
        if binding.capability() != input.capability {
            return None;
        }
        binding
            .restriction()
            .narrow(input.operation, &input.resource, ceiling?)
    }
    /// A redacted read-only observation, explicitly not execution authority.
    #[must_use]
    pub fn explain(&self, input: &EvaluationInput<'_>) -> Explanation {
        let Ok(_fence) = self.owner.fence.try_read() else {
            return Explanation::Indeterminate;
        };
        if self.check().is_err() {
            return Explanation::Indeterminate;
        }
        if self.evaluate(input).is_some() {
            Explanation::Allow
        } else {
            Explanation::Deny
        }
    }
    #[must_use]
    pub fn into_explanation(self, input: &EvaluationInput<'_>) -> super::PolicyRead<Explanation> {
        let value = self.explain(input);
        super::PolicyRead {
            value,
            lease: self.lease,
        }
    }
    pub fn authorize<'a>(
        &'a self,
        input: EvaluationInput<'a>,
        restrictions: &CallRestrictions<'_>,
        publication: &'a ReleaseUseEligibility,
    ) -> Result<SealedPolicyDecision<'a>, PlatformError> {
        self.check()?;
        if publication.tenant() != Some(&self.tenant)
            || publication.publication().as_str() != input.publication
        {
            return Err(denied());
        }
        publication.check_current()?;
        restrictions.deployment.validate(input.capability)?;
        restrictions
            .provider_configuration
            .validate(input.capability)?;
        restrictions.remaining.validate()?;
        if !super::super::unique(restrictions.imported_operations, |value| {
            operation(input.capability, value)
        }) || !restrictions
            .imported_operations
            .iter()
            .any(|value| value == input.operation)
        {
            return Err(denied());
        }
        let Compiled::Binding(binding) = self.binding.document.as_ref() else {
            return Err(denied());
        };
        if binding.provider_profile() != restrictions.provider_profile
            || binding.configuration_digest() != restrictions.configuration_digest
            || binding.configuration_epoch() != restrictions.configuration_epoch
        {
            return Err(denied());
        }
        let mut ceiling = self.evaluate(&input).ok_or_else(denied)?;
        for extra in [restrictions.deployment, restrictions.provider_configuration] {
            ceiling = extra
                .narrow(input.operation, &input.resource, ceiling)
                .ok_or_else(denied)?;
        }
        ceiling = ceiling.intersect(restrictions.remaining);
        if ceiling.operations == 0
            || ceiling.wall_time_millis == 0
            || restrictions.input_bytes > ceiling.input_bytes
            || restrictions.output_bytes > ceiling.output_bytes
        {
            return Err(capacity());
        }
        Ok(SealedPolicyDecision {
            snapshot: self,
            publication,
            input,
            ceiling,
        })
    }
}
