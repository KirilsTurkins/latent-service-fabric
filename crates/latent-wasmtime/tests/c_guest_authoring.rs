//! Fresh public-only fixture for the authenticated, separate-process C guide.
#![cfg(target_os = "linux")]
// These shared fixture modules also serve the complete guest runtime suite.
#[allow(dead_code)]
#[path = "guest_sdk/package.rs"]
mod package;
#[allow(dead_code)]
#[path = "generic_backend/support.rs"]
mod support;

use latent_artifacts::ReleaseEvidenceUpload;
use latent_signing::{C_GUEST_BUILD_TYPE, ProvenanceLimits, decode_build_observation};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{io::Read, path::Path};

fn read(path: &Path, maximum: usize) -> Vec<u8> {
    assert!(!path.symlink_metadata().unwrap().file_type().is_symlink());
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .unwrap()
        .take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .unwrap();
    assert!(bytes.len() <= maximum);
    bytes
}
fn digest(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}
fn write(path: &Path, value: &Value) {
    std::fs::write(path, serde_json::to_vec_pretty(value).unwrap()).unwrap();
}

#[test]
#[ignore = "Requires actual C authoring builds and an explicit new fixture output"]
fn export_c_authoring_fixture() {
    let inputs = std::env::var_os("LSF_C_AUTHORING_BUILD_ROOT").expect("actual C build root");
    let output = std::env::var_os("LSF_C_AUTHORING_FIXTURE_ROOT").expect("new public fixture root");
    let inputs = Path::new(&inputs);
    let output = Path::new(&output);
    std::fs::create_dir(output).unwrap();
    let signers = package::Signers::new(C_GUEST_BUILD_TYPE);
    std::fs::write(output.join("policy.json"), &signers.policy_document).unwrap();
    let mut components = serde_json::Map::new();
    for name in ["greeting", "word-count", "shipping"] {
        let build = inputs.join(format!("build-{name}"));
        let marker: Value =
            serde_json::from_slice(&read(&build.join("BUILD-COMPLETE.json"), 65536)).unwrap();
        assert_eq!(marker["formatVersion"], 1);
        let bytes = read(&build.join("build-observation.json"), 65536);
        assert_eq!(marker["observationDigest"], digest(&bytes));
        let observation = decode_build_observation(&bytes, ProvenanceLimits::default()).unwrap();
        assert_eq!(observation.build_type, C_GUEST_BUILD_TYPE);
        assert_eq!(
            observation.source.snapshot_digest,
            digest(&read(&build.join("source-inputs.json"), 1_048_576))
        );
        let bundle = package::bundle(&build.join("package-inputs"));
        assert_eq!(
            bundle.layout().component_release().unwrap().0,
            observation.component_digest
        );
        let upload = signers.upload(&bundle, &observation);
        let evidence = ReleaseEvidenceUpload {
            signatures: upload.signatures,
            provenance: upload.provenance,
            sboms: upload.sboms,
        };
        let directory = output.join(name);
        std::fs::create_dir(&directory).unwrap();
        latent_packaging::write_package_directory(&bundle, &directory.join("package")).unwrap();
        latent_packaging::write_package_evidence(
            bundle.layout().digest(),
            &evidence,
            &directory.join("evidence"),
            16 * 1024 * 1024,
        )
        .unwrap();
        let mut deployment: Value = serde_json::from_slice(include_bytes!(
            "../../../examples/echo-contract/deployment.json"
        ))
        .unwrap();
        deployment["metadata"] = json!({"name": name, "tenant": "tests"});
        deployment["spec"]["service"] = json!(name);
        deployment["spec"]["release"] = json!(observation.component_digest);
        deployment["spec"]["grants"] = json!([]);
        deployment["spec"]["resources"]["cpuFuel"] = json!(100_000_000);
        deployment["spec"]["resources"]["memoryBytes"] = json!(4_194_304);
        deployment["spec"]["resources"]["logBytes"] = json!(0);
        write(&directory.join("deployment.json"), &deployment);
        components.insert(
            name.into(),
            json!({
                "componentDigest": observation.component_digest,
                "componentBytes": observation.component_size,
                "sourceSnapshotDigest": observation.source.snapshot_digest,
                "observationDigest": digest(&bytes)
            }),
        );
    }
    write(
        &output.join("fixture.json"),
        &json!({"formatVersion": 1, "tenant": "tests",
            "components": components,
            "provenance": "actual bounded C compiler observations; fresh ephemeral test signing keys"}),
    );
}
