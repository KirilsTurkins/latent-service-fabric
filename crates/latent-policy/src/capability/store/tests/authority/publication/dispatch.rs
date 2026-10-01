use super::*;

const CONTRACT: &str = "latent:intents/staging@0.1.0";
fn scope() -> serde_json::Value {
    serde_json::json!({"kind":"state","scopes":[{"namespace":"aggregate","incarnation":1,"entity":null,
        "recoveryKind":"service-integration","recoveryScope":"dispatch-service-scope","resultPolicy":"owner"}]})
}
fn configured(store: &PolicyStore, publication: &str) -> InvocationPrincipal {
    let mut actor = principal();
    actor.kind = latent_core::PrincipalKind::Service;
    actor.service = Some(latent_core::ServiceId("a/echo".into()));
    actor.subject = InvocationPrincipal::local_service_subject(
        &TenantId("a".into()),
        actor.service.as_ref().unwrap(),
    );
    let mut policy = policy();
    policy["rules"][0]["principals"] =
        serde_json::json!([{"kind":"service","subject":actor.subject}]);
    policy["rules"][0]["services"] = serde_json::json!(["a/echo"]);
    policy["rules"][0]["publications"] = serde_json::json!([publication]);
    policy["rules"][0]["capability"] = CONTRACT.into();
    policy["rules"][0]["operations"] = serde_json::json!(["dispatch"]);
    policy["rules"][0]["resources"] = scope();
    policy["rules"][0]["ceiling"] = serde_json::json!({"operations":1,"inputBytes":27,"outputBytes":2048,"wallTimeMillis":2000});
    mutate(
        store,
        "p",
        "dispatch-policy",
        0,
        Some(&serde_json::to_vec(&policy).unwrap()),
    )
    .unwrap();
    let mut binding = binding();
    binding["capability"] = CONTRACT.into();
    binding["providerProfile"] = "qualified-http-put-once-v1".into();
    binding["restriction"] = serde_json::json!({"operations":["dispatch"],"resources":scope()});
    store
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                kind: RecordKind::ProviderBinding,
                id: "binding",
                operation_id: "dispatch-binding",
                expected_revision: 0,
                document: Some(&serde_json::to_vec(&binding).unwrap()),
            },
            deadline(),
            |_| Ok(()),
        )
        .unwrap();
    actor
}
#[test]
fn explicit_native_dispatch_decision_keeps_current_source_policy_and_original_deadline() {
    let fixture = Fixture::new();
    let receipt = publish(&fixture, "native-dispatch");
    let release = fixture
        .catalog
        .execution_eligibility_selected(
            &receipt.operation.record.as_ref().unwrap().release,
            Some(&receipt.publication.id),
        )
        .unwrap()
        .unwrap();
    let store = fixture.store(PolicyStoreLimits::default());
    let actor = configured(&store, release.publication().as_str());
    let snapshot = store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .unwrap();
    assert_eq!(snapshot.generation(), 3);
    let input = || EvaluationInput {
        principal: &actor,
        service: "a/echo",
        publication: release.publication().as_str(),
        capability: CONTRACT,
        operation: "dispatch",
        resource: ResourceTarget::State {
            namespace: "aggregate",
            incarnation: 1,
            entity: None,
            recovery_kind: crate::capability::RecoveryScopeKind::ServiceIntegration,
            recovery_scope: "dispatch-service-scope",
            result_policy: "owner",
        },
    };
    let restriction = GrantRestriction::parse(br#"{"operations":[]}"#, CONTRACT).unwrap();
    let operations = vec!["dispatch".into()];
    let digest = format!("sha256:{}", "2".repeat(64));
    let restrictions = CallRestrictions {
        imported_operations: &operations,
        deployment: &restriction,
        provider_configuration: &restriction,
        provider_profile: "qualified-http-put-once-v1",
        configuration_digest: &digest,
        configuration_epoch: 1,
        remaining: CapabilityCeiling {
            operations: 1,
            input_bytes: 27,
            output_bytes: 2048,
            wall_time_millis: 2000,
        },
        input_bytes: 27,
        output_bytes: 2048,
    };
    let decision = snapshot
        .authorize(input(), &restrictions, &release)
        .unwrap();
    let mut accepted = 0;
    store
        .with_current(&decision, &mut |actual, ceiling| {
            assert_eq!(actual.principal, &actor);
            assert_eq!(actual.operation, "dispatch");
            assert_eq!(ceiling.wall_time_millis, 2000);
            accepted += 1;
            assert!(mutate(&store, "p", "concurrent-revoke", 2, None).is_err());
            Ok(())
        })
        .unwrap();
    let mut wrong_purpose = input();
    wrong_purpose.operation = "stage";
    assert!(snapshot
        .authorize(wrong_purpose, &restrictions, &release)
        .is_err());
    let mut foreign = actor.clone();
    foreign.tenant = Some(TenantId("b".into()));
    let mut wrong_caller = input();
    wrong_caller.principal = &foreign;
    assert!(snapshot
        .authorize(wrong_caller, &restrictions, &release)
        .is_err());
    mutate(&store, "p", "actual-revoke", 2, None).unwrap();
    assert!(store
        .with_current(&decision, &mut |_, _| {
            accepted += 1;
            Ok(())
        })
        .is_err());
    assert_eq!(accepted, 1);
    assert!(store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .is_err());
}
