//! Real package command semantics; these components execute no guest.
mod fixtures;
#[path = "../examples/support/package_driver.rs"]
#[allow(dead_code)]
mod package_driver;
#[path = "sbom_association/support.rs"]
#[allow(dead_code)]
mod sbom;

use latent_artifacts::package::LayerRole;
use latent_packaging::{PackageFile, PackageInput, PackageSource, PackagingLimits};
use serde_json::json;
use std::path::{Path, PathBuf};

fn input(root: &Path, input: &PackageInput) -> PathBuf {
    for layer in &input.layers {
        let path = root.join(&layer.path);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, &layer.bytes).unwrap();
    }
    let source = PackageSource {
        format_version: 1,
        kind: input.kind,
        name: input.name.clone(),
        version: input.version.clone(),
        entrypoint: input.entrypoint.clone(),
        annotations: input.annotations.clone(),
        layers: input
            .layers
            .iter()
            .map(|layer| PackageFile {
                path: layer.path.clone(),
                source: layer.path.clone(),
                role: layer.role,
                media_type: layer.media_type.clone(),
            })
            .collect(),
    };
    let recipe = root.join("package-source.json");
    std::fs::write(&recipe, serde_json::to_vec(&source).unwrap()).unwrap();
    recipe
}

fn selected() -> PackagingLimits {
    PackagingLimits {
        manifest_profile: fixtures::transaction_profile(),
        ..Default::default()
    }
}

fn build(
    root: &Path,
    recipe: &Path,
    output: &Path,
    limits: PackagingLimits,
) -> Result<(), Box<dyn std::error::Error>> {
    package_driver::run_args(
        &[
            "build".into(),
            recipe.to_str().unwrap().into(),
            root.to_str().unwrap().into(),
            output.to_str().unwrap().into(),
        ],
        limits,
    )
}

#[test]
fn stateless_command_refuses_transaction_inputs_and_selected_command_builds_and_inspects() {
    let root = tempfile::tempdir().unwrap();
    let recipe = input(root.path(), &fixtures::transactional_capsule());
    let refused = root.path().join("refused");
    assert!(build(root.path(), &recipe, &refused, PackagingLimits::default()).is_err());
    assert!(
        !refused.exists(),
        "no package is published after validation refusal"
    );
    let output = root.path().join("selected");
    build(root.path(), &recipe, &output, selected()).unwrap();
    let args = ["inspect".into(), output.to_str().unwrap().into()];
    package_driver::run_args(&args, selected()).unwrap();
    assert!(package_driver::run_args(&args, PackagingLimits::default()).is_err());
    let restored = latent_packaging::read_package_directory(&output, selected()).unwrap();
    assert_eq!(
        restored.blob("component.wasm"),
        Some(
            std::fs::read(root.path().join("component.wasm"))
                .unwrap()
                .as_slice()
        )
    );
}

#[test]
fn selected_command_preserves_stateless_bytes_and_refuses_output_replacement() {
    let root = tempfile::tempdir().unwrap();
    let recipe = input(
        root.path(),
        &fixtures::capsule(fixtures::component::Options::default()),
    );
    let ordinary = root.path().join("ordinary");
    let opted_in = root.path().join("opted-in");
    build(root.path(), &recipe, &ordinary, PackagingLimits::default()).unwrap();
    build(root.path(), &recipe, &opted_in, selected()).unwrap();
    let before = std::fs::read(ordinary.join("manifest.json")).unwrap();
    assert_eq!(
        before,
        std::fs::read(opted_in.join("manifest.json")).unwrap()
    );
    assert_eq!(
        std::fs::read(ordinary.join("config.json")).unwrap(),
        std::fs::read(opted_in.join("config.json")).unwrap()
    );
    assert!(build(root.path(), &recipe, &ordinary, selected()).is_err());
    assert_eq!(
        std::fs::read(ordinary.join("manifest.json")).unwrap(),
        before
    );
}

#[test]
fn selected_command_refuses_optional_transaction_import_and_raw_networking() {
    for networking in [false, true] {
        let root = tempfile::tempdir().unwrap();
        let mut capsule = fixtures::transactional_capsule();
        fixtures::mutate_json(&mut capsule, "capsule.json", |manifest| {
            if networking {
                manifest["imports"]
                    .as_array_mut()
                    .unwrap()
                    .push(json!({"contract":"wasi:sockets/tcp@0.2.0","optional":false}));
            } else {
                let state = manifest["imports"]
                    .as_array_mut()
                    .unwrap()
                    .iter_mut()
                    .find(|row| row["contract"] == "latent:state/key-value@0.2.0")
                    .unwrap();
                state["optional"] = json!(true);
            }
        });
        let recipe = input(root.path(), &capsule);
        let output = root.path().join("refused");
        assert!(build(root.path(), &recipe, &output, selected()).is_err());
        assert!(!output.exists());
    }
}

#[test]
fn selected_sbom_command_requires_the_actual_component_inventory() {
    let root = tempfile::tempdir().unwrap();
    let capsule = fixtures::transactional_capsule();
    let recipe = input(root.path(), &capsule);
    let mut inventory = sbom::inventory(&capsule);
    let inventory_path = root.path().join("sbom-inputs.json");
    std::fs::write(&inventory_path, serde_json::to_vec(&inventory).unwrap()).unwrap();
    let args = |output: &Path| {
        vec![
            "build-with-sbom".into(),
            recipe.to_str().unwrap().into(),
            inventory_path.to_str().unwrap().into(),
            root.path().to_str().unwrap().into(),
            output.to_str().unwrap().into(),
        ]
    };
    let output = root.path().join("with-sbom");
    package_driver::run_args(&args(&output), selected()).unwrap();
    let restored = latent_packaging::read_package_directory(&output, selected()).unwrap();
    assert!(restored.sbom().is_some());
    let component = capsule
        .layers
        .iter()
        .find(|row| row.role == LayerRole::Component)
        .unwrap();
    let entry = inventory
        .entries
        .iter_mut()
        .find(|row| row.path.as_deref() == Some(component.path.as_str()))
        .unwrap();
    entry.digest = Some(latent_artifacts::package::artifact_blob_digest(
        b"different component",
    ));
    std::fs::write(&inventory_path, serde_json::to_vec(&inventory).unwrap()).unwrap();
    let refused = root.path().join("refused");
    assert!(package_driver::run_args(&args(&refused), selected()).is_err());
    assert!(!refused.exists());
}
