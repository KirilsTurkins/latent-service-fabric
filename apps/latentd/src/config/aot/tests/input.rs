use super::*;

#[test]
fn omission_preserves_default_and_present_null_or_open_shapes_reject() {
    let directory = TempDir::new().unwrap();
    let mut value = document(directory.path());
    value.as_object_mut().unwrap().remove("isolatedAot");
    let config: NodeConfig = serde_json::from_value(value).unwrap();
    assert!(config.derive().unwrap().isolated_aot.is_none());
    for change in [json!(null), json!({}), json!({"keyBytes":[0,1]})] {
        let mut value = document(directory.path());
        value["isolatedAot"] = change;
        assert!(serde_json::from_value::<NodeConfig>(value).is_err());
    }
    for (name, value) in [
        ("process", json!(null)),
        ("cache", json!({"extra":1})),
        ("images", json!({"maximumImages":1.5})),
        ("extra", json!(true)),
    ] {
        let mut input = document(directory.path());
        input["isolatedAot"][name] = value;
        assert!(serde_json::from_value::<NodeConfig>(input).is_err());
    }
}

#[test]
fn duplicate_members_and_oversized_documents_fail_before_derivation() {
    let directory = TempDir::new().unwrap();
    let value = document(directory.path());
    let member = serde_json::to_string(&value["isolatedAot"]).unwrap();
    let text = serde_json::to_string(&value).unwrap();
    let duplicate = text.replacen(
        "\"isolatedAot\":",
        &format!("\"isolatedAot\":{member},\"isolatedAot\":"),
        1,
    );
    assert!(crate::config::input::decode(duplicate.as_bytes()).is_err());
    let duplicate = member.replacen(
        "\"compilerDigest\":",
        "\"process\":{},\"process\":{},\"compilerDigest\":",
        1,
    );
    assert!(serde_json::from_str::<IsolatedAotConfig>(&duplicate).is_err());
    assert!(crate::config::input::decode(&vec![b' '; 65_537]).is_err());
}

#[test]
fn relative_key_and_future_roots_anchor_without_creating_storage() {
    let directory = TempDir::new().unwrap();
    let mut value = document(directory.path());
    value["dataDirectory"] = json!("future-data");
    value["isolatedAot"]["keyFile"] = json!("private/key");
    value["isolatedAot"]["blobRoot"] = json!("future-cache/blobs");
    value["isolatedAot"]["receiptRoot"] = json!("future-cache/receipts");
    let path = directory.path().join("node.json");
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    let config = NodeConfig::load(&path).unwrap();
    let canonical = directory.path().canonicalize().unwrap();
    let aot = config.isolated_aot.unwrap();
    assert_eq!(aot.key_file, canonical.join("private/key"));
    assert_eq!(aot.blob_root, canonical.join("future-cache/blobs"));
    assert_eq!(aot.receipt_root, canonical.join("future-cache/receipts"));
    assert!(!canonical.join("future-data").exists());
    assert!(!canonical.join("future-cache").exists());
    assert!(!canonical.join("private").exists());
    value["isolatedAot"]["compilerExecutable"] = json!("compiler-on-path");
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    assert!(NodeConfig::load(&path).is_err());
}

#[test]
fn path_aliases_and_key_root_overlap_fail_without_storage_creation() {
    let directory = TempDir::new().unwrap();
    std::fs::create_dir(directory.path().join("private")).unwrap();
    let config = parsed(directory.path());
    let aot = config.isolated_aot.as_ref().unwrap();
    let roots = paths::Roots::check(aot, &config.data_directory).unwrap();
    assert!(!roots.blobs.exists());
    assert!(!roots.receipts.exists());
    for field in ["blobRoot", "receiptRoot", "keyFile"] {
        let mut value = document(directory.path());
        value["isolatedAot"][field] = json!(directory.path().join("data"));
        let config: NodeConfig = serde_json::from_value(value).unwrap();
        assert!(paths::Roots::check(
            config.isolated_aot.as_ref().unwrap(),
            &config.data_directory
        )
        .is_err());
    }
    let mut aot = aot.clone();
    aot.receipt_root = aot.blob_root.join("nested");
    assert!(paths::Roots::check(&aot, &config.data_directory).is_err());
    aot.receipt_root = directory.path().join("cache/../blobs");
    assert!(paths::Roots::check(&aot, &config.data_directory).is_err());
}

#[test]
fn compiler_digest_spelling_and_bounded_path_copies_are_exact() {
    let mut input = String::with_capacity(1024 * 1024);
    input.push_str("sha256:");
    input.push_str(&"ab".repeat(32));
    assert_eq!(digest(&input).unwrap(), [0xab; 32]);
    for input in [
        "sha256:a".to_owned(),
        format!("sha256:{}", "AB".repeat(32)),
        format!("sha512:{}", "ab".repeat(32)),
        "a".repeat(4097),
    ] {
        assert!(digest(&input).is_err());
    }
    let directory = TempDir::new().unwrap();
    let mut path = std::path::PathBuf::with_capacity(1024 * 1024);
    path.push(directory.path());
    path.push("cache");
    let mut config = parsed(directory.path());
    std::fs::create_dir(directory.path().join("private")).unwrap();
    config.isolated_aot.as_mut().unwrap().blob_root = path;
    config.isolated_aot.as_mut().unwrap().receipt_root = directory.path().join("receipts");
    let roots = paths::Roots::check(
        config.isolated_aot.as_ref().unwrap(),
        &config.data_directory,
    )
    .unwrap();
    assert!(roots.blobs.capacity() < 8192);
    assert!(paths::check(Path::new(&"x".repeat(4097)), false).is_err());
    assert!(paths::check(Path::new("with\nnewline"), false).is_err());
}

#[cfg(not(all(target_os = "linux", target_arch = "x86_64")))]
#[test]
fn unsupported_aot_fails_without_opening_any_configured_root() {
    let directory = TempDir::new().unwrap();
    let error = parsed(directory.path()).derive().err().unwrap();
    assert_eq!(error.code, PlatformErrorCode::IncompatibleContract);
    assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 0);
}
