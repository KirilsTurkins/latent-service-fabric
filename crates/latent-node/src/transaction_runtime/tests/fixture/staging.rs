use super::*;
use latent_capabilities::namespace::{CallerScope, RecoverySelection, INTENT_CONTRACT};
use latent_effects::authority::{DispatchCeiling, DispatchProfile, EffectRule, EffectScope};
use latent_policy::capability::GrantRestriction;
use serde_json::json;

pub(super) fn install(
    policy: &PolicyStore,
    publication: &ReleaseUseEligibility,
    effects: &EffectAuthorityOwner,
) -> PolicyCallBinding {
    let caller =
        CallerScope::derive(&policy::principal(), &RecoverySelection::OriginalCaller).unwrap();
    let digest = format!("sha256:{}", "2".repeat(64));
    let documents = [
        (
            RecordKind::Policy,
            "staging",
            json!({"formatVersion":1,"tenant":"a","rules":[{
                "id":"original-caller","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
                "services":["a/echo"],"publications":[publication.publication().as_str()],"capability":INTENT_CONTRACT,"operations":["stage"],
                "resources":{"kind":"state","scopes":[{"namespace":"orders","incarnation":1,"entity":null,"recoveryKind":caller.kind,"recoveryScope":caller.scope,"resultPolicy":"visibility-v1"}]},
                "ceiling":{"operations":1,"inputBytes":65536,"outputBytes":65536,"wallTimeMillis":10_000}
            }]}),
        ),
        (
            RecordKind::ProviderBinding,
            "staging-binding",
            json!({"formatVersion":1,"tenant":"a","capability":INTENT_CONTRACT,"providerProfile":"namespace-v1",
                   "configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":["stage"]}}),
        ),
    ];
    for (kind, id, document) in documents {
        policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind,
                    id,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&document).unwrap()),
                },
                Instant::now() + Duration::from_secs(10),
                |_| Ok(()),
            )
            .unwrap();
    }
    effects
        .publish(EffectRule {
            scope: EffectScope {
                tenant: "a".into(),
                namespace: "orders".into(),
                incarnation: 1,
                publication: publication.publication().as_str().into(),
                binding: "approved-event".into(),
                operation: "event".into(),
            },
            profile: DispatchProfile {
                provider: "events".into(),
                destination: "events.subject".into(),
                adapter: "qualified-test-v1".into(),
                intent_format: 1,
                payload_format: "lsf-value-v1".into(),
                idempotency_profile: "qualified-test-idempotency-v1".into(),
            },
            policy_revision: 1,
            credential_epoch: 1,
            protected_credential_reference: "protected-fixture-events".into(),
            ceiling: DispatchCeiling {
                maximum_payload_bytes: 1024,
                maximum_response_bytes: 1024,
                maximum_attempts: 1,
                maximum_age_millis: 1000,
                attempt_timeout_millis: 100,
            },
            enabled: true,
        })
        .unwrap();
    PolicyCallBinding {
        policies: vec!["staging".into()],
        binding: "staging-binding".into(),
        profile: "namespace-v1".into(),
        configuration_digest: digest,
        configuration_epoch: 1,
        operations: vec!["stage".into()],
        deployment: GrantRestriction::parse(br#"{"operations":["stage"]}"#, INTENT_CONTRACT)
            .unwrap(),
        provider_configuration: GrantRestriction::parse(
            br#"{"operations":["stage"]}"#,
            INTENT_CONTRACT,
        )
        .unwrap(),
    }
}
