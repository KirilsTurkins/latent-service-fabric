//! Original authenticated administrator and current, purpose-specific seals.
use super::super::clock;
use super::{assets::SchemaEvidence, request::Action};
use latent_capabilities::namespace::{CallerScope, RecoverySelection, STATE_CONTRACT};
use latent_core::{InvocationPrincipal, PlatformError, PrincipalKind};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, OwnedPolicyDecision,
    PolicyStore, ResourceTarget,
};
use latent_state::embedded::StoreError;
use std::{
    sync::Arc,
    time::{Duration, Instant},
};

pub(super) struct NativeProfile<'a> {
    pub profile: &'a str,
    pub digest: &'a str,
    pub epoch: u64,
}
pub(super) struct Authority {
    policy: Arc<PolicyStore>,
    decisions: Vec<OwnedPolicyDecision>,
    purposes: &'static [&'static str],
    pub actor: String,
    pub deadline: Instant,
    pub file_bytes: u64,
    pub clock: Arc<clock::ProtectedCommandClock>,
}
impl Authority {
    pub fn retain(
        policy: Arc<PolicyStore>,
        evidence: &SchemaEvidence,
        principal: &InvocationPrincipal,
        action: &Action,
        clock: Arc<clock::ProtectedCommandClock>,
        host: &NativeProfile<'_>,
    ) -> Result<Self, PlatformError> {
        let op = &evidence.operation;
        if principal.kind != PrincipalKind::Administrator
            || principal.tenant.as_ref() != Some(&op.target.tenant)
        {
            return Err(super::super::denied());
        }
        let caller = CallerScope::derive(principal, &RecoverySelection::OriginalCaller)?;
        let started = Instant::now();
        let mut deadline = started + latent_state::recovery::snapshot::SNAPSHOT_DURATION;
        let mut file_bytes = 64 * 1024 * 1024;
        let unrestricted = GrantRestriction {
            operations: vec![],
            resources: None,
            ceiling: None,
        };
        let operations = action
            .purposes()
            .iter()
            .map(|value| (*value).to_owned())
            .collect::<Vec<_>>();
        let mut decisions = Vec::new();
        for purpose in action.purposes() {
            let snapshot =
                policy.snapshot(&op.target.tenant, &op.policies, op.binding(), deadline)?;
            let decision = snapshot.authorize(
                EvaluationInput {
                    principal,
                    service: &op.target.service.0,
                    publication: op.publication.publication().as_str(),
                    capability: STATE_CONTRACT,
                    operation: purpose,
                    resource: ResourceTarget::State {
                        namespace: op.namespace(),
                        incarnation: op.incarnation,
                        entity: None,
                        recovery_kind: caller.kind,
                        recovery_scope: &caller.scope,
                        result_policy: &op.result_policy,
                    },
                },
                &CallRestrictions {
                    imported_operations: &operations,
                    deployment: &unrestricted,
                    provider_configuration: &unrestricted,
                    provider_profile: host.profile,
                    configuration_digest: host.digest,
                    configuration_epoch: host.epoch,
                    remaining: CapabilityCeiling {
                        operations: 1,
                        input_bytes: file_bytes,
                        output_bytes: file_bytes,
                        wall_time_millis: 60_000,
                    },
                    input_bytes: 0,
                    output_bytes: 0,
                },
                &op.publication,
            )?;
            let ceiling = decision.ceiling();
            file_bytes = file_bytes
                .min(ceiling.input_bytes)
                .min(ceiling.output_bytes);
            deadline = deadline.min(started + Duration::from_millis(ceiling.wall_time_millis));
            let captured = policy.retain_decision(&decision)?;
            // No audit acknowledgement can be manufactured from receipt data.
            if captured.requires_audit() || file_bytes == 0 {
                return Err(super::super::denied());
            }
            decisions.push(captured);
        }
        let authority = Self {
            policy,
            decisions,
            purposes: action.purposes(),
            actor: principal.subject.clone(),
            deadline,
            file_bytes,
            clock,
        };
        authority
            .check(action.purposes()[0])
            .map_err(|_| super::super::denied())?;
        Ok(authority)
    }
    pub fn check(&self, purpose: &str) -> Result<(), StoreError> {
        if !self.purposes.contains(&purpose) {
            return Err(StoreError::Unavailable);
        }
        let references = self.decisions.iter().collect::<Vec<_>>();
        self.policy
            .with_retained_decisions(&references, &mut |_| {
                if Instant::now() >= self.deadline
                    || !latent_effects::runtime::EffectTimeSource::observe(self.clock.as_ref())
                        .continuity_proven
                {
                    return Err(super::super::unavailable());
                }
                Ok(())
            })
            .map_err(|_| StoreError::Unavailable)
    }
}
