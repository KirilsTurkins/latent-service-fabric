#![cfg(target_os = "linux")]

use std::{fs, io::Write, os::unix::fs::PermissionsExt, path::Path};

use latent_artifacts::ReleaseEvidenceUpload;
use latent_packaging::{write_package_directory, write_package_evidence};
use serde_json::json;

#[path = "../../../crates/latent-wasmtime/tests/guest_sdk/package.rs"]
mod package;

mod support {
    pub fn config() -> latent_wasmtime::WasmtimeConfig {
        latent_wasmtime::WasmtimeConfig {
            maximum_memory_bytes: 64 * 1024 * 1024,
            maximum_fuel: 10_000_000_000,
            ..Default::default()
        }
    }
}

fn write(path: &Path, bytes: &[u8]) {
    assert!(bytes.len() <= 256 * 1024);
    let mut options = fs::OpenOptions::new();
    options.create_new(true).write(true);
    let mut file = options.open(path).unwrap();
    file.set_permissions(fs::Permissions::from_mode(0o600))
        .unwrap();
    file.write_all(bytes).unwrap();
}

#[test]
#[ignore = "requires real compiled LSF_GUEST_CAPSULES and a fresh LSF_PHASE3_WORKFLOW_FIXTURE_ROOT"]
fn export_signed_provider_workflow_fixtures() {
    let root = std::env::var_os("LSF_PHASE3_WORKFLOW_FIXTURE_ROOT").unwrap();
    let root = Path::new(&root);
    assert!(root.is_absolute() && !root.exists());
    fs::create_dir(root).unwrap();
    fs::set_permissions(root, fs::Permissions::from_mode(0o700)).unwrap();
    let signers = package::Signers::new("https://latent.dev/build/rust-guest/v1");
    write(&root.join("policy.json"), &signers.policy_document);
    let mut fixtures = Vec::new();
    for name in ["rust-http", "rust-blob", "rust-callee"] {
        let bundle = package::bundle(&package::input(name));
        let observation = package::observation(name);
        let upload = signers.upload(&bundle, &observation);
        let directory = root.join(name);
        fs::create_dir(&directory).unwrap();
        write_package_directory(&bundle, &directory.join("package")).unwrap();
        let digest = latent_artifacts::package::package_digest(bundle.manifest_bytes());
        write_package_evidence(
            &digest,
            &ReleaseEvidenceUpload {
                signatures: upload.signatures,
                provenance: upload.provenance,
                sboms: upload.sboms,
            },
            &directory.join("evidence"),
            1024 * 1024,
        )
        .unwrap();
        fixtures.push(json!({"name":name,"packageDigest":digest.to_string(),
            "componentDigest":bundle.layout().component_release().unwrap().0,
            "buildObservation":observation}));
    }
    write(
        &root.join("fixture.json"),
        &serde_json::to_vec(&json!({
            "schemaVersion":"latent.phase3.provider.fixture.v1","tenant":"tests",
            "mediaType":"application/vnd.latent.wit-values.v1+json","fixtures":fixtures,
        }))
        .unwrap(),
    );
}
