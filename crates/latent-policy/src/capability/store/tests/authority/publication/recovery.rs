//! Real catalog/policy ownership checks, separate from guest or restore execution.
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

fn scope() -> serde_json::Value {
    serde_json::json!({"kind":"state","scopes":[{"namespace":"aggregate","incarnation":1,"entity":null,
        "recoveryKind":"original-caller","recoveryScope":"operator-original-scope","resultPolicy":"owner"}]})
}

fn configured(store: &PolicyStore, publication: &str) -> latent_core::InvocationPrincipal {
    let mut actor = principal();
    actor.kind = latent_core::PrincipalKind::Administrator;
    actor.subject = "operator".into();
    let mut policy = policy();
    policy["rules"][0]["principals"] =
        serde_json::json!([{"kind":"administrator","subject":actor.subject}]);
    policy["rules"][0]["services"] = serde_json::json!(["a/echo"]);
    policy["rules"][0]["publications"] = serde_json::json!([publication]);
    policy["rules"][0]["capability"] = CONTRACT.into();
    policy["rules"][0]["operations"] = serde_json::json!(PURPOSES);
    policy["rules"][0]["resources"] = scope();
    policy["rules"][0]["ceiling"] = serde_json::json!({"operations":1,"inputBytes":65536,"outputBytes":65536,"wallTimeMillis":2000});
    for unknown in [
        "namespace-copy-files",
        "namespace-restore-any-root",
        "namespace-resume\n",
    ] {
        let mut refused = policy.clone();
        refused["rules"][0]["operations"] = serde_json::json!([unknown]);
        assert!(
            crate::capability::CapabilityPolicy::parse(&serde_json::to_vec(&refused).unwrap())
                .is_err()
        );
    }
    mutate(
        store,
        "p",
        "recovery-policy",
        0,
        Some(&serde_json::to_vec(&policy).unwrap()),
    )
    .unwrap();
    let mut binding = binding();
    binding["capability"] = CONTRACT.into();
    binding["providerProfile"] = "native-store-recovery-v1".into();
    binding["restriction"] = serde_json::json!({"operations":PURPOSES,"resources":scope()});
    store
        .mutate(
            MutationRequest {
                tenant: "a",
                actor: "operator",
                kind: RecordKind::ProviderBinding,
                id: "binding",
                operation_id: "recovery-binding",
                expected_revision: 0,
                document: Some(&serde_json::to_vec(&binding).unwrap()),
            },
            deadline(),
            |_| Ok(()),
        )
        .unwrap();
    actor
}

fn scoped_input<'a>(
    actor: &'a latent_core::InvocationPrincipal,
    publication: &'a str,
    purpose: &'a str,
) -> EvaluationInput<'a> {
    EvaluationInput {
        principal: actor,
        service: "a/echo",
        publication,
        capability: CONTRACT,
        operation: purpose,
        resource: ResourceTarget::State {
            namespace: "aggregate",
            incarnation: 1,
            entity: None,
            recovery_kind: crate::capability::RecoveryScopeKind::OriginalCaller,
            recovery_scope: "operator-original-scope",
            result_policy: "owner",
        },
    }
}

fn refused_scopes(
    snapshot: &crate::capability::PolicySnapshot,
    actor: &latent_core::InvocationPrincipal,
    release: &latent_artifacts::ReleaseUseEligibility,
    restrictions: &CallRestrictions<'_>,
) {
    let mut wrong_actor = actor.clone();
    wrong_actor.kind = latent_core::PrincipalKind::User;
    let mut foreign = actor.clone();
    foreign.tenant = Some(TenantId("b".into()));
    for denied in [&wrong_actor, &foreign] {
        let request = scoped_input(denied, release.publication().as_str(), PURPOSES[0]);
        assert!(snapshot.authorize(request, restrictions, release).is_err());
    }
    for (namespace, incarnation, scope) in [
        ("other", 1, "operator-original-scope"),
        ("aggregate", 2, "operator-original-scope"),
        ("aggregate", 1, "other-original-scope"),
    ] {
        let mut request = scoped_input(actor, release.publication().as_str(), PURPOSES[0]);
        request.resource = ResourceTarget::State {
            namespace,
            incarnation,
            entity: None,
            recovery_kind: crate::capability::RecoveryScopeKind::OriginalCaller,
            recovery_scope: scope,
            result_policy: "owner",
        };
        assert!(snapshot.authorize(request, restrictions, release).is_err());
    }
    assert!(snapshot
        .authorize(
            scoped_input(actor, release.publication().as_str(), "namespace-recreate"),
            restrictions,
            release
        )
        .is_err());
}

#[test]
fn native_recovery_decisions_retain_exact_current_operator_scope_and_refuse_revocation() {
    let fixture = Fixture::new();
    let receipt = publish(&fixture, "native-recovery");
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
    let restriction = GrantRestriction::parse(br#"{"operations":[]}"#, CONTRACT).unwrap();
    let operations = PURPOSES.map(str::to_owned);
    let digest = format!("sha256:{}", "2".repeat(64));
    let restrictions = CallRestrictions {
        imported_operations: &operations,
        deployment: &restriction,
        provider_configuration: &restriction,
        provider_profile: "native-store-recovery-v1",
        configuration_digest: &digest,
        configuration_epoch: 1,
        remaining: CapabilityCeiling {
            operations: 1,
            input_bytes: 65536,
            output_bytes: 65536,
            wall_time_millis: 2000,
        },
        input_bytes: 0,
        output_bytes: 0,
    };
    let mut retained = Vec::new();
    for purpose in PURPOSES {
        let decision = snapshot
            .authorize(
                scoped_input(&actor, release.publication().as_str(), purpose),
                &restrictions,
                &release,
            )
            .unwrap();
        retained.push(store.retain_decision(&decision).unwrap());
    }
    refused_scopes(&snapshot, &actor, &release, &restrictions);
    let originals = retained.iter().collect::<Vec<_>>();
    let mut accepted = 0;
    store
        .with_retained_decisions(&originals, &mut |_| {
            accepted += 1;
            assert!(mutate(&store, "p", "concurrent-revoke", 2, None).is_err());
            Ok(())
        })
        .unwrap();
    mutate(&store, "p", "actual-revoke", 2, None).unwrap();
    assert!(store
        .with_retained_decisions(&originals, &mut |_| {
            accepted += 1;
            Ok(())
        })
        .is_err());
    assert_eq!(accepted, 1);
    assert!(store
        .snapshot(&TenantId("a".into()), &["p".into()], "binding", deadline())
        .is_err());
}

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
