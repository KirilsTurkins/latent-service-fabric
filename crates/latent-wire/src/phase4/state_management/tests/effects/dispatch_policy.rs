//! Explicit controlled fixture dispatch authority on the real policy owner.
use super::*;
use latent_artifacts::ReleaseUseEligibility;
use latent_capabilities::namespace::{CallerScope, RecoverySelection, INTENT_CONTRACT};
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind, TenantId};
use latent_effects::authority::{AuthorityError, DurableEffectAuthority, EffectScope};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, MutationRequest,
    PolicyStore, RecordKind, ResourceTarget,
};

pub(super) struct DispatchPolicy {
    policy: Arc<PolicyStore>,
    publication: ReleaseUseEligibility,
    principal: InvocationPrincipal,
    caller: CallerScope,
    scope: EffectScope,
    profile: String,
    configuration_digest: String,
    result_policy: String,
    pub policy_revision: u64,
}
impl DispatchPolicy {
    pub fn install(fixture: &Fixture, rule: &latent_effects::authority::EffectRule) -> Self {
        let binding = &fixture.backend.0.bindings[0];
        let service = binding.service.clone();
        let tenant = TenantId(rule.scope.tenant.clone());
        let principal = InvocationPrincipal {
            subject: InvocationPrincipal::local_service_subject(&tenant, &service),
            kind: PrincipalKind::Service,
            tenant: Some(tenant),
            service: Some(service),
            claims: Metadata::new(),
        };
        let caller =
            CallerScope::derive(&principal, &RecoverySelection::ServiceIntegration).unwrap();
        let scope = serde_json::json!({"kind":"state","scopes":[{"namespace":rule.scope.namespace,
            "incarnation":rule.scope.incarnation,"entity":null,"recoveryKind":"service-integration",
            "recoveryScope":caller.scope,"resultPolicy":binding.result_policy}]});
        let configuration_digest = format!("sha256:{}", "7".repeat(64));
        let document = serde_json::json!({"formatVersion":1,"tenant":rule.scope.tenant,"rules":[{
            "id":"controlled-dispatch","effect":"allow","principals":[{"kind":"service","subject":principal.subject}],
            "services":[binding.service.0],"publications":[rule.scope.publication],"capability":INTENT_CONTRACT,
            "operations":["dispatch"],"resources":scope,"ceiling":{"operations":1,"inputBytes":1024,
            "outputBytes":1024,"wallTimeMillis":30000}}]});
        let provider = serde_json::json!({"formatVersion":1,"tenant":rule.scope.tenant,"capability":INTENT_CONTRACT,
            "providerProfile":rule.profile.adapter,"configurationDigest":configuration_digest,"configurationEpoch":1,
            "restriction":{"operations":["dispatch"],"resources":scope}});
        let mut policy_revision = None;
        for (kind, id, value) in [
            (RecordKind::Policy, "controlled-dispatch", document),
            (
                RecordKind::ProviderBinding,
                "controlled-dispatch-binding",
                provider,
            ),
        ] {
            let receipt = fixture
                .policy
                .mutate(
                    MutationRequest {
                        tenant: &rule.scope.tenant,
                        actor: "fixture-operator",
                        kind,
                        id,
                        operation_id: id,
                        expected_revision: 0,
                        document: Some(&serde_json::to_vec(&value).unwrap()),
                    },
                    deadline(),
                    |_| Ok(()),
                )
                .unwrap();
            if kind == RecordKind::Policy {
                policy_revision = Some(receipt.value().revision);
            }
        }
        let publication = fixture
            .backend
            .0
            .services
            .artifacts
            .execution_eligibility_selected(&binding.component, Some(&binding.publication.id))
            .unwrap()
            .unwrap();
        Self {
            policy: Arc::clone(&fixture.policy),
            publication,
            principal,
            caller,
            scope: rule.scope.clone(),
            profile: rule.profile.adapter.clone(),
            configuration_digest,
            result_policy: binding.result_policy.clone(),
            policy_revision: policy_revision.unwrap(),
        }
    }
    pub fn with_current(
        &self,
        authority: &DurableEffectAuthority,
        deadline: Instant,
        accept: &mut dyn FnMut() -> Result<
            latent_core::BoxFuture<'static, latent_effects::runtime::AdapterOutcome>,
            AuthorityError,
        >,
    ) -> Result<
        latent_core::BoxFuture<'static, latent_effects::runtime::AdapterOutcome>,
        AuthorityError,
    > {
        if authority.scope() != &self.scope
            || authority.profile().adapter != self.profile
            || authority.payload_bytes() > 1024
            || deadline <= Instant::now()
        {
            return Err(AuthorityError::PolicyBlocked);
        }
        let snapshot = self
            .policy
            .snapshot(
                &TenantId(self.scope.tenant.clone()),
                &["controlled-dispatch".into()],
                "controlled-dispatch-binding",
                deadline,
            )
            .map_err(|_| AuthorityError::PolicyBlocked)?;
        let restriction =
            GrantRestriction::parse(br#"{"operations":[]}"#, INTENT_CONTRACT).unwrap();
        let decision = snapshot
            .authorize(
                EvaluationInput {
                    principal: &self.principal,
                    service: self.principal.service.as_ref().unwrap().0.as_str(),
                    publication: &self.scope.publication,
                    capability: INTENT_CONTRACT,
                    operation: "dispatch",
                    resource: ResourceTarget::State {
                        namespace: &self.scope.namespace,
                        incarnation: self.scope.incarnation,
                        entity: None,
                        recovery_kind: self.caller.kind,
                        recovery_scope: &self.caller.scope,
                        result_policy: &self.result_policy,
                    },
                },
                &CallRestrictions {
                    imported_operations: &["dispatch".into()],
                    deployment: &restriction,
                    provider_configuration: &restriction,
                    provider_profile: &self.profile,
                    configuration_digest: &self.configuration_digest,
                    configuration_epoch: 1,
                    remaining: CapabilityCeiling {
                        operations: 1,
                        input_bytes: 1024,
                        output_bytes: 1024,
                        wall_time_millis: 30000,
                    },
                    input_bytes: authority.payload_bytes(),
                    output_bytes: 1024,
                },
                &self.publication,
            )
            .map_err(|_| AuthorityError::PolicyBlocked)?;
        let retained = self
            .policy
            .retain_decision(&decision)
            .map_err(|_| AuthorityError::PolicyBlocked)?;
        let mut accepted = None;
        let mut once = Some(accept);
        self.policy
            .with_retained_decision(&retained, &mut |_, _| {
                if Instant::now() >= deadline || once.is_none() {
                    return Err(latent_core::PlatformError {
                        code: latent_core::PlatformErrorCode::PermissionDenied,
                        message: "controlled dispatch authority expired".into(),
                        retryable: false,
                        details: vec![],
                    });
                }
                accepted = Some(once.take().unwrap()());
                Ok(())
            })
            .map_err(|_| AuthorityError::PolicyBlocked)?;
        accepted.ok_or(AuthorityError::PolicyBlocked)?
    }
}
