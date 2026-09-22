#![cfg(target_os = "linux")]

#[path = "phase3_angular_fixture/mod.rs"]
mod signing;

use latent_packaging::{read_package_directory, PackagingLimits};
use latent_signing::{decode_web_build_observation, ProvenanceLimits, WEB_ASSEMBLY_BUILD_TYPE};
use serde_json::json;
use std::{fs, os::unix::fs::PermissionsExt, path::Path};

fn write(path: &Path, bytes: &[u8]) {
    assert!(bytes.len() <= 256 * 1024);
    use std::io::Write;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .unwrap();
    file.set_permissions(fs::Permissions::from_mode(0o600))
        .unwrap();
    file.write_all(bytes).unwrap();
}

#[test]
#[ignore = "requires actual static-site reference builds and a fresh private fixture root"]
fn export_actual_static_site_fixtures() {
    let builds = std::env::var_os("LSF_STATIC_BUILDS").unwrap();
    let builds = Path::new(&builds);
    let root = std::env::var_os("LSF_STATIC_FIXTURE_ROOT").unwrap();
    let root = Path::new(&root);
    assert!(builds.is_absolute() && root.is_absolute() && !root.exists());
    fs::create_dir(root).unwrap();
    fs::set_permissions(root, fs::Permissions::from_mode(0o700)).unwrap();
    let mut signers = None;
    let mut records = Vec::new();
    for name in ["csr-a", "csr-b", "generator", "generator-docs"] {
        let build = builds.join(name);
        assert!(fs::metadata(build.join("observation.json")).unwrap().len() <= 64 * 1024);
        let bytes = fs::read(build.join("observation.json")).unwrap();
        let observation =
            decode_web_build_observation(&bytes, ProvenanceLimits::default()).unwrap();
        assert_eq!(observation.build_type, WEB_ASSEMBLY_BUILD_TYPE);
        assert_eq!(observation.reproducibility, "not-checked");
        assert!(!observation.hermetic);
        let signers = signers.get_or_insert_with(|| {
            signing::Signers::new(
                observation.finished_at,
                &observation.source.repository,
                WEB_ASSEMBLY_BUILD_TYPE,
            )
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
        assert!(layout.manifest().renderer.is_none());
        assert!(layout.manifest().static_routing.is_some());
        let directory = root.join(name);
        fs::create_dir(&directory).unwrap();
        latent_packaging::write_package_directory(&bundle, &directory.join("package")).unwrap();
        write(&directory.join("observation.json"), &bytes);
        for evidence_name in ["evidence", "no-publisher-evidence", "no-builder-evidence"] {
            let mut evidence = signers.evidence(&bundle, &observation, 7200);
            if evidence_name == "no-publisher-evidence" {
                evidence.signatures.clear();
            } else if evidence_name == "no-builder-evidence" {
                evidence.provenance.clear();
            }
            latent_packaging::write_package_evidence(
                bundle.layout().digest(),
                &evidence,
                &directory.join(evidence_name),
                1024 * 1024,
            )
            .unwrap();
            assert_eq!(
                signers.verify(&bundle, evidence).is_ok(),
                evidence_name == "evidence"
            );
        }
        records.push(json!({"name":name,"packageDigest":layout.package().to_string(),
            "assetsDigest":layout.assets_digest().to_string(),"manifestDigest":layout.manifest_digest().to_string(),
            "assets":layout.manifest().assets,"staticRouting":layout.manifest().static_routing,
            "sourceSnapshotDigest":observation.source.snapshot_digest,"renderer":false}));
    }
    assert_ne!(records[0]["packageDigest"], records[1]["packageDigest"]);
    write(&root.join("policy.json"), &signers.unwrap().policy_document);
    write(&root.join("fixture.json"), &serde_json::to_vec(&json!({
        "schemaVersion":"latent.static.reference.fixture.v1", "tenant":"tests", "fixtures":records,
        "actualCsrBuilds":true,"reproducibility":"not-checked","dependencyCompleteness":"declared-inputs-incomplete"
    })).unwrap());
}
