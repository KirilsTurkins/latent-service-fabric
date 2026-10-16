use latent_artifacts::ReleaseUseEligibility;
use latent_capabilities::broker::http::HttpError;
use latent_capabilities::broker::{http::HTTP_CAPABILITY, ProviderReference};
use latent_core::{native_capacity::NativeBufferPermit, InvocationPrincipal, PlatformError};
use latent_effects::authority::{DispatchGrant, EffectRule, EffectScope};
use latent_http::deferred::DeferredHttpAuthorization;
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, PolicyStore,
    ResourceTarget,
};
use std::{
    collections::BTreeMap,
    sync::{Arc, Mutex},
};

pub(in crate::standalone::state) struct DispatchRegistry(
    Mutex<BTreeMap<EffectScope, Arc<DispatchPolicy>>>,
);
impl DispatchRegistry {
    pub(in crate::standalone::state) fn new() -> Self {
        Self(Mutex::new(BTreeMap::new()))
    }
    pub(super) fn register(&self, policy: DispatchPolicy) -> Result<bool, PlatformError> {
        let mut rows = self.0.lock().map_err(|_| super::denied())?;
        if let Some(previous) = rows.get(&policy.rule.scope) {
            return if previous.rule == policy.rule
                && previous.policies == policy.policies
                && previous.binding == policy.binding
                && previous.caller_scope == policy.caller_scope
                && previous.restriction.canonical_bytes(HTTP_CAPABILITY)?
                    == policy.restriction.canonical_bytes(HTTP_CAPABILITY)?
            {
                Ok(false)
            } else {
                Err(super::denied())
            };
        }
        if rows.len() >= 128 {
            return Err(super::denied());
        }
        rows.insert(policy.rule.scope.clone(), Arc::new(policy));
        Ok(true)
    }
}
impl DeferredHttpAuthorization for DispatchRegistry {
    fn check_current(
        &self,
        grant: &DispatchGrant,
        method: &str,
        path: &str,
    ) -> Result<(), HttpError> {
        let policy = self
            .0
            .lock()
            .map_err(|_| HttpError::PermissionDenied)?
            .get(grant.scope())
            .cloned()
            .ok_or(HttpError::PermissionDenied)?;
        if grant.profile() != &policy.rule.profile {
            return Err(HttpError::PermissionDenied);
        }
        policy
            .authorize(
                method,
                path,
                if method == "POST" {
                    grant.payload_bytes()
                } else {
                    0
                },
                grant.deadline(),
            )
            .map_err(HttpError::from)
    }
}

pub(super) struct DispatchPolicy {
    pub rule: EffectRule,
    pub policy: Arc<PolicyStore>,
    pub publication: ReleaseUseEligibility,
    pub principal: InvocationPrincipal,
    pub caller_scope: latent_capabilities::namespace::CallerScope,
    pub service: String,
    pub policies: Vec<String>,
    pub binding: String,
    pub restriction: GrantRestriction,
    pub reference: ProviderReference,
    pub origin: latent_policy::capability::HttpOrigin,
    // LAST: current snapshots, strings and original source stay prepaid while
    // any accepted adapter/fence retains this installed policy record.
    pub _metadata: Arc<NativeBufferPermit>,
}
impl DispatchPolicy {
    pub(super) fn authorize(
        &self,
        method: &str,
        path: &str,
        input_bytes: u64,
        deadline: std::time::Instant,
    ) -> Result<(), PlatformError> {
        let ceiling = self.rule.ceiling;
        let snapshot = self.policy.snapshot(
            self.publication.tenant().ok_or_else(super::denied)?,
            &self.policies,
            &self.binding,
            deadline,
        )?;
        let imported = vec!["send".into()];
        let decision = snapshot.authorize(
            EvaluationInput {
                principal: &self.principal,
                service: &self.service,
                publication: self.publication.publication().as_str(),
                capability: HTTP_CAPABILITY,
                operation: "send",
                resource: ResourceTarget::Http {
                    origin: &self.origin,
                    method,
                    path,
                },
            },
            &CallRestrictions {
                imported_operations: &imported,
                deployment: &self.restriction,
                provider_configuration: &GrantRestriction {
                    operations: Vec::new(),
                    resources: None,
                    ceiling: None,
                },
                provider_profile: self.reference.profile(),
                configuration_digest: self.reference.configuration_digest(),
                configuration_epoch: self.reference.configuration_epoch(),
                remaining: CapabilityCeiling {
                    operations: 1,
                    input_bytes: ceiling.maximum_payload_bytes,
                    output_bytes: ceiling.maximum_response_bytes,
                    wall_time_millis: ceiling.attempt_timeout_millis,
                },
                input_bytes,
                output_bytes: ceiling.maximum_response_bytes,
            },
            &self.publication,
        )?;
        if decision.requires_audit()
            || decision.ceiling().wall_time_millis < ceiling.attempt_timeout_millis
        {
            return Err(super::denied());
        }
        self.policy.with_current(&decision, &mut |_, _| Ok(()))
    }
}
