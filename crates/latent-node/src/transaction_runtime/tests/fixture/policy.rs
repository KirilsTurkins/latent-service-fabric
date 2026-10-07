use super::*;
use latent_capabilities::namespace::{CallerScope, RecoverySelection, STATE_CONTRACT};
use latent_policy::capability::{GrantRestriction, PolicyStoreLimits};
use serde_json::json;
use std::path::Path;

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
pub(super) fn principal() -> latent_core::InvocationPrincipal {
    latent_core::InvocationPrincipal {
        subject: "alice".into(),
        kind: latent_core::PrincipalKind::User,
        tenant: Some(latent_core::TenantId("a".into())),
        service: None,
        claims: Metadata::new(),
    }
}
pub(super) fn create(
    root: &Path,
    catalog: &DirectoryArtifactRepository,
    publication: &ReleaseUseEligibility,
) -> (PolicyStore, PolicyCallBinding) {
    let policy = PolicyStore::open(
        &root.join("policy"),
        PolicyStoreLimits::default(),
        catalog.lifecycle_authority(),
    )
    .unwrap();
    let document = entity_policy(publication, &[]);
    let digest = format!("sha256:{}", "2".repeat(64));
    let binding = json!({"formatVersion":1,"tenant":"a","capability":STATE_CONTRACT,"providerProfile":"namespace-v1","configurationDigest":digest,"configurationEpoch":1,"restriction":{"operations":[]}});
    for (kind, id, operation, document) in [
        (RecordKind::Policy, "state", "state-create", document),
        (
            RecordKind::ProviderBinding,
            "binding",
            "binding-create",
            binding,
        ),
    ] {
        policy
            .mutate(
                MutationRequest {
                    tenant: "a",
                    actor: "operator",
                    kind,
                    id,
                    operation_id: operation,
                    expected_revision: 0,
                    document: Some(&serde_json::to_vec(&document).unwrap()),
                },
                Instant::now() + Duration::from_secs(10),
                |_| Ok(()),
            )
            .unwrap();
    }
    (policy, call_binding())
}

fn entity_policy(publication: &ReleaseUseEligibility, entities: &[&str]) -> serde_json::Value {
    let caller = CallerScope::derive(&principal(), &RecoverySelection::OriginalCaller).unwrap();
    let scopes: Vec<_> = std::iter::once(None).chain(entities.iter().copied().map(Some)).map(|entity| {
        json!({"namespace":"orders","incarnation":1,"entity":entity,"recoveryKind":caller.kind,"recoveryScope":caller.scope,"resultPolicy":"visibility-v1"})
    }).collect();
    json!({"formatVersion":1,"tenant":"a","rules":[{
        "id":"alice","effect":"allow","principals":[{"kind":"user","subject":"alice"}],"services":["a/echo"],"publications":[publication.publication().as_str()],"capability":STATE_CONTRACT,"operations":OPERATIONS,
        "resources":{"kind":"state","scopes":scopes},
        "ceiling":{"operations":256,"inputBytes":2_097_152,"outputBytes":2_097_152,"wallTimeMillis":10_000}
    }]})
}

pub(super) fn install_entities(
    policy: &PolicyStore,
    publication: &ReleaseUseEligibility,
    entities: &[&str],
) {
    let deadline = Instant::now() + Duration::from_secs(10);
    let current = policy
        .get("a", RecordKind::Policy, "state", 64 * 1024, deadline)
        .unwrap();
    let revision = current.value().as_ref().unwrap().revision;
    drop(current);
    policy
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                kind: RecordKind::Policy,
                id: "state",
                operation_id: "entity-scopes",
                expected_revision: revision,
                document: Some(&serde_json::to_vec(&entity_policy(publication, entities)).unwrap()),
            },
            deadline,
            |_| Ok(()),
        )
        .unwrap();
}
fn call_binding() -> PolicyCallBinding {
    PolicyCallBinding {
        policies: vec!["state".into()],
        binding: "binding".into(),
        profile: "namespace-v1".into(),
        configuration_digest: format!("sha256:{}", "2".repeat(64)),
        configuration_epoch: 1,
        operations: OPERATIONS
            .iter()
            .map(|operation| (*operation).into())
            .collect(),
        deployment: GrantRestriction::parse(br#"{"operations":[]}"#, STATE_CONTRACT).unwrap(),
        provider_configuration: GrantRestriction::parse(br#"{"operations":[]}"#, STATE_CONTRACT)
            .unwrap(),
    }
}

pub(super) fn inspection(
    fixture: &Fixture,
    namespace: latent_state::namespace::catalog::NamespaceRead,
    envelope: &latent_activation::ActivationEnvelope,
    budget: &latent_core::ActivationBudget,
) -> Arc<StateAuthorization> {
    use latent_capabilities::namespace::{NamespaceAdmission, NamespaceAuthority};
    use latent_policy::capability::{
        CallRestrictions, CapabilityCeiling, EvaluationInput, ResourceTarget,
    };
    let principal = principal();
    let caller = CallerScope::derive(&principal, &RecoverySelection::OriginalCaller).unwrap();
    let binding = Arc::new(call_binding());
    let deadline = budget.deadline().monotonic().unwrap();
    let snapshot = fixture
        .policy
        .snapshot(
            &latent_core::TenantId("a".into()),
            &binding.policies,
            &binding.binding,
            deadline,
        )
        .unwrap();
    let decision = snapshot
        .authorize(
            EvaluationInput {
                principal: &principal,
                service: "a/echo",
                publication: fixture.publication.publication().as_str(),
                capability: STATE_CONTRACT,
                operation: "read-result",
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
                imported_operations: &binding.operations,
                deployment: &binding.deployment,
                provider_configuration: &binding.provider_configuration,
                provider_profile: &binding.profile,
                configuration_digest: &binding.configuration_digest,
                configuration_epoch: binding.configuration_epoch,
                remaining: CapabilityCeiling {
                    operations: 16,
                    input_bytes: 2_097_152,
                    output_bytes: 2_097_152,
                    wall_time_millis: 1000,
                },
                input_bytes: 0,
                output_bytes: 0,
            },
            &fixture.publication,
        )
        .unwrap();
    let lifecycle = fixture.namespaces.lifecycle().pin(&namespace).unwrap();
    let schema = schema();
    let authority = NamespaceAuthority::seal(
        &fixture.policy,
        &decision,
        &namespace,
        NamespaceAdmission {
            activation: envelope.activation_id.clone(),
            deadline,
            recovery: &RecoverySelection::OriginalCaller,
            state_schema: &schema,
        },
        lifecycle,
    )
    .unwrap();
    Arc::new(
        StateAuthorization::new(
            Arc::clone(&fixture.policy),
            Arc::new(authority),
            namespace,
            principal,
            "a/echo".into(),
            fixture.publication.clone(),
            binding,
            None,
            budget.clone(),
        )
        .unwrap(),
    )
}
