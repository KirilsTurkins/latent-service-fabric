#![cfg(target_os = "linux")]

#[path = "phase3_angular_fixture/mod.rs"]
mod signing;

use latent_artifacts::package::artifact_blob_digest;
use latent_packaging::{read_package_directory, PackagingLimits};
use latent_signing::{decode_web_build_observation, ProvenanceLimits, ANGULAR_BUILD_TYPE};
use serde_json::json;
use std::{fs, io::Write, os::unix::fs::PermissionsExt, path::Path};

fn write(path: &Path, bytes: &[u8]) {
    assert!(bytes.len() <= 256 * 1024);
    let mut output = fs::OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .unwrap();
    output
        .set_permissions(fs::Permissions::from_mode(0o600))
        .unwrap();
    output.write_all(bytes).unwrap();
}

#[test]
#[ignore = "requires two actual maintained Angular builds and a fresh private fixture root"]
fn export_actual_angular_reference_fixtures() {
    let builds = std::env::var_os("LSF_ANGULAR_REFERENCE_BUILDS").unwrap();
    let builds = Path::new(&builds);
    let root = std::env::var_os("LSF_ANGULAR_REFERENCE_FIXTURE_ROOT").unwrap();
    let root = Path::new(&root);
    assert!(builds.is_absolute() && root.is_absolute() && !root.exists());
    fs::create_dir(root).unwrap();
    fs::set_permissions(root, fs::Permissions::from_mode(0o700)).unwrap();
    let mut signers = None;
    let mut records = Vec::new();
    for name in ["green", "blue"] {
        let build = builds.join(name);
        let observation_bytes = fs::read(build.join("observation.json")).unwrap();
        assert!(observation_bytes.len() <= 64 * 1024);
        let observation =
            decode_web_build_observation(&observation_bytes, ProvenanceLimits::default()).unwrap();
        assert_eq!(observation.build_type, ANGULAR_BUILD_TYPE);
        assert_eq!(observation.reproducibility, "not-checked");
        assert!(!observation.hermetic);
        let signers = signers.get_or_insert_with(|| {
            signing::Signers::new(observation.finished_at, &observation.source.repository)
        });
        let bundle =
            read_package_directory(&build.join("package"), PackagingLimits::default()).unwrap();
        let outputs = latent_artifacts::web::web_build_outputs(bundle.layout()).unwrap();
        assert_eq!(outputs.digest().to_string(), observation.outputs_digest);
        assert_eq!(outputs.count(), observation.outputs_count);
        assert_eq!(outputs.bytes(), observation.outputs_bytes);
        let layout =
            latent_packaging::inspect_web_bundle(&bundle, PackagingLimits::default().semantics)
                .unwrap();
        let renderer = layout.manifest().renderer.as_ref().unwrap();
        assert_eq!(
            renderer.profile,
            latent_manifest::RendererProfile::AngularSsrComponentV1
        );
        assert_eq!(
            renderer.backend_profile,
            latent_artifacts::web::WebBackendProfile::ScopedHttpGetV1
        );
        let directory = root.join(name);
        fs::create_dir(&directory).unwrap();
        latent_packaging::write_package_directory(&bundle, &directory.join("package")).unwrap();
        write(&directory.join("observation.json"), &observation_bytes);
        for evidence_name in ["evidence", "no-publisher-evidence", "no-builder-evidence"] {
            let mut evidence = signers.evidence(&bundle, &observation, 7200);
            if evidence_name == "evidence" {
                signers
                    .verify(&bundle, signers.evidence(&bundle, &observation, 7200))
                    .unwrap();
            } else if evidence_name == "no-publisher-evidence" {
                evidence.signatures.clear();
            } else {
                evidence.provenance.clear();
            }
            latent_packaging::write_package_evidence(
                bundle.layout().digest(),
                &evidence,
                &directory.join(evidence_name),
                1024 * 1024,
            )
            .unwrap();
        }
        records.push(json!({"name": name, "version": format!("reference-{name}"), "packageDigest": layout.package().to_string(),
            "componentDigest": renderer.digest, "rendererBytes": renderer.size.to_string(),
            "assetsDigest": layout.assets_digest().to_string(), "manifestDigest": layout.manifest_digest().to_string(),
            "service": layout.name(), "assets": layout.manifest().assets, "routes": layout.manifest().routes,
            "sourceSnapshotDigest": observation.source.snapshot_digest,
            "buildObservationDigest": artifact_blob_digest(&observation_bytes).to_string()}));
    }
    for field in [
        "packageDigest",
        "componentDigest",
        "assetsDigest",
        "sourceSnapshotDigest",
    ] {
        assert_ne!(records[0][field], records[1][field]);
    }
    assert_eq!(records[0]["routes"], records[1]["routes"]);
    write(&root.join("policy.json"), &signers.unwrap().policy_document);
    write(&root.join("fixture.json"), &serde_json::to_vec(&json!({
        "schemaVersion": "latent.angular.reference.fixture.v1", "tenant": "tests", "fixtures": records,
        "actualAngularBuilds": true, "reproducibility": "not-checked", "dependencyCompleteness": "declared-inputs-incomplete",
    })).unwrap());
}
