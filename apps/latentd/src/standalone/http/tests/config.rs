use crate::config::NodeConfig;
use serde_json::{json, Value};

pub(super) fn config() -> Value {
    json!({"formatVersion":1, "dataDirectory":std::env::temp_dir().join("unused-http-node"), "nodeId":"http-test", "bind":"127.0.0.1:0",
        "limits":{"maximumPayloadBytes":2_097_152},
        "credentials":[{"token":"invoke-token-0000000000000000000000000000", "subject":"alice", "tenant":"tests", "role":"invoke"},
            {"token":"second-token-0000000000000000000000000000", "subject":"bob", "tenant":"other", "role":"invoke"}],
        "httpIngress":{"formatVersion":1, "bind":"127.0.0.1:0", "transport":{"mode":"loopback"}, "authentication":{"mode":"bearer"}, "limits":{}}
    })
}
#[test]
fn http_configuration_is_opt_in_closed_and_rejects_unsafe_limits_or_identity() {
    let original = config();
    let settings = serde_json::from_value::<NodeConfig>(original.clone())
        .unwrap()
        .derive()
        .unwrap();
    assert!(settings.http.is_some());
    assert_eq!(
        settings.wasmtime.value_codec_limits.max_input_bytes,
        2 * 1024 * 1024
    );
    assert_eq!(
        settings.wasmtime.value_codec_limits.max_string_bytes,
        512 * 1024
    );
    for (pointer, value) in [
        ("/httpIngress", Value::Null),
        ("/httpIngress/formatVersion", json!(2)),
        ("/httpIngress/bind", json!("0.0.0.0:8080")),
        (
            "/httpIngress/transport",
            json!({"mode":"trusted-proxy", "peers":[]}),
        ),
        (
            "/httpIngress/transport",
            json!({"mode":"trusted-proxy", "peers":["0.0.0.0"]}),
        ),
        ("/httpIngress/authentication", json!({"mode":"anonymous"})),
        ("/httpIngress/limits", json!({"maximumConnections":0})),
        ("/httpIngress/limits", json!({"maximumConnections":129})),
        ("/httpIngress/limits", json!({"maximumExchanges":65})),
        ("/httpIngress/limits", json!({"maximumBufferBytes":1024})),
        ("/httpIngress/limits", json!({"headerTimeoutMillis":0})),
        ("/httpIngress/limits", json!({"unknown":1})),
        ("/limits/maximumPayloadBytes", json!(1_048_576)),
    ] {
        let mut changed = original.clone();
        *changed
            .pointer_mut(pointer)
            .unwrap_or_else(|| panic!("fixture pointer {pointer}")) = value;
        let rejected =
            serde_json::from_value::<NodeConfig>(changed).map_or(true, |c| c.derive().is_err());
        assert!(rejected, "{pointer}");
    }
    let mut disabled = original;
    disabled.as_object_mut().unwrap().remove("httpIngress");
    disabled["limits"]["maximumPayloadBytes"] = json!(1_048_576);
    let disabled = serde_json::from_value::<NodeConfig>(disabled)
        .unwrap()
        .derive()
        .unwrap();
    assert!(disabled.http.is_none());
    let profile = |settings: &crate::config::NodeSettings| {
        latent_wasmtime::ValidatedAotProfile::from_config(
            &settings.wasmtime,
            latent_wasmtime::AotCompilerLimits::default(),
        )
        .unwrap()
    };
    assert_ne!(profile(&disabled).digest(), profile(&settings).digest());
}
#[test]
fn public_origin_is_an_explicit_tenant_principal_without_administrator_claims() {
    let mut config = config();
    config["httpIngress"]["authentication"] = json!({"mode":"public-origins", "origins":[{"authority":"web.example.test", "subject":"public-web", "tenant":"tests"}]});
    let settings = serde_json::from_value::<NodeConfig>(config.clone())
        .unwrap()
        .derive()
        .unwrap();
    let crate::config::http::Authentication::PublicOrigins(origins) =
        &settings.http.as_ref().unwrap().authentication
    else {
        panic!()
    };
    let principal = &origins[0].1;
    assert_eq!(principal.kind, latent_core::PrincipalKind::Trigger);
    assert!(principal.claims.is_empty());
    assert!(
        settings.admission.tenants[&latent_core::TenantId("tests".into())]
            .allowed_subjects
            .contains("public-web")
    );
    config["httpIngress"]["authentication"]["origins"][0]["tenant"] = json!("missing");
    assert!(serde_json::from_value::<NodeConfig>(config)
        .unwrap()
        .derive()
        .is_err());
}
