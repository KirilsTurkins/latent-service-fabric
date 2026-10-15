use super::*;
use latent_capabilities::namespace::{CallerScope, RecoverySelection, STATE_CONTRACT};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, MutationRequest,
    OwnedPolicyDecision, RecordKind, ResourceTarget,
};

pub(super) fn install(
    policy: &PolicyStore,
    principal: &InvocationPrincipal,
    publication: &str,
    profile: &str,
    digest: &str,
    short_policy: bool,
) {
    let document = grant(principal, publication, short_policy);
    let binding = json!({"formatVersion":1,"tenant":"tests","capability":STATE_CONTRACT,
        "providerProfile":profile,"configurationDigest":digest,"configurationEpoch":1,
        "restriction":{"operations":[]}});
    for (id, kind, document) in [
        ("native", RecordKind::Policy, document.clone()),
        ("native-secondary", RecordKind::Policy, document),
        ("binding", RecordKind::ProviderBinding, binding),
    ] {
        let bytes = serde_json::to_vec(&document).unwrap();
        policy
            .mutate(
                MutationRequest {
                    tenant: "tests",
                    actor: "operator",
                    id,
                    kind,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&bytes),
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
    }
}

fn grant(
    principal: &InvocationPrincipal,
    publication: &str,
    short_policy: bool,
) -> serde_json::Value {
    let caller = CallerScope::derive(principal, &RecoverySelection::OriginalCaller).unwrap();
    json!({"formatVersion":1,"tenant":"tests","rules":[{
        "id":"native","effect":"allow","principals":[{"kind":"administrator","subject":"operator"}],
        "services":["tests/packaging"],"publications":[publication],"capability":STATE_CONTRACT,
        "operations":["namespace-resume","namespace-inspect-restore","namespace-restore"],
        "resources":{"kind":"state","scopes":[{"namespace":"orders","incarnation":1,
            "entity":null,"recoveryKind":"original-caller","recoveryScope":caller.scope,"resultPolicy":"visibility-v1"}]},
        "ceiling":{"operations":1,"inputBytes":1_048_576,"outputBytes":1_048_576,"wallTimeMillis":if short_policy { 1000 } else { 30000 }}}]})
}

impl Fixture {
    pub fn captured(&self, id: &str, purpose: &str) -> OwnedPolicyDecision {
        let snapshot = self
            .policy
            .snapshot(
                &TenantId("tests".into()),
                &[id.into()],
                "binding",
                deadline(),
            )
            .unwrap();
        let unrestricted = GrantRestriction {
            operations: Vec::new(),
            resources: None,
            ceiling: None,
        };
        let caller =
            CallerScope::derive(&self.principal, &RecoverySelection::OriginalCaller).unwrap();
        let imported = vec![purpose.into()];
        let decision = snapshot
            .authorize(
                EvaluationInput {
                    principal: &self.principal,
                    service: "tests/packaging",
                    publication: self.sources[0].id.as_str(),
                    capability: STATE_CONTRACT,
                    operation: purpose,
                    resource: ResourceTarget::State {
                        namespace: "orders",
                        incarnation: 1,
                        entity: None,
                        recovery_kind: caller.kind,
                        recovery_scope: &caller.scope,
                        result_policy: "visibility-v1",
                    },
                },
                &CallRestrictions {
                    imported_operations: &imported,
                    deployment: &unrestricted,
                    provider_configuration: &unrestricted,
                    provider_profile: &self.profile,
                    configuration_digest: &self.digest,
                    configuration_epoch: 1,
                    remaining: CapabilityCeiling {
                        operations: 1,
                        input_bytes: 1_048_576,
                        output_bytes: 1_048_576,
                        wall_time_millis: 30000,
                    },
                    input_bytes: 0,
                    output_bytes: 0,
                },
                self.codecs.catalog.primary().operation.publication(),
            )
            .unwrap();
        self.policy.retain_decision(&decision).unwrap()
    }

    pub fn revoke_policy(&self, secondary: bool, binding: bool) {
        let id = if binding {
            "binding"
        } else if secondary {
            "native-secondary"
        } else {
            "native"
        };
        let kind = if binding {
            RecordKind::ProviderBinding
        } else {
            RecordKind::Policy
        };
        let expected_revision = {
            let current = self
                .policy
                .get("tests", kind, id, 16 * 1024, deadline())
                .unwrap();
            current.value().as_ref().unwrap().revision
        };
        self.policy
            .mutate(
                MutationRequest {
                    tenant: "tests",
                    actor: "operator",
                    id,
                    kind,
                    operation_id: "revoke",
                    expected_revision,
                    document: None,
                },
                deadline(),
                |_| Ok(()),
            )
            .unwrap();
    }

    pub fn revoke_publication(&self, secondary: bool) {
        use latent_artifacts::{
            ReleaseActor, ReleaseActorKind, ReleaseLifecycleAction, ReleaseLifecycleReason,
            ReleaseMutationContext, ReleaseOperationPrecondition,
        };
        let publication = &self.sources[usize::from(secondary)];
        self.artifacts
            .change_publication_lifecycle(
                ReleaseMutationContext {
                    scope: publication.scope.clone(),
                    actor: ReleaseActor {
                        subject: "operator".into(),
                        kind: ReleaseActorKind::Administrator,
                    },
                    operation: Some(ReleaseOperationPrecondition {
                        operation_id: "revoke-source".into(),
                        expected_generation: 1,
                    }),
                },
                publication,
                ReleaseLifecycleAction::Revoke,
                ReleaseLifecycleReason::OperatorRevocation,
                &mut |_| Ok(()),
            )
            .unwrap();
    }

    pub async fn foreign_tenant_dependency(&self) -> latent_artifacts::ReleaseUseEligibility {
        let admitted = self
            .artifacts
            .admit_package(
                &TenantId("other".into()),
                self.signed.neutral_inventory_upload(false),
                &mut |_| Ok(()),
            )
            .await
            .unwrap();
        self.artifacts
            .execution_eligibility_selected(
                &admitted.descriptor.release_digest,
                admitted.publication.as_ref(),
            )
            .unwrap()
            .unwrap()
    }
}
