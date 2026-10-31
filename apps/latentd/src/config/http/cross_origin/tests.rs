use super::*;
use latent_core::{InvocationPrincipal, Metadata, PrincipalKind};
use serde_json::{json, Value};
use std::io::Write as _;

fn grant() -> Value {
    json!({
        "authority": "assets.example.test",
        "tenant": "tests",
        "publication": format!("publication:sha256:{}", "ab".repeat(32)),
        "origins": ["https://portal.example.test"]
    })
}
fn config(grants: Value) -> Value {
    let mut value = json!({
        "formatVersion": 1,
        "bind": "127.0.0.1:0",
        "transport": {"mode": "trusted-proxy", "peers": ["127.0.0.1"]},
        "authentication": {"mode": "public-origins", "origins": [
            {"authority": "assets.example.test", "tenant": "tests", "subject": "public"}
        ]},
        "crossOriginAssets": []
    });
    value["crossOriginAssets"] = grants;
    value
}
fn owners() -> Authentication {
    Authentication::PublicOrigins(vec![(
        "assets.example.test".into(),
        InvocationPrincipal {
            subject: "public".into(),
            kind: PrincipalKind::Trigger,
            tenant: Some(TenantId("tests".into())),
            service: None,
            claims: Metadata::new(),
        },
    )])
}
fn valid(grants: Value) -> bool {
    serde_json::from_value::<HttpIngressConfig>(config(grants))
        .is_ok_and(|config| validate(&config, Scheme::Https, &owners()).is_ok())
}

#[test]
fn cross_origin_configuration_is_closed_default_empty_and_https_public_only() {
    let mut value = config(json!([]));
    value.as_object_mut().unwrap().remove("crossOriginAssets");
    let default: HttpIngressConfig = serde_json::from_value(value).unwrap();
    assert!(default.cross_origin_assets.is_empty());
    assert!(validate(&default, Scheme::Http, &Authentication::Bearer(Vec::new())).is_ok());
    assert!(valid(json!([grant()])));
    let configured: HttpIngressConfig = serde_json::from_value(config(json!([grant()]))).unwrap();
    assert!(validate(&configured, Scheme::Http, &owners()).is_err());
    assert!(validate(
        &configured,
        Scheme::Https,
        &Authentication::Bearer(Vec::new())
    )
    .is_err());
    assert_eq!(
        configured.cross_origin_assets[0].credentials,
        CrossOriginCredentials::Omit
    );
    for invalid in [Value::Null, json!({}), json!([null])] {
        assert!(!valid(invalid));
    }
    let mut extra = grant();
    extra["allowAnyOrigin"] = json!(true);
    assert!(!valid(json!([extra])));
    for credentials in ["include", "omit"] {
        let mut row = grant();
        row["credentials"] = json!(credentials);
        assert!(valid(json!([row])));
    }
    for credentials in [Value::Null, json!(true), json!("same-origin"), json!("*")] {
        let mut row = grant();
        row["credentials"] = credentials;
        assert!(!valid(json!([row])));
    }
}

#[test]
fn cross_origin_grants_reject_duplicates_foreign_ownership_and_bad_publications() {
    assert!(!valid(json!([grant(), grant()])));
    let mut duplicate = grant();
    duplicate["credentials"] = json!("include");
    assert!(!valid(json!([grant(), duplicate])));
    for (field, value) in [
        ("authority", "foreign.example.test"),
        ("authority", "ASSETS.example.test"),
        ("authority", "assets.example.test:443"),
        ("authority", "*.example.test"),
        ("tenant", "foreign"),
        ("tenant", ""),
        ("publication", "latest"),
        ("publication", "*"),
        ("publication", "sha256:abcd"),
    ] {
        let mut row = grant();
        row[field] = json!(value);
        assert!(!valid(json!([row])), "{field}={value}");
    }
    let mut row = grant();
    row["origins"] = json!(["https://portal.example.test", "https://portal.example.test"]);
    assert!(!valid(json!([row])));
}

#[test]
fn cross_origin_origins_require_exact_ascii_https_serialization() {
    for origin in [
        "https://portal.example.test",
        "https://portal.example.test:8443",
        "https://xn--bcher-kva.example",
        "https://127.0.0.1",
        "https://[::1]:8443",
    ] {
        assert!(canonical_origin(origin), "{origin}");
    }
    for origin in [
        "",
        "null",
        "*",
        "https://*.example.test",
        "http://portal.example.test",
        "HTTPS://portal.example.test",
        "https://PORTAL.example.test",
        "https://portal.example.test:443",
        "https://portal.example.test:08443",
        "https://portal.example.test/",
        "https://portal.example.test/path",
        "https://portal.example.test?x=1",
        "https://portal.example.test#x",
        "https://user@portal.example.test",
        " https://portal.example.test",
        "https://portal.example.test ",
        "https://portal.example.test.",
        "https://portal.example.test,https://other.example.test",
        "https://portal.example.test https://other.example.test",
        "https://bücher.example",
        "https://0x7f000001",
        "https://0177.0.0.1",
        "https://127.1",
        "https://2130706433",
        "https://example.123",
        "https://[0:0:0:0:0:0:0:1]",
        "https://[::1]:443",
        "https://[::ffff:127.0.0.1]",
    ] {
        assert!(!canonical_origin(origin), "{origin}");
    }
    assert!(!canonical_origin(&format!("https://{}", "a".repeat(513))));
}

#[test]
fn cross_origin_configuration_enforces_all_three_independent_bounds() {
    let rows: Vec<_> = (0..MAX_GRANTS)
        .map(|index| {
            let mut row = grant();
            row["publication"] = json!(format!("publication:sha256:{index:064x}"));
            row
        })
        .collect();
    assert!(valid(json!(rows)));
    let mut too_many = rows.clone();
    let mut extra = grant();
    extra["publication"] = json!(format!("publication:sha256:{:064x}", MAX_GRANTS));
    too_many.push(extra);
    assert!(!valid(json!(too_many)));
    let mut row = grant();
    row["origins"] = json!((0..MAX_ORIGINS)
        .map(|index| format!("https://portal{index}.example.test"))
        .collect::<Vec<_>>());
    assert!(valid(json!([row.clone()])));
    row["origins"]
        .as_array_mut()
        .unwrap()
        .push(json!("https://extra.example.test"));
    assert!(!valid(json!([row])));
    let mut large = rows;
    for row in &mut large {
        row["origins"] = json!((0..MAX_ORIGINS)
            .map(|index| format!(
                "https://{}.{}.{}.portal{index}.example.test",
                "a".repeat(60),
                "b".repeat(60),
                "c".repeat(60),
            ))
            .collect::<Vec<_>>());
    }
    assert!(serde_json::to_vec(&large).unwrap().len() > MAX_CONFIGURATION_BYTES);
    assert!(!valid(json!(large)));
    let mut count = ConfigurationBytes(0);
    assert!(count.write_all(&vec![0; MAX_CONFIGURATION_BYTES]).is_ok());
    assert!(count.write_all(&[0]).is_err());
}
