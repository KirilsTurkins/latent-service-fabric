//! Consume an actual maintained build, including its original unsigned facts.
use latent_manifest::{CapsuleManifest, JsonManifestCodec, ManifestCodec, TransactionBinding};
use latent_packaging::{PackageBundle, PackagingLimits};
use latent_signing::{decode_build_observation, BuildObservation, ProvenanceLimits};
use serde::Deserialize;
use serde_json::Value;
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

#[path = "../../../latent-packaging/tests/sbom_association/support.rs"]
#[allow(dead_code)]
mod sbom;

pub fn directory(variant: &str) -> PathBuf {
    assert!(matches!(variant, "aggregate" | "forbidden-http"));
    PathBuf::from(
        std::env::var_os("LSF_TRANSACTION_GUEST_DIR")
            .expect("run prepare_transaction_guest_packages.py for this exact language"),
    )
    .join(variant)
}

pub fn profile() -> latent_manifest::ManifestValidationProfile {
    latent_manifest::ManifestValidationProfile::phase4(
        latent_core::BudgetProfile::Phase4,
        latent_core::PHASE4_HOST_ABI_V1,
        &latent_manifest::phase4_host_abi_digest(),
    )
    .unwrap()
}

pub fn read(root: &Path, relative: &str, maximum: u64) -> Vec<u8> {
    latent_packaging::read_package_file(root, relative, maximum).unwrap()
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct InputIdentity {
    digest: String,
    size: u64,
}

fn check_inventory(root: &Path, raw: &[u8], maximum_files: usize, maximum_total: u64) {
    let files: BTreeMap<String, InputIdentity> = serde_json::from_slice(raw).unwrap();
    assert!(!files.is_empty() && files.len() <= maximum_files);
    let mut total = 0_u64;
    for (name, identity) in files {
        total = total.checked_add(identity.size).unwrap();
        assert!(total <= maximum_total && identity.size <= 64 * 1024 * 1024);
        let bytes = read(root, &name, identity.size.max(1));
        assert_eq!(u64::try_from(bytes.len()).unwrap(), identity.size);
        assert_eq!(latent_artifacts::content_digest(&bytes).0, identity.digest);
    }
}

fn material(observation: &BuildObservation, name: &str, bytes: &[u8]) {
    let selected = observation
        .materials
        .iter()
        .filter(|row| row.name == name)
        .collect::<Vec<_>>();
    assert_eq!(selected.len(), 1, "one original build material");
    assert_eq!(
        selected[0].digest,
        latent_artifacts::content_digest(bytes).0
    );
    assert_eq!(selected[0].size, u64::try_from(bytes.len()).unwrap());
}

pub struct Prepared {
    pub bundle: PackageBundle,
    pub observation: BuildObservation,
    pub manifest: CapsuleManifest,
    pub declaration: TransactionBinding,
}

pub fn prepared(variant: &str) -> Prepared {
    let root = directory(variant);
    let project: Value =
        serde_json::from_slice(&read(&root, "project/capsule-project.json", 65536)).unwrap();
    let report: Value = serde_json::from_slice(&read(&root, "report.json", 65536)).unwrap();
    assert_eq!(
        report["schemaVersion"],
        "latent.transaction-guest.preparation.v1"
    );
    assert_eq!(report["evidenceKind"], "authored-observed-package");
    assert_eq!(report["status"], "prepared");
    assert_eq!(report["compiled"], true);
    assert_eq!(report["packageAssembled"], true);
    assert_eq!(report["variant"], variant);
    assert_eq!(
        report["hostAbiDigest"],
        latent_manifest::phase4_host_abi_digest()
    );
    let language = std::env::var("LSF_GUEST_SDK_LANGUAGE")
        .expect("select this exact maintained language profile");
    assert!(matches!(
        language.as_str(),
        "rust" | "c" | "typescript" | "go" | "java" | "dotnet"
    ));
    assert_eq!(report["language"], language);
    assert_eq!(report["signedNodeExecutionQualified"], false);
    let built = root.join("built");
    let marker: Value =
        serde_json::from_slice(&read(&built, "BUILD-COMPLETE.json", 65536)).unwrap();
    assert_eq!(marker["formatVersion"], 1);
    assert_eq!(marker["packageAssembled"], true);
    let raw = read(&built, "build-observation.json", 65536);
    let observation = decode_build_observation(&raw, ProvenanceLimits::default()).unwrap();
    let observation_digest = latent_artifacts::content_digest(&raw);
    assert_eq!(marker["observationDigest"], observation_digest.0);
    assert_eq!(report["buildObservationDigest"], observation_digest.0);
    assert_eq!(report["buildType"], observation.build_type);
    let component = read(&built, "component.wasm", 64 * 1024 * 1024);
    let component_digest = latent_artifacts::content_digest(&component);
    assert_eq!(observation.component_digest, component_digest.0);
    assert_eq!(
        observation.component_size,
        u64::try_from(component.len()).unwrap()
    );
    assert_eq!(marker["componentDigest"], component_digest.0);
    assert_eq!(report["componentDigest"], component_digest.0);
    assert_eq!(
        report["componentBytes"].as_u64(),
        Some(observation.component_size)
    );
    let source_inputs = read(&built, "source-inputs.json", 1024 * 1024);
    let source_digest = latent_artifacts::content_digest(&source_inputs);
    assert_eq!(observation.source.snapshot_digest, source_digest.0);
    assert_eq!(report["sourceDigest"], source_digest.0);
    assert_eq!(marker["sourceDigest"], source_digest.0);
    assert_eq!(
        observation.source.repository,
        "https://github.com/KirilsTurkins/latent-service-fabric"
    );
    assert_eq!(observation.source.capture, "explicit-input-files");
    check_inventory(
        &root.join("project"),
        &source_inputs,
        4096,
        32 * 1024 * 1024,
    );
    material(&observation, "source-snapshot", &source_inputs);
    material(
        &observation,
        "build-recipe",
        &read(&built, "recipe-inputs.json", 1024 * 1024),
    );
    let package_inputs = read(&built, "package-inputs.json", 1024 * 1024);
    check_inventory(&built, &package_inputs, 128, 128 * 1024 * 1024);
    material(&observation, "package-inputs", &package_inputs);
    let limits = PackagingLimits {
        manifest_profile: profile(),
        ..Default::default()
    };
    let recipe = read(&built, "package-source.json", 65536);
    assert_eq!(
        report["packageSourceDigest"],
        latent_artifacts::content_digest(&recipe).0
    );
    let source = latent_packaging::decode_package_source(&recipe, limits).unwrap();
    let input = latent_packaging::read_package_input(&built, &source, limits).unwrap();
    let mut inventory = sbom::inventory(&input);
    inventory.source_snapshot_digest = Some(latent_artifacts::package::artifact_blob_digest(
        &source_inputs,
    ));
    let bundle = latent_packaging::build_package_with_sbom(input, inventory, limits).unwrap();
    assert_eq!(bundle.blob("component.wasm").unwrap(), component);
    assert_eq!(
        bundle.layout().component_release().unwrap().0,
        component_digest.0
    );
    let manifest = JsonManifestCodec::default()
        .decode_capsule(bundle.blob("capsule.json").unwrap())
        .unwrap();
    let declaration_bytes = read(&root, "project/transaction-binding.json", 128 * 1024);
    assert_eq!(
        report["companionDigest"],
        latent_artifacts::content_digest(&declaration_bytes).0
    );
    assert_eq!(
        bundle.blob("transaction-binding.json").unwrap(),
        declaration_bytes
    );
    let declaration = TransactionBinding::decode(&declaration_bytes).unwrap();
    let name = project["name"].as_str().unwrap();
    assert_eq!(manifest.metadata.name, project["service"].as_str().unwrap());
    declaration
        .check_links(&manifest.metadata.name, name, name)
        .unwrap();
    Prepared {
        bundle,
        observation,
        manifest,
        declaration,
    }
}
