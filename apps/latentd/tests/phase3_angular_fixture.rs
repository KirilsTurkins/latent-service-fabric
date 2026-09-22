#![cfg(target_os = "linux")]

#[path = "phase3_angular_fixture/mod.rs"]
mod signing;

use latent_artifacts::package::artifact_blob_digest;
use latent_packaging::{inspect_bundle, read_package_directory, PackageBundle, PackagingLimits};
use latent_signing::{
    decode_web_build_observation, ProvenanceLimits, WebBuildObservation, ANGULAR_BUILD_TYPE,
};
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

fn variation(bundle: PackageBundle, omit_sbom: bool) -> PackageBundle {
    let mut configuration = bundle.layout().config().clone();
    let mut manifest = bundle.layout().manifest().clone();
    let mut input = bundle.into_input();
    manifest.annotations.insert(
        "latent.qualification.wrapper".into(),
        if omit_sbom {
            "missing-sbom"
        } else {
            "independent-publication"
        }
        .into(),
    );
    if omit_sbom {
        let retained =
            |path: &str| !matches!(path, "package/sbom.cdx.json" | "package/build-inputs.json");
        configuration.layers.retain(|layer| retained(&layer.path));
        input.layers.retain(|(path, _)| retained(path));
        manifest.layers.retain(|layer| {
            retained(
                &layer.annotations.as_ref().unwrap()
                    [latent_artifacts::package::LAYER_PATH_ANNOTATION],
            )
        });
        input.configuration = serde_json::to_vec(&configuration).unwrap();
        manifest.config.digest = artifact_blob_digest(&input.configuration);
        manifest.config.size = input.configuration.len() as u64;
    }
    input.manifest = serde_json::to_vec(&manifest).unwrap();
    inspect_bundle(input, PackagingLimits::default()).unwrap()
}

#[test]
#[ignore = "requires an actual maintained LSF_ANGULAR_BUILD_DIR and fresh LSF_ANGULAR_T1_FIXTURE_ROOT"]
fn export_actual_angular_t1_fixtures() {
    let build = std::env::var_os("LSF_ANGULAR_BUILD_DIR").unwrap();
    let build = Path::new(&build);
    let root = std::env::var_os("LSF_ANGULAR_T1_FIXTURE_ROOT").unwrap();
    let root = Path::new(&root);
    assert!(build.is_absolute() && root.is_absolute() && !root.exists());
    let observation_bytes = fs::read(build.join("observation.json")).unwrap();
    assert!(observation_bytes.len() <= 64 * 1024);
    let observed =
        decode_web_build_observation(&observation_bytes, ProvenanceLimits::default()).unwrap();
    assert_eq!(observed.build_type, ANGULAR_BUILD_TYPE);
    assert!(matches!(
        observed.source.repository.as_str(),
        "https://github.com/KirilsTurkins/latent-service-fabric" | "https://example.com/source"
    ));
    assert_eq!(observed.reproducibility, "not-checked");
    assert!(!observed.hermetic);
    fs::create_dir(root).unwrap();
    fs::set_permissions(root, fs::Permissions::from_mode(0o700)).unwrap();
    let signers = signing::Signers::new(
        observed.finished_at,
        &observed.source.repository,
        latent_signing::ANGULAR_BUILD_TYPE,
    );
    write(&root.join("policy.json"), &signers.policy_document);
    write(&root.join("observation.json"), &observation_bytes);
    let mut fixtures = Vec::new();
    for name in ["angular", "alternate", "missing-sbom"] {
        let bundle =
            read_package_directory(&build.join("package"), PackagingLimits::default()).unwrap();
        let bundle = if name == "angular" {
            bundle
        } else {
            variation(bundle, name == "missing-sbom")
        };
        let outputs = latent_artifacts::web::web_build_outputs(bundle.layout()).unwrap();
        assert_eq!(outputs.digest().to_string(), observed.outputs_digest);
        assert_eq!(outputs.count(), observed.outputs_count);
        assert_eq!(outputs.bytes(), observed.outputs_bytes);
        let layout =
            latent_packaging::inspect_web_bundle(&bundle, PackagingLimits::default().semantics)
                .unwrap();
        let renderer = layout.manifest().renderer.as_ref().unwrap();
        assert_eq!(
            renderer.profile,
            latent_manifest::RendererProfile::AngularSsrComponentV1
        );
        let directory = root.join(name);
        fs::create_dir(&directory).unwrap();
        latent_packaging::write_package_directory(&bundle, &directory.join("package")).unwrap();
        write_evidence(&signers, &bundle, &observed, &directory, name);
        fixtures.push(json!({
            "name": name, "packageDigest": layout.package().to_string(),
            "componentDigest": renderer.digest, "rendererBytes": renderer.size.to_string(),
            "assetsDigest": layout.assets_digest().to_string(), "manifestDigest": layout.manifest_digest().to_string(),
            "service": layout.name(), "assets": layout.manifest().assets, "routes": layout.manifest().routes,
            "wrapperVariation": name != "angular",
        }));
    }
    assert_ne!(fixtures[0]["packageDigest"], fixtures[1]["packageDigest"]);
    assert_eq!(
        fixtures[0]["componentDigest"],
        fixtures[1]["componentDigest"]
    );
    write(&root.join("fixture.json"), &serde_json::to_vec(&json!({
        "schemaVersion": "latent.phase3.angular.fixture.v1", "tenant": "tests",
        "fixtures": fixtures, "buildObservationDigest": artifact_blob_digest(&observation_bytes).to_string(),
        "actualAngularBuild": true, "reproducibility": observed.reproducibility,
        "dependencyCompleteness": observed.dependency_completeness,
    })).unwrap());
}

fn write_evidence(
    signers: &signing::Signers,
    bundle: &PackageBundle,
    observed: &WebBuildObservation,
    directory: &Path,
    name: &str,
) {
    for (evidence_name, lifetime) in [("evidence", 7200), ("renewed-evidence", 7199)] {
        let evidence = signers.evidence(bundle, observed, lifetime);
        let verification = signers.verify(bundle, signers.evidence(bundle, observed, lifetime));
        if name == "missing-sbom" {
            assert_eq!(
                verification.unwrap_err().message,
                "required-embedded-sbom-missing"
            );
        } else if let Err(failure) = verification {
            panic!("actual Angular admission: {}", failure.message);
        }
        latent_packaging::write_package_evidence(
            bundle.layout().digest(),
            &evidence,
            &directory.join(evidence_name),
            1024 * 1024,
        )
        .unwrap();
        if evidence_name == "evidence" {
            for missing_name in ["no-builder-evidence", "no-publisher-evidence"] {
                let mut missing = signers.evidence(bundle, observed, lifetime);
                if missing_name == "no-builder-evidence" {
                    missing.provenance.clear();
                } else {
                    missing.signatures.clear();
                }
                latent_packaging::write_package_evidence(
                    bundle.layout().digest(),
                    &missing,
                    &directory.join(missing_name),
                    1024 * 1024,
                )
                .unwrap();
            }
        }
    }
}
