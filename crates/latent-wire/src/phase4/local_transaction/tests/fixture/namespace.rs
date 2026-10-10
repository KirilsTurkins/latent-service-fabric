//! Real policy and lifecycle fences for explicit test-operator transitions.
use super::*;
use latent_capabilities::namespace::{
    CallerScope, NamespaceControl, NamespaceControlRequest, RecoverySelection, STATE_CONTRACT,
};
use latent_core::{InvocationPrincipal, PrincipalKind};
use latent_policy::capability::{
    CallRestrictions, CapabilityCeiling, EvaluationInput, GrantRestriction, MutationRequest,
    RecordKind, ResourceTarget,
};
use latent_state::namespace::{NamespaceRecord, NamespaceTransition};
use serde_json::json;

fn operator() -> InvocationPrincipal {
    let mut principal = principal("namespace-operator");
    principal.kind = PrincipalKind::Administrator;
    principal
}
fn install(f: &Fixture) {
    let caller = CallerScope::derive(&operator(), &RecoverySelection::OriginalCaller).unwrap();
    let ops = [
        "namespace-inspect",
        "namespace-quiesce",
        "namespace-retire",
        "namespace-destroy",
        "namespace-recreate",
    ];
    let scopes:Vec<_>=(1..=2).map(|incarnation|json!({"namespace":publication::NAMESPACE,"incarnation":incarnation,"entity":null,"recoveryKind":caller.kind,"recoveryScope":caller.scope,"resultPolicy":"visibility-v1"})).collect();
    let policy = json!({"formatVersion":1,"tenant":publication::TENANT,"rules":[{"id":"namespace-operator","effect":"allow","principals":[{"kind":"administrator","subject":"namespace-operator"}],"services":[publication::SERVICE],"publications":[f.publication.publication().as_str()],"capability":STATE_CONTRACT,"operations":ops,"resources":{"kind":"state","scopes":scopes},"ceiling":{"operations":8,"inputBytes":2_097_152,"outputBytes":2_097_152,"wallTimeMillis":10_000}}]});
    let provider = json!({"formatVersion":1,"tenant":publication::TENANT,"capability":STATE_CONTRACT,"providerProfile":"namespace-v1","configurationDigest":format!("sha256:{}","2".repeat(64)),"configurationEpoch":1,"restriction":{"operations":[]}});
    for (kind, id, value) in [
        (RecordKind::Policy, "namespace-control", policy),
        (
            RecordKind::ProviderBinding,
            "namespace-control-binding",
            provider,
        ),
    ] {
        f.policy
            .mutate(
                MutationRequest {
                    tenant: publication::TENANT,
                    actor: "compiled-guest-test-operator",
                    kind,
                    id,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&value).unwrap()),
                },
                Instant::now() + Duration::from_secs(10),
                |_| Ok(()),
            )
            .unwrap();
    }
}

pub(super) async fn transition(
    f: &Fixture,
    action: NamespaceTransition,
) -> Result<NamespaceRecord, PlatformError> {
    let deadline = Instant::now() + Duration::from_secs(10);
    if f.policy
        .get(
            publication::TENANT,
            RecordKind::Policy,
            "namespace-control",
            64 * 1024,
            deadline,
        )?
        .value()
        .is_none()
    {
        install(f);
    }
    let policy = Arc::clone(&f.policy);
    let namespaces = Arc::clone(&f.namespaces);
    let publication = f.publication.clone();
    f.store
        .with_store(StoreIoKind::RecoveryWrite, 128 * 1024, move |engine| {
            let operation = match &action {
                NamespaceTransition::Quiesce => "namespace-quiesce",
                NamespaceTransition::Retire => "namespace-retire",
                NamespaceTransition::Destroy => "namespace-destroy",
                NamespaceTransition::Recreate { .. } => "namespace-recreate",
            };
            let view = engine.snapshot()?;
            let current = NamespaceCatalog::read_in(
                &view,
                &TenantId(publication::TENANT.into()),
                &latent_core::StateNamespaceId(publication::NAMESPACE.into()),
            )
            .unwrap()
            .unwrap();
            let expected = current.record().version;
            drop(view);
            let actor = operator();
            let caller = CallerScope::derive(&actor, &RecoverySelection::OriginalCaller).unwrap();
            let snapshot = policy
                .snapshot(
                    &TenantId(publication::TENANT.into()),
                    &["namespace-control".into()],
                    "namespace-control-binding",
                    deadline,
                )
                .unwrap();
            let restrictions =
                GrantRestriction::parse(br#"{"operations":[]}"#, STATE_CONTRACT).unwrap();
            let decision = match snapshot.authorize(
                EvaluationInput {
                    principal: &actor,
                    service: publication::SERVICE,
                    publication: publication.publication().as_str(),
                    capability: STATE_CONTRACT,
                    operation,
                    resource: ResourceTarget::State {
                        namespace: publication::NAMESPACE,
                        incarnation: expected.incarnation,
                        entity: None,
                        recovery_kind: caller.kind,
                        recovery_scope: &caller.scope,
                        result_policy: "visibility-v1",
                    },
                },
                &CallRestrictions {
                    imported_operations: &[operation.into()],
                    deployment: &restrictions,
                    provider_configuration: &restrictions,
                    provider_profile: "namespace-v1",
                    configuration_digest: &format!("sha256:{}", "2".repeat(64)),
                    configuration_epoch: 1,
                    remaining: CapabilityCeiling {
                        operations: 1,
                        input_bytes: 2_097_152,
                        output_bytes: 2_097_152,
                        wall_time_millis: 10_000,
                    },
                    input_bytes: 0,
                    output_bytes: 0,
                },
                &publication,
            ) {
                Ok(value) => value,
                Err(error) => return Ok(Err(error)),
            };
            let mutation = NamespaceMutation::Transition {
                id: latent_core::StateNamespaceId(publication::NAMESPACE.into()),
                expected,
                action,
            };
            let operation_id = format!(
                "{operation}-{}-{}",
                expected.incarnation, expected.generation
            );
            let prepared = match NamespaceControl::prepare(
                &policy,
                &decision,
                &namespaces,
                engine,
                NamespaceControlRequest {
                    mutation: &mutation,
                    operation_id: &operation_id,
                    inspection: None,
                },
                0,
            ) {
                Ok(value) => value,
                Err(error) => return Ok(Err(error)),
            };
            let (batch, receipt, replayed, fence) = prepared.into_parts();
            assert!(!replayed);
            let mut completion = None;
            engine
                .apply_fenced(batch, || fence.accept().map(|value| completion = value))
                .unwrap();
            let view = engine.snapshot()?;
            let read = NamespaceCatalog::read_in(&view, &receipt.record.tenant, &receipt.record.id)
                .unwrap()
                .unwrap();
            if let Some(completion) = completion {
                completion.resolve(&read).unwrap();
            }
            Ok(Ok(receipt.record))
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap()
}

pub(super) fn authorize_incarnation(f: &Fixture, incarnation: u64) {
    let deadline = Instant::now() + Duration::from_secs(10);
    for id in ["state", "intents"] {
        let current = f
            .policy
            .get(
                publication::TENANT,
                RecordKind::Policy,
                id,
                64 * 1024,
                deadline,
            )
            .unwrap();
        let revision = current.value().as_ref().unwrap().revision;
        let mut document: serde_json::Value =
            serde_json::from_str(current.value().as_ref().unwrap().document.as_ref().unwrap())
                .unwrap();
        drop(current);
        for rule in document["rules"].as_array_mut().unwrap() {
            for scope in rule["resources"]["scopes"].as_array_mut().unwrap() {
                scope["incarnation"] = incarnation.into();
            }
        }
        f.policy
            .mutate(
                MutationRequest {
                    tenant: publication::TENANT,
                    actor: "compiled-guest-test-operator",
                    kind: RecordKind::Policy,
                    id,
                    operation_id: &format!("authorize-{id}-{incarnation}"),
                    expected_revision: revision,
                    document: Some(&serde_json::to_vec(&document).unwrap()),
                },
                deadline,
                |_| Ok(()),
            )
            .unwrap();
    }
    use latent_effects::authority::*;
    f.effects
        .publish(EffectRule {
            scope: EffectScope {
                tenant: publication::TENANT.into(),
                namespace: publication::NAMESPACE.into(),
                incarnation,
                publication: f.publication.publication().as_str().into(),
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
}
