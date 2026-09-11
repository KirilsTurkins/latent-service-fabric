use latent_artifacts::package::{
    artifact_blob_digest, decode_config, decode_manifest, decode_referrer, encode_config,
    encode_manifest, encode_referrer, inspect_package, package_digest, verify_layer_bytes,
    EvidenceKind, PackageKind, PackageLimits,
};
use latent_core::PlatformErrorCode;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

fn wire(value: &Value) -> Vec<u8> {
    serde_json::to_vec(value).unwrap()
}

fn config(kind: PackageKind) -> Value {
    let roles = match kind {
        PackageKind::Capsule => vec![
            ("a.wasm", "component", "application/wasm"),
            (
                "b.json",
                "capsule-manifest",
                "application/vnd.latent.capsule.manifest.v1+json",
            ),
            (
                "c.json",
                "contracts",
                "application/vnd.latent.contracts.v1+json",
            ),
            (
                "d.json",
                "wit-lock",
                "application/vnd.latent.wit-lock.v1+json",
            ),
        ],
        PackageKind::BrowserAssets => vec![("index.html", "asset", "text/html")],
        PackageKind::SsrPackage => vec![("render.js", "renderer", "text/javascript")],
    };
    let layers: Vec<Value> = roles
        .iter()
        .map(|(path, role, media_type)| {
            json!({
                "path": path, "role": role, "mediaType": media_type,
                "digest": artifact_blob_digest(b"x").as_str(), "size": 1,
            })
        })
        .collect();
    let mut config = json!({
        "formatVersion": 1, "kind": kind, "name": "example", "version": "1.2.3-beta.1+build",
        "entrypoint": roles[0].0, "layers": layers, "annotations": {},
    });
    if kind == PackageKind::Capsule {
        config["componentDigest"] = json!(artifact_blob_digest(b"x").as_str());
    }
    config
}

fn manifest(config: &Value) -> Value {
    let layers: Vec<_> = config["layers"].as_array().unwrap().iter().map(|layer| json!({
        "mediaType": layer["mediaType"], "digest": layer["digest"], "size": layer["size"],
        "annotations": {"org.opencontainers.image.title": layer["path"], "dev.latent.layer.role": layer["role"]},
    })).collect();
    let bytes = wire(config);
    json!({
        "schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": format!("application/vnd.latent.{}.v1", config["kind"].as_str().unwrap()),
        "config": {"mediaType": "application/vnd.latent.package.config.v1+json",
            "digest": artifact_blob_digest(&bytes).as_str(), "size": bytes.len()},
        "layers": layers, "annotations": {},
    })
}

#[test]
fn all_three_kinds_preserve_distinct_raw_and_component_identities() {
    for kind in [
        PackageKind::Capsule,
        PackageKind::BrowserAssets,
        PackageKind::SsrPackage,
    ] {
        let config = config(kind);
        let manifest = manifest(&config);
        let bytes = wire(&manifest);
        let layout = inspect_package(&bytes, &wire(&config), PackageLimits::default()).unwrap();
        assert_eq!(layout.config().kind, kind);
        assert_eq!(
            layout.digest().as_str(),
            format!("sha256:{:x}", Sha256::digest(&bytes))
        );
        assert_ne!(
            layout.digest().as_str(),
            artifact_blob_digest(b"x").as_str()
        );
        if kind == PackageKind::Capsule {
            assert_eq!(
                layout.component_release().unwrap().0,
                artifact_blob_digest(b"x").as_str()
            );
        } else {
            assert_eq!(layout.component_release(), None);
        }
        for layer in &layout.config().layers {
            verify_layer_bytes(layer, b"x", PackageLimits::default()).unwrap();
            assert_eq!(
                verify_layer_bytes(layer, b"y", PackageLimits::default())
                    .unwrap_err()
                    .code,
                PlatformErrorCode::CorruptArtifact
            );
            assert!(verify_layer_bytes(layer, b"", PackageLimits::default()).is_err());
        }
    }
}

#[test]
fn noncanonical_received_json_keeps_its_exact_identity() {
    let config = config(PackageKind::BrowserAssets);
    let manifest = manifest(&config);
    let compact = wire(&manifest);
    let pretty = serde_json::to_vec_pretty(&manifest).unwrap();
    let first = inspect_package(&compact, &wire(&config), PackageLimits::default()).unwrap();
    let second = inspect_package(&pretty, &wire(&config), PackageLimits::default()).unwrap();
    assert_ne!(first.digest(), second.digest());
    assert_eq!(first.manifest(), second.manifest());
    assert_eq!(second.digest(), &package_digest(&pretty));
    let canonical = encode_manifest(first.manifest(), PackageLimits::default()).unwrap();
    assert_eq!(
        canonical,
        encode_manifest(second.manifest(), PackageLimits::default()).unwrap()
    );
    assert!(canonical.starts_with(br#"{"schemaVersion":2,"mediaType":"#));
    assert!(!canonical.ends_with(b"\n"));
    assert_eq!(
        decode_manifest(&canonical, PackageLimits::default()).unwrap(),
        *first.manifest()
    );
    // Equal JSON values with distinct raw config bytes must not substitute for the descriptor.
    assert_eq!(
        inspect_package(
            &compact,
            &serde_json::to_vec_pretty(&config).unwrap(),
            PackageLimits::default()
        )
        .unwrap_err()
        .code,
        PlatformErrorCode::CorruptArtifact
    );
}

#[test]
fn associations_require_more_than_each_document_independently_being_valid() {
    let config = config(PackageKind::BrowserAssets);
    for field in ["digest", "size", "mediaType", "path"] {
        let mut manifest = manifest(&config);
        match field {
            "digest" => manifest["layers"][0][field] = json!(artifact_blob_digest(b"z").as_str()),
            "size" => manifest["layers"][0][field] = json!(2),
            "mediaType" => manifest["layers"][0][field] = json!("text/plain"),
            _ => {
                manifest["layers"][0]["annotations"]["org.opencontainers.image.title"] =
                    json!("other.html")
            }
        }
        decode_manifest(&wire(&manifest), PackageLimits::default()).unwrap();
        assert!(
            inspect_package(&wire(&manifest), &wire(&config), PackageLimits::default()).is_err(),
            "{field}"
        );
    }
    let mut changed = config.clone();
    changed["name"] = json!("another");
    assert!(inspect_package(
        &wire(&manifest(&config)),
        &wire(&changed),
        PackageLimits::default()
    )
    .is_err());
}

#[test]
fn kinds_require_exact_roles_and_component_associations() {
    for kind in [
        PackageKind::Capsule,
        PackageKind::BrowserAssets,
        PackageKind::SsrPackage,
    ] {
        let original = config(kind);
        for other in [
            PackageKind::Capsule,
            PackageKind::BrowserAssets,
            PackageKind::SsrPackage,
        ] {
            if other != kind {
                let mut changed = original.clone();
                changed["kind"] = json!(other);
                assert!(decode_config(&wire(&changed), PackageLimits::default()).is_err());
            }
        }
    }
    let original = config(PackageKind::Capsule);
    for index in 0..4 {
        let mut changed = original.clone();
        changed["layers"].as_array_mut().unwrap().remove(index);
        assert!(decode_config(&wire(&changed), PackageLimits::default()).is_err());
    }
    let mut changed = original;
    changed["componentDigest"] = json!(artifact_blob_digest(b"other").as_str());
    assert!(decode_config(&wire(&changed), PackageLimits::default()).is_err());
    changed["componentDigest"] = Value::Null;
    assert!(decode_config(&wire(&changed), PackageLimits::default()).is_err());
}

fn evidence(kind: EvidenceKind) -> Value {
    json!({
        "schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": kind.artifact_type(),
        "config": {"mediaType": "application/vnd.oci.empty.v1+json", "digest": artifact_blob_digest(b"{}").as_str(), "size": 2},
        "layers": [{"mediaType": kind.payload_media_type(), "digest": artifact_blob_digest(b"payload").as_str(), "size": 7,
            "annotations": {"org.opencontainers.image.title": "evidence.json", "dev.latent.layer.role": "evidence"}}],
        "subject": {"mediaType": "application/vnd.oci.image.manifest.v1+json", "digest": package_digest(b"manifest").as_str(), "size": 8},
        "annotations": {},
    })
}

#[test]
fn detached_evidence_has_exact_empty_config_subject_and_payload_kind() {
    for kind in [
        EvidenceKind::Signature,
        EvidenceKind::Provenance,
        EvidenceKind::Sbom,
    ] {
        let original = evidence(kind);
        let parsed = decode_referrer(&wire(&original), PackageLimits::default()).unwrap();
        assert_eq!(
            decode_referrer(
                &encode_referrer(&parsed, PackageLimits::default()).unwrap(),
                PackageLimits::default()
            )
            .unwrap(),
            parsed
        );
        for (pointer, replacement) in [
            (
                "/config/digest",
                json!(artifact_blob_digest(b"wrong").as_str()),
            ),
            ("/config/size", json!(3)),
            ("/subject/size", json!(0)),
            ("/subject/mediaType", json!("application/wasm")),
            ("/layers/0/mediaType", json!("application/json")),
            (
                "/layers/0/annotations/dev.latent.layer.role",
                json!("asset"),
            ),
        ] {
            let mut changed = original.clone();
            *changed.pointer_mut(pointer).unwrap() = replacement;
            assert!(
                decode_referrer(&wire(&changed), PackageLimits::default()).is_err(),
                "{pointer}"
            );
        }
        assert!(decode_manifest(&wire(&original), PackageLimits::default()).is_err());
        let mut changed = original;
        changed["signature"] = json!("circular-inline-signature");
        assert!(decode_referrer(&wire(&changed), PackageLimits::default()).is_err());
    }
}

#[test]
fn descriptor_profile_forbids_optional_oci_transport_members_and_config_annotations() {
    let config = config(PackageKind::BrowserAssets);
    let original = manifest(&config);
    for extra in ["urls", "data", "platform"] {
        let mut changed = original.clone();
        changed["layers"][0][extra] = json!("unsupported");
        assert!(decode_manifest(&wire(&changed), PackageLimits::default()).is_err());
    }
    for annotations in [Value::Null, json!({}), json!({"key": "value"})] {
        let mut changed = original.clone();
        changed["config"]["annotations"] = annotations;
        assert!(decode_manifest(&wire(&changed), PackageLimits::default()).is_err());
    }
    let mut changed = original;
    changed["layers"][0]["annotations"]["extra"] = json!("value");
    assert!(decode_manifest(&wire(&changed), PackageLimits::default()).is_err());
    let model = decode_config(&wire(&config), PackageLimits::default()).unwrap();
    assert_eq!(
        decode_config(
            &encode_config(&model, PackageLimits::default()).unwrap(),
            PackageLimits::default()
        )
        .unwrap(),
        model
    );
}
