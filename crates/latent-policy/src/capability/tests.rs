use super::*;
use latent_core::{InvocationPrincipal, PrincipalKind, TenantId};
use serde_json::{json, Value};

pub(super) fn publication_id() -> String {
    format!("publication:sha256:{}", "1".repeat(64))
}
pub(super) fn principal() -> InvocationPrincipal {
    InvocationPrincipal {
        subject: "alice".into(),
        kind: PrincipalKind::User,
        tenant: Some(TenantId("a".into())),
        service: None,
        claims: latent_core::Metadata::new(),
    }
}
pub(super) fn policy() -> Value {
    json!({"formatVersion":1,"tenant":"a","rules":[{
        "id":"allow","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
        "services":["echo"],"publications":[publication_id()],"capability":"latent:secrets/reader@0.1.0",
        "operations":["read"],"resources":{"kind":"secrets","references":["test-key"]},
        "ceiling":{"operations":4,"inputBytes":128,"outputBytes":256,"wallTimeMillis":100}
    }]})
}
pub(super) fn binding() -> Value {
    json!({"formatVersion":1,"tenant":"a","capability":"latent:secrets/reader@0.1.0",
        "providerProfile":"local-secrets-v1","configurationDigest":format!("sha256:{}","2".repeat(64)),
        "configurationEpoch":1,"restriction":{"operations":[]}})
}
fn allowed(value: &Value, principal: &InvocationPrincipal) -> Option<CapabilityCeiling> {
    let policy = CapabilityPolicy::parse(&serde_json::to_vec(value).unwrap()).unwrap();
    policy.evaluate(
        principal,
        "echo",
        &publication_id(),
        "latent:secrets/reader@0.1.0",
        "read",
        &ResourceTarget::Secrets {
            reference: "test-key",
        },
    )
}
#[test]
fn exact_identity_is_required_and_guest_claims_do_not_supply_it() {
    let value = policy();
    let mut actor = principal();
    assert!(allowed(&value, &actor).is_some());
    actor.tenant = Some(TenantId("b".into()));
    actor.claims.insert("tenant".into(), "a".into());
    assert!(allowed(&value, &actor).is_none());
    actor = principal();
    actor.kind = PrincipalKind::Administrator;
    assert!(allowed(&value, &actor).is_none());
    actor = principal();
    actor.subject = "mallory".into();
    assert!(allowed(&value, &actor).is_none());
    let mut value = policy();
    value["rules"][0]["publications"] = json!([format!("publication:sha256:{}", "3".repeat(64))]);
    assert!(allowed(&value, &principal()).is_none());
}
#[test]
fn empty_sets_default_deny_and_matching_deny_overrides_every_allow() {
    for key in ["principals", "services", "publications", "operations"] {
        let mut value = policy();
        value["rules"][0][key] = json!([]);
        assert!(allowed(&value, &principal()).is_none(), "{key}");
    }
    let mut value = policy();
    let mut deny = value["rules"][0].clone();
    deny["id"] = "deny".into();
    deny["effect"] = "deny".into();
    value["rules"].as_array_mut().unwrap().push(deny);
    assert!(allowed(&value, &principal()).is_none());
    value["rules"] = json!([]);
    assert!(allowed(&value, &principal()).is_none());
}
#[test]
fn matching_allow_rules_intersect_every_ceiling_instead_of_building_a_union() {
    let mut value = policy();
    let mut other = value["rules"][0].clone();
    other["id"] = "narrow".into();
    other["ceiling"]["operations"] = 1.into();
    other["ceiling"]["outputBytes"] = 512.into();
    other["ceiling"]["wallTimeMillis"] = 25.into();
    value["rules"].as_array_mut().unwrap().push(other);
    let actual = allowed(&value, &principal()).unwrap();
    assert_eq!(
        actual,
        CapabilityCeiling {
            operations: 1,
            input_bytes: 128,
            output_bytes: 256,
            wall_time_millis: 25
        }
    );
}
#[test]
fn malformed_unknown_duplicate_and_null_constraints_are_rejected() {
    let good = serde_json::to_string(&policy()).unwrap();
    for bad in [
        good.replacen(
            "\"formatVersion\":1",
            "\"formatVersion\":1,\"formatVersion\":1",
            1,
        ),
        good.replacen("\"formatVersion\":1", "\"formatVersion\":2", 1),
        good.replacen("\"effect\":\"allow\"", "\"effect\":\"script\"", 1),
        good.replacen("\"read\"", "\"execute\"", 1),
    ] {
        assert!(CapabilityPolicy::parse(bad.as_bytes()).is_err());
    }
    for resources in [
        json!(null),
        json!({"kind":"secrets","references":["test-key","test-key"]}),
        json!({"kind":"secrets","references":["test-key"],"unknown":true}),
        json!({"kind":"http","origins":[]}),
    ] {
        let mut value = policy();
        value["rules"][0]["resources"] = resources;
        assert!(CapabilityPolicy::parse(&serde_json::to_vec(&value).unwrap()).is_err());
    }
    let mut huge = policy();
    huge["rules"][0]["principals"][0]["subject"] = "x".repeat(257).into();
    assert!(CapabilityPolicy::parse(&serde_json::to_vec(&huge).unwrap()).is_err());
    assert!(CapabilityPolicy::parse(&vec![b' '; MAX_DOCUMENT_BYTES + 1]).is_err());
}
#[test]
fn additional_restrictions_inherit_only_when_absent_and_never_grant_by_themselves() {
    let contract = "latent:secrets/reader@0.1.0";
    let inherited = GrantRestriction::parse(br#"{"operations":[]}"#, contract).unwrap();
    let ceiling = allowed(&policy(), &principal()).unwrap();
    assert_eq!(
        inherited.narrow(
            "read",
            &ResourceTarget::Secrets {
                reference: "test-key"
            },
            ceiling
        ),
        Some(ceiling)
    );
    for bytes in [
        br#"{"operations":[],"resources":null}"#.as_slice(),
        br#"{"operations":[],"ceiling":null}"#,
        br#"{"operations":["read","read"]}"#,
        br#"{"operations":[],"resources":{"kind":"context"}}"#,
    ] {
        assert!(GrantRestriction::parse(bytes, contract).is_err());
    }
    let deny = GrantRestriction::parse(
        br#"{"operations":[],"resources":{"kind":"secrets","references":[]}}"#,
        contract,
    )
    .unwrap();
    assert!(deny
        .narrow(
            "read",
            &ResourceTarget::Secrets {
                reference: "test-key"
            },
            ceiling
        )
        .is_none());
}
#[test]
fn normalized_http_scope_has_exact_origins_and_segment_prefixes() {
    let origin = HttpOrigin {
        scheme: "https".into(),
        host: "example.test".into(),
        port: 443,
    };
    let scope = ResourceConstraint::Http {
        origins: vec![origin.clone()],
        methods: vec!["GET".into()],
        paths: vec!["/health".into()],
        path_prefixes: vec!["/v1/".into()],
    };
    scope.validate().unwrap();
    for path in ["/health", "/v1/items"] {
        assert!(scope.covers(&ResourceTarget::Http {
            origin: &origin,
            method: "GET",
            path
        }));
    }
    for path in [
        "/v10/items",
        "/v1/../private",
        "/v1/%2e%2e/private",
        "/v1/\u{7f}",
    ] {
        assert!(!scope.covers(&ResourceTarget::Http {
            origin: &origin,
            method: "GET",
            path
        }));
    }
    assert!(!scope.covers(&ResourceTarget::Http {
        origin: &origin,
        method: "POST",
        path: "/health"
    }));
    let mut other = origin.clone();
    other.port = 444;
    assert!(!scope.covers(&ResourceTarget::Http {
        origin: &other,
        method: "GET",
        path: "/health"
    }));
}
#[test]
fn binding_digest_tracks_only_validated_immutable_configuration_identity() {
    let bytes = serde_json::to_vec(&binding()).unwrap();
    let parsed = ProviderBinding::parse(&bytes).unwrap();
    assert_eq!(
        ProviderBinding::parse(parsed.canonical()).unwrap().digest(),
        parsed.digest()
    );
    let mut bad = binding();
    bad["configurationEpoch"] = 0.into();
    assert!(ProviderBinding::parse(&serde_json::to_vec(&bad).unwrap()).is_err());
    bad = binding();
    bad["credentials"] = "do-not-retain".into();
    let error = ProviderBinding::parse(&serde_json::to_vec(&bad).unwrap())
        .err()
        .unwrap();
    assert_eq!(error.message, "capability-policy-invalid");
}
