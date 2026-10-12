use serde_json::{json, Value};

fn document() -> Value {
    let mut value = super::document();
    value["providers"].as_object_mut().unwrap().remove("blob");
    value["providers"]["httpStreaming"] = json!({
        "identity": {"id":"stream-http","tenant":"examples","service":"http-stream-host","epoch":1},
        "configuration": {"formatVersion":1,
            "destinations":[{"origin":{"scheme":"http","host":"127.0.0.1","port":32123},
                "addresses":{"networks":["127.0.0.1/32"],"specialAddresses":["127.0.0.1"]},
                "resolution":{"kind":"static","addresses":["127.0.0.1"]},
                "allowedRequestHeaders":[],"redirectDestinations":[]}],
            "limits":{"maximumRequestBodyBytes":4096,"maximumResponseBodyBytes":4096,
                "maximumEncodedResponseBytes":8192,"maximumHeaderBytes":1024,"maximumHeaders":8,"maximumRedirects":0},
            "extraRoots":[],"publicRoots":false},
        "limits":{"maximumInputBytes":4096,"maximumOutputBytes":4096,
            "maximumChunkBytes":1024,"maximumOutstandingChunks":2}
    });
    value["providers"]["bindings"][0]["contract"] = "latent:http/streaming@0.3.0".into();
    value["providers"]["bindings"][0]["providerService"] = "http-stream-host".into();
    value
}

#[test]
fn bindings_match_only_the_installed_typed_http_contract() {
    let original = document();
    let config = super::super::input::decode(&serde_json::to_vec(&original).unwrap()).unwrap();
    assert_eq!(
        config
            .providers
            .as_ref()
            .unwrap()
            .definitions()
            .unwrap()
            .len(),
        1
    );
    for (field, changed) in [
        ("contract", "latent:http/client@0.2.0"),
        ("contract", "latent:network/streams@0.1.0"),
        ("providerService", "another-host"),
        ("tenant", "foreign"),
    ] {
        let mut value = original.clone();
        value["providers"]["bindings"][0][field] = changed.into();
        let config = super::super::input::decode(&serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(config.providers.as_ref().unwrap().definitions().is_err());
    }
    let mut missing = original;
    missing["providers"]
        .as_object_mut()
        .unwrap()
        .remove("httpStreaming");
    let config = super::super::input::decode(&serde_json::to_vec(&missing).unwrap()).unwrap();
    assert!(config.providers.as_ref().unwrap().definitions().is_err());
}

#[test]
fn input_rejects_null_unknown_and_inline_authority() {
    let original = document();
    for (pointer, changed) in [
        ("/providers/httpStreaming", Value::Null),
        ("/providers/httpStreaming/limits", Value::Null),
        ("/providers/httpStreaming/credentialDirectory", Value::Null),
        ("/providers/httpStreaming/profile", json!("future-profile")),
        (
            "/providers/httpStreaming/authorization",
            json!("DO-NOT-ECHO"),
        ),
        (
            "/providers/httpStreaming/limits/maximumChunkBytes",
            json!(true),
        ),
        (
            "/providers/httpStreaming/limits/memoryBytes",
            json!(18_446_744_073_709_551_615_u64),
        ),
    ] {
        let mut value = original.clone();
        let (parent, field) = pointer.rsplit_once('/').unwrap();
        value
            .pointer_mut(parent)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert(field.into(), changed);
        let error = super::super::input::decode(&serde_json::to_vec(&value).unwrap())
            .err()
            .unwrap();
        assert!(!error.message.contains("DO-NOT-ECHO"));
    }
    let mut missing = original;
    missing["providers"]["httpStreaming"]
        .as_object_mut()
        .unwrap()
        .remove("limits");
    assert!(super::super::input::decode(&serde_json::to_vec(&missing).unwrap()).is_err());
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
#[test]
fn protected_configuration_rejects_limits_scope_and_paths_before_side_effects() {
    use std::os::unix::fs::PermissionsExt;

    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let path = directory.path().join("node.json");
    let mut original = document();
    original["providers"]["httpStreaming"]["credentialDirectory"] = "not-opened".into();
    original["providers"]["httpStreaming"]["credentials"] = json!([
        {"reference":"test","file":"authorization","destination":0,"header":"authorization"}]);
    std::fs::write(&path, serde_json::to_vec(&original).unwrap()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    let settings = super::super::NodeConfig::load(&path)
        .unwrap()
        .derive()
        .unwrap();
    let http = settings
        .providers
        .as_ref()
        .unwrap()
        .http_streaming
        .as_ref()
        .unwrap();
    assert_eq!(http.limits.maximum_chunk_bytes, 1024);
    assert_eq!(http.limits.maximum_outstanding_chunks, 2);
    assert_eq!(
        http.credential_directory.as_ref().unwrap(),
        &directory.path().join("not-opened")
    );
    assert!(!directory.path().join("not-opened").exists());
    assert!(!directory.path().join("data").exists());
    assert!(
        super::super::input::decode(&serde_json::to_vec(&original).unwrap())
            .unwrap()
            .derive()
            .is_err()
    );
    for (pointer, changed) in [
        (
            "/providers/httpStreaming/limits/maximumInputBytes",
            json!(66_060_289_u64),
        ),
        (
            "/providers/httpStreaming/limits/maximumOutputBytes",
            json!(0),
        ),
        (
            "/providers/httpStreaming/limits/maximumChunkBytes",
            json!(65537),
        ),
        (
            "/providers/httpStreaming/limits/maximumOutstandingChunks",
            json!(33),
        ),
        (
            "/providers/httpStreaming/credentialDirectory",
            json!("../escape"),
        ),
        (
            "/providers/httpStreaming/credentials/0/file",
            json!("../escape"),
        ),
        (
            "/providers/httpStreaming/credentials/0/destination",
            json!(1),
        ),
        ("/providers/bindings/0/tenant", json!("foreign")),
    ] {
        let mut value = original.clone();
        *value.pointer_mut(pointer).unwrap() = changed;
        std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
        assert!(super::super::NodeConfig::load(&path)
            .unwrap()
            .derive()
            .is_err());
        assert!(!directory.path().join("not-opened").exists());
    }
    let mut duplicate = original;
    duplicate["providers"]["blob"] = json!({"identity": {
        "id":"stream-http","tenant":"examples","service":"blob-host","epoch":1}, "namespace":"workflow"});
    std::fs::write(&path, serde_json::to_vec(&duplicate).unwrap()).unwrap();
    assert!(super::super::NodeConfig::load(&path)
        .unwrap()
        .derive()
        .is_err());
}
