use super::definition::{normalize, PathMatch};
use latent_ingress::http::{CanonicalTarget, Method, Scheme};
use latent_manifest::{__serde_json as json, JsonManifestCodec, ManifestCodec, TriggerManifest};

fn manifest() -> TriggerManifest {
    let value = json::json!({
        "apiVersion":"latent.dev/v1alpha1", "kind":"HttpTrigger",
        "metadata":{"name":"browser", "tenant":"tenant-a"},
        "spec":{
            "target":{
                "service":"tenant-a/browser", "contract":"latent:web/application@0.1.0", "function":"handle",
                "route":"web-deployment", "publication":format!("publication:sha256:{}", "a".repeat(64)),
                "revision":format!("revision-v1:sha256:{}", "b".repeat(64)), "deploymentGeneration":1
            },
            "configuration":{"profile":"buffered-v1", "scheme":"https", "host":"EXAMPLE.TEST:443",
                "path":"/api/%7euser", "pathMatch":"prefix", "method":"GET"}
        }
    });
    JsonManifestCodec::default()
        .decode_trigger(&json::to_vec(&value).unwrap())
        .unwrap()
}

#[test]
fn direct_transaction_routes_roundtrip_with_fixed_scope_and_reject_method_widening() {
    let mut value = manifest();
    let target = value.target.application_mut().unwrap();
    target.contract.0 = "examples:transactions/api@1.0.0".into();
    target.function = "update".into();
    value.configuration.extend([
        ("profile".into(), json::json!("transaction-http-v1")),
        ("method".into(), json::json!("POST")),
        ("transactionMode".into(), json::json!("command")),
        ("namespace".into(), json::json!("orders")),
        ("incarnation".into(), json::json!("1")),
        (
            "stateSchema".into(),
            json::json!(format!("sha256:{}", "1".repeat(64))),
        ),
        (
            "companionDigest".into(),
            json::json!(format!("sha256:{}", "2".repeat(64))),
        ),
        ("stateBinding".into(), json::json!("state")),
        ("resultPolicy".into(), json::json!("owner")),
    ]);
    let (value, _) = normalize(value).unwrap();
    let bytes = JsonManifestCodec::default().encode_trigger(&value).unwrap();
    assert_eq!(
        JsonManifestCodec::default().decode_trigger(&bytes).unwrap(),
        value
    );
    for method in ["GET", "HEAD"] {
        let mut changed = value.clone();
        changed
            .configuration
            .insert("method".into(), json::json!(method));
        assert!(normalize(changed).is_err());
    }
    for mode in ["query", "result"] {
        let mut changed = value.clone();
        changed
            .configuration
            .insert("transactionMode".into(), json::json!(mode));
        assert!(normalize(changed).is_err());
    }
}

#[test]
fn exact_publication_selector_survives_manifest_codec_and_canonical_matching() {
    let (value, matcher) = normalize(manifest()).unwrap();
    let bytes = JsonManifestCodec::default().encode_trigger(&value).unwrap();
    assert_eq!(
        JsonManifestCodec::default().decode_trigger(&bytes).unwrap(),
        value
    );
    assert_eq!(value.configuration["host"], "example.test");
    assert_eq!(value.configuration["path"], "/api/~user");
    assert_eq!(
        value
            .target
            .application()
            .and_then(|target| target.deployment_generation),
        Some(1)
    );
    assert_eq!(matcher.path_match, PathMatch::Prefix);
    for (path, expected) in [
        ("/api/~user", true),
        ("/api/~user/child?query=1", true),
        ("/api/~users", false),
    ] {
        let target = CanonicalTarget::parse(Scheme::Https, "example.test", path).unwrap();
        assert_eq!(matcher.matches(&target, Method::Get), expected);
        assert!(!matcher.matches(&target, Method::Head));
    }
    let mut exact = value;
    exact
        .configuration
        .insert("pathMatch".into(), json::json!("exact"));
    let (_, exact) = normalize(exact).unwrap();
    assert!(exact.precedence() > matcher.precedence());
}

#[test]
fn unsupported_contracts_ambiguous_paths_unpinned_targets_and_unbounded_native_storage_deny() {
    let original = manifest();
    for (key, replacement) in [
        ("profile", json::json!("future")),
        ("method", json::json!("get")),
        ("pathMatch", json::json!("regex")),
        ("path", json::json!("/api?route=other")),
        ("path", json::json!("/api/")),
        ("path", json::json!("/%2fother")),
        ("path", json::json!(["/api"])),
        ("extra", json::json!("ignored")),
    ] {
        let mut value = original.clone();
        value.configuration.insert(key.into(), replacement);
        assert!(normalize(value).is_err(), "{key}");
    }
    let mut value = original.clone();
    value.target.application_mut().unwrap().publication = None;
    assert!(normalize(value).is_err());
    let mut value = original.clone();
    value.target.application_mut().unwrap().revision = None;
    assert!(normalize(value).is_err());
    let mut value = original.clone();
    value
        .target
        .application_mut()
        .unwrap()
        .deployment_generation = Some(0);
    assert!(normalize(value).is_err());
    let mut value = original.clone();
    value.target.application_mut().unwrap().contract.0 = "example:echo/api@0.1.0".into();
    assert!(normalize(value).is_err());
    let mut value = original.clone();
    value.target.application_mut().unwrap().route = Some("default".into());
    assert!(normalize(value).is_err());
    let mut value = original;
    let mut retained = String::with_capacity(65_536);
    retained.push_str("example.test");
    value
        .configuration
        .insert("host".into(), json::Value::String(retained));
    assert!(normalize(value).is_err());
}
