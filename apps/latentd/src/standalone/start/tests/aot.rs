use super::*;
use std::fs;
use std::os::unix::fs::PermissionsExt;

#[tokio::test]
async fn configured_aot_startup_error_never_selects_ordinary_compilation() {
    let directory = TempDir::new().unwrap();
    let private = directory.path().join("private");
    fs::create_dir(&private).unwrap();
    fs::set_permissions(&private, fs::Permissions::from_mode(0o700)).unwrap();
    let key = private.join("key");
    fs::write(&key, [0x37; 32]).unwrap();
    fs::set_permissions(&key, fs::Permissions::from_mode(0o600)).unwrap();
    let config: NodeConfig = serde_json::from_value(serde_json::json!({
        "formatVersion":1,"dataDirectory":directory.path().join("data"),
        "nodeId":"aot-startup-test","bind":"127.0.0.1:0",
        "credentials":[{"token":"test-aot-token-00000000000000000000000",
            "subject":"operator","tenant":"tests","role":"operator"}],
        "isolatedAot":{
            "compilerExecutable":directory.path().join("missing-approved-compiler"),
            "compilerDigest":format!("sha256:{}", "ab".repeat(32)),"keyFile":key,
            "blobRoot":directory.path().join("blobs"),
            "receiptRoot":directory.path().join("receipts")}
    }))
    .unwrap();
    let mut settings = config.derive().unwrap();
    let catalogs = Catalogs::open(&settings).await.unwrap();
    let error = super::super::StandaloneNode::compose(
        &mut settings,
        &catalogs,
        Arc::new(SystemActivationClock),
    )
    .err()
    .expect("a missing approved executable cannot select the legacy factory");
    assert!(matches!(
        error.code,
        PlatformErrorCode::Unavailable | PlatformErrorCode::InvalidArgument
    ));
    assert!(!error.message.contains("missing-approved-compiler"));
    assert!(settings.isolated_aot.is_none());
}
