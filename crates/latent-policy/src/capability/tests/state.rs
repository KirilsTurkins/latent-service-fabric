use super::*;

fn scope(namespace: &str, entity: Option<&str>, recovery: &str) -> Value {
    json!({"namespace":namespace,"incarnation":1,"entity":entity,
        "recoveryKind":"original-caller","recoveryScope":recovery,"resultPolicy":"visibility-v1"})
}
fn target<'a>(
    namespace: &'a str,
    entity: Option<&'a str>,
    recovery_scope: &'a str,
) -> ResourceTarget<'a> {
    ResourceTarget::State {
        namespace,
        incarnation: 1,
        entity,
        recovery_kind: RecoveryScopeKind::OriginalCaller,
        recovery_scope,
        result_policy: "visibility-v1",
    }
}

#[test]
fn state_policy_matches_exact_tuples_without_cross_product_or_incarnation_revival() {
    let resource: ResourceConstraint = serde_json::from_value(json!({"kind":"state","scopes":[
        scope("orders",Some("alice-order"),"caller-a"), scope("invoices",Some("bob-invoice"),"caller-b")]})).unwrap();
    resource.validate().unwrap();
    assert!(resource.covers(&target("orders", Some("alice-order"), "caller-a")));
    for requested in [
        target("orders", Some("bob-invoice"), "caller-a"),
        target("orders", Some("alice-order"), "caller-b"),
        target("invoices", Some("alice-order"), "caller-b"),
        target("orders", None, "caller-a"),
        ResourceTarget::State {
            namespace: "orders",
            incarnation: 2,
            entity: Some("alice-order"),
            recovery_kind: RecoveryScopeKind::OriginalCaller,
            recovery_scope: "caller-a",
            result_policy: "visibility-v1",
        },
    ] {
        assert!(!resource.covers(&requested));
    }
    let ResourceTarget::State {
        namespace,
        incarnation,
        entity,
        recovery_kind,
        recovery_scope,
        ..
    } = target("orders", Some("alice-order"), "caller-a")
    else {
        unreachable!()
    };
    assert!(!resource.covers(&ResourceTarget::State {
        namespace,
        incarnation,
        entity,
        recovery_kind,
        recovery_scope,
        result_policy: "visibility-v2"
    }));
}

#[test]
fn same_tenant_subjects_require_current_entity_and_result_policy_grants() {
    let mut value = policy();
    value["rules"][0]["capability"] = "latent:state/key-value@0.2.0".into();
    value["rules"][0]["operations"] = json!(["get", "read-result"]);
    value["rules"][0]["resources"] =
        json!({"kind":"state","scopes":[scope("orders",Some("alice-order"),"caller-a")]});
    let parsed = CapabilityPolicy::parse(&serde_json::to_vec(&value).unwrap()).unwrap();
    let actor = principal();
    assert!(parsed
        .evaluate(
            &actor,
            "echo",
            &publication_id(),
            "latent:state/key-value@0.2.0",
            "read-result",
            &target("orders", Some("alice-order"), "caller-a")
        )
        .is_some());
    let mut bob = actor;
    bob.subject = "bob".into();
    bob.claims
        .insert("recovery-scope".into(), "caller-a".into());
    assert!(parsed
        .evaluate(
            &bob,
            "echo",
            &publication_id(),
            "latent:state/key-value@0.2.0",
            "read-result",
            &target("orders", Some("alice-order"), "caller-a")
        )
        .is_none());
    assert!(parsed
        .evaluate(
            &principal(),
            "echo",
            &publication_id(),
            "latent:state/key-value@0.2.0",
            "read-result",
            &target("orders", Some("bob-invoice"), "caller-a")
        )
        .is_none());
}

#[test]
fn state_and_intent_opt_ins_preserve_stateless_linking_and_closed_bounded_decoding() {
    assert!(latent_core::PHASE3_HOST_ABI_CURRENT
        .interface("latent:state/key-value@0.2.0")
        .is_none());
    for (contract, op) in [
        ("latent:state/key-value@0.2.0", "put"),
        ("latent:intents/staging@0.1.0", "stage"),
    ] {
        let mut value = policy();
        value["rules"][0]["capability"] = contract.into();
        value["rules"][0]["operations"] = json!([op]);
        value["rules"][0]["resources"] =
            json!({"kind":"state","scopes":[scope("orders",Some("é"),"caller-a")]});
        assert!(CapabilityPolicy::parse(&serde_json::to_vec(&value).unwrap()).is_ok());
        for bad in [
            json!({"kind":"state","scopes":[scope("orders",Some(&"é".repeat(129)),"caller-a")]}),
            json!({"kind":"state","scopes":[scope("orders",None,"caller-a"),scope("orders",None,"caller-a")]}),
            json!({"kind":"state","scopes":vec![scope("orders",None,"caller-a");17]}),
            json!({"kind":"state","scopes":[{"namespace":"orders","incarnation":1,"recoveryKind":"shared","recoveryScope":"forged","resultPolicy":"visibility-v1"}]}),
        ] {
            value["rules"][0]["resources"] = bad;
            assert!(CapabilityPolicy::parse(&serde_json::to_vec(&value).unwrap()).is_err());
        }
    }
}
