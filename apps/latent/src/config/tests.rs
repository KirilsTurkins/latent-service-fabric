use std::fs;
use std::time::Duration;

use clap::Parser;
use serde_json::{json, Value};

use crate::args::Cli;

use super::{decode, resolve, validation};

fn profile(name: &str) -> Value {
    json!({
        "name": name,
        "endpoint": "http://127.0.0.1:50051",
        "tenant": "examples",
        "token": "private_test_token_0123456789abcdef"
    })
}

fn document() -> Value {
    json!({"formatVersion": 1, "profiles": [profile("local")]})
}

fn check(value: &Value) -> bool {
    let bytes = serde_json::to_vec(value).expect("test JSON");
    decode::document(&bytes)
        .and_then(|value| validation::document(&value))
        .is_ok()
}

#[test]
fn selected_profile_defaults_and_nonsecret_overrides_are_exact() {
    let workspace = tempfile::tempdir().expect("temporary configuration directory");
    let path = workspace.path().join("client.json");
    fs::write(&path, serde_json::to_vec(&document()).expect("test JSON")).expect("configuration");
    let cli = Cli::try_parse_from([
        "latent",
        "--config",
        path.to_str().expect("test path"),
        "node",
        "list",
    ])
    .unwrap_or_else(|_| panic!("test command"));
    let config = resolve(&cli).unwrap_or_else(|_| panic!("valid profile"));
    assert_eq!(config.tenant, "examples");
    assert_eq!(config.connect_timeout, Duration::from_secs(2));
    assert_eq!(config.rpc_timeout, Duration::from_secs(1));
    assert_eq!(config.limits.maximum_component_bytes, 16 * 1024 * 1024);
    let cli = Cli::try_parse_from([
        "latent",
        "--config",
        path.to_str().expect("test path"),
        "--endpoint",
        "http://[::1]:50052",
        "--tenant",
        "other-tenant",
        "--rpc-timeout-ms",
        "250",
        "node",
        "list",
    ])
    .unwrap_or_else(|_| panic!("test command"));
    let overridden = resolve(&cli).unwrap_or_else(|_| panic!("valid override"));
    assert_eq!(overridden.endpoint, "http://[::1]:50052");
    assert_eq!(overridden.tenant, "other-tenant");
    assert_eq!(overridden.rpc_timeout, Duration::from_millis(250));
    assert_eq!(overridden.token, config.token);
}

#[test]
fn multiple_profiles_require_explicit_or_default_selection() {
    let workspace = tempfile::tempdir().expect("temporary directory");
    let path = workspace.path().join("client.json");
    let mut value = json!({"formatVersion": 1, "profiles": [profile("alice"), profile("bob")]});
    fs::write(&path, serde_json::to_vec(&value).expect("JSON")).expect("configuration");
    let cli = Cli::try_parse_from([
        "latent",
        "--config",
        path.to_str().expect("test path"),
        "node",
        "list",
    ])
    .unwrap_or_else(|_| panic!("test command"));
    assert!(resolve(&cli).is_err());
    value["defaultProfile"] = json!("bob");
    value["profiles"][1]["tenant"] = json!("bob");
    fs::write(&path, serde_json::to_vec(&value).expect("JSON")).expect("configuration");
    let config = resolve(&cli).unwrap_or_else(|_| panic!("default profile"));
    assert_eq!(config.tenant, "bob");
    let selected = Cli::try_parse_from([
        "latent",
        "--config",
        path.to_str().expect("test path"),
        "--profile",
        "alice",
        "node",
        "list",
    ])
    .unwrap_or_else(|_| panic!("test command"));
    assert_eq!(
        resolve(&selected)
            .unwrap_or_else(|_| panic!("selected profile"))
            .tenant,
        "examples"
    );
}

#[test]
fn profiles_reject_ambient_endpoints_and_invalid_credentials() {
    for endpoint in [
        "http://localhost:50051",
        "https://127.0.0.1:50051",
        "http://127.0.0.1:0",
        "http://0.0.0.0:50051",
        "http://192.0.2.1:50051",
        "http://user@127.0.0.1:50051",
        "http://127.0.0.1:50051/",
        "http://127.0.0.1:50051?token=secret",
        "http://127.0.0.1:50051#fragment",
    ] {
        assert!(validation::endpoint(endpoint).is_err());
    }
    for (field, invalid) in [
        ("token", json!("short")),
        ("token", json!("a".repeat(257))),
        ("token", json!("private token with whitespace 0123456789")),
        ("tenant", json!("-tenant")),
        ("tenant", json!("tenant/child")),
        ("connectTimeoutMillis", json!(0)),
        ("rpcTimeoutMillis", json!(300_001)),
    ] {
        let mut value = document();
        value["profiles"][0][field] = invalid;
        assert!(!check(&value));
    }
    assert!(check(&document()));
}

#[test]
fn strict_decode_rejects_duplicate_unknown_deep_and_oversized_documents() {
    for bytes in [
        br#"{"formatVersion":1,"formatVersion":1,"profiles":[]}"#.as_slice(),
        br#"{"formatVersion":1,"profiles":[],"unknown":true}"#.as_slice(),
    ] {
        assert!(decode::document(bytes).is_err());
    }
    let mut value = document();
    value["profiles"][0]["unknown"] = json!("secret");
    assert!(!check(&value));
    let deep = format!("{}0{}", "[".repeat(17), "]".repeat(17));
    assert!(decode::document(deep.as_bytes()).is_err());
    assert!(decode::document(&vec![b' '; decode::MAXIMUM_CONFIG_BYTES + 1]).is_err());
    let mut value = document();
    value["profiles"] = json!([profile("same"), profile("same")]);
    assert!(!check(&value));
    value["profiles"] = Value::Array((0..17).map(|index| profile(&format!("p{index}"))).collect());
    assert!(!check(&value));
}

#[test]
fn profile_input_limits_are_positive_and_have_compiled_ceilings() {
    for (field, maximum) in [
        ("maximumComponentBytes", 64 * 1024 * 1024),
        ("maximumPayloadBytes", 1024 * 1024),
        ("maximumResponseBytes", 16 * 1024 * 1024),
    ] {
        for limit in [0, maximum + 1] {
            let mut value = document();
            value["profiles"][0]["limits"] = json!({field: limit});
            assert!(!check(&value));
        }
        let mut value = document();
        value["profiles"][0]["limits"] = json!({field: maximum});
        assert!(check(&value));
    }
}
