use super::*;
use latent_capabilities::namespace::{
    CallerScope, RecoverySelection, INTENT_CONTRACT, STATE_CONTRACT,
};
use latent_effects::authority::*;
use latent_node::transaction_runtime::PolicyCallBinding;
use latent_policy::capability::{GrantRestriction, MutationRequest, PolicyStore, RecordKind};
use serde_json::json;

const OPERATIONS: [&str; 16] = [
    "acquire-command",
    "acquire-query",
    "info",
    "query-info",
    "get",
    "get-query",
    "scan",
    "scan-query",
    "put",
    "delete",
    "inspect-effect",
    "describe-page",
    "page-next",
    "commit",
    "read-result",
    "cancel-command",
];
pub(super) fn install(
    policy: &PolicyStore,
    publication: &latent_artifacts::ReleaseUseEligibility,
    effects: &EffectAuthorityOwner,
    recovery: &RecoverySelection,
    subjects: &[&str],
) -> (Arc<PolicyCallBinding>, Arc<PolicyCallBinding>) {
    let mut bindings = Vec::new();
    for (id, capability, operations) in [
        ("state", STATE_CONTRACT, OPERATIONS.as_slice()),
        ("intents", INTENT_CONTRACT, &["stage"][..]),
    ] {
        let binding = if id == "state" {
            "transaction-rust-aggregate"
        } else {
            "intents-binding"
        };
        let digest = format!("sha256:{}", "2".repeat(64));
        let rules:Vec<_> = subjects.iter().map(|subject| {
            let caller = CallerScope::derive(&principal(subject),recovery).unwrap();
            json!({
                "id":subject,"effect":"allow","principals":[{"kind":"user","subject":subject}],"services":[publication::SERVICE],"publications":[publication.publication().as_str()],"capability":capability,"operations":operations,
                "resources":{"kind":"state","scopes":[{"namespace":publication::NAMESPACE,"incarnation":1,"entity":null,"recoveryKind":caller.kind,"recoveryScope":caller.scope,"resultPolicy":"visibility-v1"}]},"ceiling":{"operations":256,"inputBytes":2_097_152,"outputBytes":2_097_152,"wallTimeMillis":10_000}
            })
        }).collect();
        let document = json!({"formatVersion":1,"tenant":publication::TENANT,"rules":rules});
        let provider = json!({"formatVersion":1,"tenant":publication::TENANT,"capability":capability,"providerProfile":"namespace-v1","configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}});
        for (kind, selected, value) in [
            (RecordKind::Policy, id, document),
            (RecordKind::ProviderBinding, binding, provider),
        ] {
            policy
                .mutate(
                    MutationRequest {
                        tenant: publication::TENANT,
                        actor: "compiled-guest-test-operator",
                        kind,
                        id: selected,
                        operation_id: selected,
                        expected_revision: 0,
                        document: Some(&serde_json::to_vec(&value).unwrap()),
                    },
                    Instant::now() + Duration::from_secs(10),
                    |_| Ok(()),
                )
                .unwrap();
        }
        bindings.push(Arc::new(PolicyCallBinding {
            policies: vec![id.into()],
            binding: binding.into(),
            profile: "namespace-v1".into(),
            configuration_digest: digest,
            configuration_epoch: 1,
            operations: operations.iter().map(|v| (*v).into()).collect(),
            deployment: GrantRestriction::parse(br#"{"operations":[]}"#, capability).unwrap(),
            provider_configuration: GrantRestriction::parse(br#"{"operations":[]}"#, capability)
                .unwrap(),
        }));
    }
    effects
        .publish(EffectRule {
            scope: EffectScope {
                tenant: publication::TENANT.into(),
                namespace: publication::NAMESPACE.into(),
                incarnation: 1,
                publication: publication.publication().as_str().into(),
                binding: "approved-event".into(),
                operation: "event".into(),
            },
            profile: DispatchProfile {
                provider: "event-provider".into(),
                destination: "approved-events".into(),
                adapter: "test-event-v1".into(),
                intent_format: 1,
                payload_format: "lsf-aggregate-v1".into(),
                idempotency_profile: "stable-effect-v1".into(),
            },
            policy_revision: 1,
            credential_epoch: 1,
            protected_credential_reference: "event-credential-reference".into(),
            ceiling: DispatchCeiling {
                maximum_payload_bytes: 4096,
                maximum_response_bytes: 4096,
                maximum_attempts: 3,
                maximum_age_millis: 60_000,
                attempt_timeout_millis: 1000,
            },
            enabled: true,
        })
        .unwrap();
    (bindings.remove(0), bindings.remove(0))
}

pub(super) fn revoke(policy: &PolicyStore) {
    let deadline = Instant::now() + Duration::from_secs(10);
    let current = policy
        .get(
            publication::TENANT,
            RecordKind::Policy,
            "state",
            64 * 1024,
            deadline,
        )
        .unwrap();
    let expected = current.value().as_ref().unwrap().revision;
    drop(current);
    policy
        .mutate(
            MutationRequest {
                tenant: publication::TENANT,
                actor: "compiled-guest-test-operator",
                kind: RecordKind::Policy,
                id: "state",
                operation_id: "revoke",
                expected_revision: expected,
                document: None,
            },
            deadline,
            |_| Ok(()),
        )
        .unwrap();
}
