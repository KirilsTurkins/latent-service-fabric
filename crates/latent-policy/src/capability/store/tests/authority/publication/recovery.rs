//! Real catalog and policy-owner canary for inherited state bindings.
use super::*;
use latent_artifacts::ReleaseUseEligibility;
use latent_core::{InvocationPrincipal, PrincipalKind};

const CONTRACT: &str = "latent:state/key-value@0.2.0";
const PURPOSES: [&str; 6] = [
    "namespace-snapshot",
    "namespace-inspect-restore",
    "namespace-restore",
    "namespace-schema-migrate",
    "namespace-review-recovery",
    "namespace-resume",
];

fn resource() -> serde_json::Value {
    serde_json::json!({"kind":"state","scopes":[{"namespace":"aggregate","incarnation":1,
        "entity":null,"recoveryKind":"original-caller","recoveryScope":"operator-scope","resultPolicy":"owner"}]})
}
fn target() -> ResourceTarget<'static> {
    ResourceTarget::State {
        namespace: "aggregate",
        incarnation: 1,
        entity: None,
        recovery_kind: crate::capability::RecoveryScopeKind::OriginalCaller,
        recovery_scope: "operator-scope",
        result_policy: "owner",
    }
}
fn input<'a>(
    actor: &'a InvocationPrincipal,
    publication: &'a str,
    purpose: &'a str,
) -> EvaluationInput<'a> {
    EvaluationInput {
        principal: actor,
        service: "echo",
        publication,
        capability: CONTRACT,
        operation: purpose,
        resource: target(),
    }
}
fn configure(store: &PolicyStore, publication: &str) -> InvocationPrincipal {
    let mut operator = principal();
    operator.kind = PrincipalKind::Administrator;
    operator.subject = "operator".into();
    let mut document = policy();
    let user = &mut document["rules"][0];
    user["capability"] = CONTRACT.into();
    user["publications"] = serde_json::json!([publication]);
    user["operations"] = serde_json::json!(["get", "read-result"]);
    user["resources"] = resource();
    let mut admin = user.clone();
    admin["id"] = "native-recovery".into();
    admin["principals"] = serde_json::json!([{"kind":"administrator","subject":operator.subject}]);
    admin["operations"] = serde_json::json!(PURPOSES);
    document["rules"].as_array_mut().unwrap().push(admin);
    mutate(
        store,
        "p",
        "explicit-caller-purposes",
        0,
        Some(&serde_json::to_vec(&document).unwrap()),
    )
    .unwrap();
    let mut inherited = binding();
    inherited["capability"] = CONTRACT.into();
    inherited["providerProfile"] = "protected-state-v1".into();
    inherited["restriction"] = serde_json::json!({"operations":[]});
    store
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                kind: RecordKind::ProviderBinding,
                id: "binding",
                operation_id: "inherited-state-binding",
                expected_revision: 0,
                document: Some(&serde_json::to_vec(&inherited).unwrap()),
            },
            deadline(),
            |_| Ok(()),
        )
        .unwrap();
    operator
}

fn restrictions<'a>(
    operations: &'a [String],
    inherited: &'a GrantRestriction,
    digest: &'a str,
) -> CallRestrictions<'a> {
    CallRestrictions {
        imported_operations: operations,
        deployment: inherited,
        provider_configuration: inherited,
        provider_profile: "protected-state-v1",
        configuration_digest: digest,
        configuration_epoch: 1,
        remaining: CapabilityCeiling {
            operations: 2,
            input_bytes: 128,
            output_bytes: 256,
            wall_time_millis: 100,
        },
        input_bytes: 128,
        output_bytes: 256,
    }
}

fn selected(fixture: &Fixture) -> (ManagedPublicationReceipt, ReleaseUseEligibility) {
    let receipt = publish(fixture, "inherited-state");
    let proof = fixture
        .catalog
        .execution_eligibility_selected(
            &receipt.operation.record.as_ref().unwrap().release,
            Some(&receipt.publication.id),
        )
        .unwrap()
        .unwrap();
    (receipt, proof)
}

#[test]
fn inherited_state_binding_keeps_caller_purposes_and_final_publication_fences() {
    let fixture = Fixture::new();
    let (receipt, proof) = selected(&fixture);
    let store = fixture.store(PolicyStoreLimits::default());
    let operator = configure(&store, proof.publication().as_str());
    let snapshot = store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .unwrap();
    let inherited = GrantRestriction::parse(br#"{"operations":[]}"#, CONTRACT).unwrap();
    let operations = PURPOSES
        .iter()
        .map(|value| (*value).into())
        .collect::<Vec<_>>();
    let digest = format!("sha256:{}", "2".repeat(64));
    let restrictions = restrictions(&operations, &inherited, &digest);
    let user = principal();
    let mut captured = Vec::new();
    for purpose in PURPOSES {
        let decision = snapshot
            .authorize(
                input(&operator, proof.publication().as_str(), purpose),
                &restrictions,
                &proof,
            )
            .unwrap();
        captured.push(store.retain_decision(&decision).unwrap());
        assert!(snapshot
            .authorize(
                input(&user, proof.publication().as_str(), purpose),
                &restrictions,
                &proof
            )
            .is_err());
        let mut foreign = input(&operator, proof.publication().as_str(), purpose);
        if let ResourceTarget::State { namespace, .. } = &mut foreign.resource {
            *namespace = "other";
        }
        assert!(snapshot.authorize(foreign, &restrictions, &proof).is_err());
    }
    let mut missing = restrictions;
    missing.imported_operations = &[];
    assert!(snapshot
        .authorize(
            input(&operator, proof.publication().as_str(), PURPOSES[0]),
            &missing,
            &proof
        )
        .is_err());
    let originals = captured.iter().collect::<Vec<_>>();
    let mut accepted = 0;
    store
        .with_retained_decisions(&originals, &mut |_| {
            accepted += 1;
            Ok(())
        })
        .unwrap();
    fixture
        .catalog
        .change_publication_lifecycle(
            context("revoke-inherited-state", 1),
            &receipt.publication,
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert!(store
        .with_retained_decisions(&originals, &mut |_| {
            accepted += 1;
            Ok(())
        })
        .is_err());
    assert_eq!(accepted, 1);
}
