#![allow(clippy::unwrap_used)]
use latent_artifacts::{AdmissionEvidence, ReleaseEvidenceUpload};
use latent_core::PackageDigest;
use latent_packaging::{read_package_evidence, write_package_evidence};
use serde_json::json;

fn package() -> PackageDigest {
    format!("sha256:{}", "a".repeat(64)).parse().unwrap()
}
fn evidence() -> ReleaseEvidenceUpload {
    ReleaseEvidenceUpload {
        signatures: vec![AdmissionEvidence {
            manifest: b"untrusted exact referrer".to_vec(),
            configuration: b"{}".to_vec(),
            payload: b"untrusted exact signature".to_vec(),
        }],
        provenance: Vec::new(),
        sboms: Vec::new(),
    }
}

#[test]
fn detached_export_preserves_bytes_and_refuses_existing_output() {
    let root = tempfile::tempdir().unwrap();
    let out = root.path().join("evidence");
    let input = evidence();
    write_package_evidence(&package(), &input, &out, 4096).unwrap();
    let index = std::fs::read(out.join("index.json")).unwrap();
    let restored = read_package_evidence(&out, &index, &package(), 4096).unwrap();
    assert_eq!(
        restored.signatures[0].manifest,
        input.signatures[0].manifest
    );
    assert_eq!(restored.signatures[0].payload, input.signatures[0].payload);
    assert!(write_package_evidence(&package(), &input, &out, 4096).is_err());
    assert_eq!(std::fs::read(out.join("index.json")).unwrap(), index);
    assert!(read_package_evidence(&out, &index, &package(), 1).is_err());
}

#[test]
fn malformed_selection_and_subject_reject_before_file_access() {
    let root = tempfile::tempdir().unwrap();
    let mut index = json!({"formatVersion":1,"packageDigest":package().to_string(),
        "signatures":[{"manifest":"../private","configuration":"config","payload":"payload"}],
        "provenance":[],"sboms":[]});
    let read = |value: &serde_json::Value| {
        read_package_evidence(
            root.path(),
            &serde_json::to_vec(value).unwrap(),
            &package(),
            4096,
        )
    };
    assert!(read(&index).is_err());
    index["signatures"][0]["manifest"] = json!("config");
    assert!(read(&index).is_err());
    index["signatures"] = json!([]);
    assert!(read(&index).is_ok());
    index["packageDigest"] = json!(format!("sha256:{}", "b".repeat(64)));
    assert!(read(&index).is_err());
    index["packageDigest"] = json!(package().to_string());
    let encoded = serde_json::to_string(&index).unwrap();
    let duplicate = encoded.replacen(
        "\"formatVersion\":1",
        "\"formatVersion\":1,\"formatVersion\":1",
        1,
    );
    assert!(read_package_evidence(root.path(), duplicate.as_bytes(), &package(), 4096).is_err());
    index["sboms"] = serde_json::Value::Null;
    assert!(read(&index).is_err());
}

#[cfg(unix)]
#[test]
fn linked_descendant_evidence_cannot_escape_approved_root() {
    let root = tempfile::tempdir().unwrap();
    let outside = tempfile::tempdir().unwrap();
    std::fs::write(outside.path().join("manifest"), b"private").unwrap();
    std::os::unix::fs::symlink(outside.path(), root.path().join("link")).unwrap();
    let index = json!({"formatVersion":1,"packageDigest":package().to_string(),
        "signatures":[{"manifest":"link/manifest","configuration":"config","payload":"payload"}],
        "provenance":[],"sboms":[]});
    assert!(read_package_evidence(
        root.path(),
        &serde_json::to_vec(&index).unwrap(),
        &package(),
        4096
    )
    .is_err());
    assert_eq!(
        std::fs::read(outside.path().join("manifest")).unwrap(),
        b"private"
    );
}
