//! Packaging-only derivation of an observed examples component, not compilation.
use std::{
    collections::BTreeMap,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

use latent_artifacts::package::{artifact_blob_digest, LayerRole};
use latent_packaging::{
    build_package_with_sbom, decode_package_source, read_package_file, read_package_input,
    LayerInput, PackageFile, PackageInput, PackageSource, PackagingLimits,
};
use latent_signing::{decode_build_observation, BuildMaterial, BuildObservation, ProvenanceLimits};
use serde_json::{json, Value};

use super::{inputs, Result, TENANT};

const ORIGINAL: &str = "resource-original-build-observation.json";
const DERIVATION: &str = "resource-neutral-derivation.json";

fn read(root: &Path, path: &str, maximum: u64) -> Result<Vec<u8>> {
    read_package_file(root, path, maximum).map_err(|error| error.message.into())
}

fn identity(bytes: &[u8]) -> Value {
    json!({"digest":artifact_blob_digest(bytes).as_str(),"size":bytes.len()})
}

fn require_original_asset_path(path: &str) -> Result<()> {
    if [ORIGINAL, DERIVATION].contains(&path) {
        return Err("resource derivation reserved asset already present".into());
    }
    Ok(())
}

fn require_package_inputs(material: &BuildMaterial, bytes: &[u8]) -> Result<()> {
    if material.name != "package-inputs"
        || material.digest != artifact_blob_digest(bytes).as_str()
        || material.size != bytes.len() as u64
    {
        return Err("original resource package inputs changed during derivation".into());
    }
    Ok(())
}

fn neutral_documents(manifest: &mut Value, deployment: &mut Value, name: &str) -> Result<()> {
    inputs::require_fixture_tenant(manifest, Some(TENANT))?;
    if name.is_empty()
        || name.contains('/')
        || name.contains(':')
        || manifest["metadata"]["name"] != format!("{TENANT}/{name}")
        || deployment["metadata"]["tenant"] != TENANT
        || deployment["spec"]["service"] != manifest["metadata"]["name"]
        || deployment["spec"]["grants"] != json!([])
    {
        return Err("neutral resources require an observed examples service without grants".into());
    }
    manifest["metadata"]
        .as_object_mut()
        .ok_or("capsule metadata")?
        .remove("tenant");
    manifest["metadata"]["name"] = json!(name);
    deployment["metadata"]
        .as_object_mut()
        .ok_or("deployment metadata")?
        .remove("tenant");
    deployment["spec"]["service"] = json!(name);
    Ok(())
}

struct Captured {
    source: PackageSource,
    input: PackageInput,
    raw: Vec<u8>,
    ancestry: Value,
}

fn checked_original(root: &Path, original: &inputs::Build) -> Result<Captured> {
    let limits = PackagingLimits::default();
    let raw = read(root, "build-observation.json", 32768)?;
    let marker = read(root, "BUILD-COMPLETE.json", 65536)?;
    let snapshot = read(root, "source-inputs.json", 4 * 1024 * 1024)?;
    if decode_build_observation(&raw, ProvenanceLimits::default())? != original.observation
        || serde_json::from_slice::<Value>(&marker)?["observationDigest"]
            != artifact_blob_digest(&raw).as_str()
        || original.observation.source.snapshot_digest != artifact_blob_digest(&snapshot).as_str()
    {
        return Err("original resource build changed during derivation".into());
    }
    let source_raw = read(root, "package-source.json", 65536)?;
    let source = decode_package_source(&source_raw, limits).map_err(|error| error.message)?;
    let input = read_package_input(root, &source, limits).map_err(|error| error.message)?;
    let mut inventory = BTreeMap::from([("package-source.json".to_owned(), identity(&source_raw))]);
    for layer in &input.layers {
        require_original_asset_path(&layer.path)?;
        inventory.insert(layer.path.clone(), identity(&layer.bytes));
    }
    let inventory_raw = serde_json::to_vec(&inventory)?;
    let material = original
        .observation
        .materials
        .iter()
        .find(|row| row.name == "package-inputs")
        .ok_or("original package input observation missing")?;
    require_package_inputs(material, &inventory_raw)?;
    let ancestry = json!({
        "schemaVersion":"latent.resource.neutral-packaging.v1",
        "operation":"neutral-resource-packaging-only", "tenants":[TENANT,"foreign"],
        "componentCompilationPerformed":false,"nativeCompilationPerformed":false,
        "typedCompilerRecipe":"inherited-original-component-compilation-only",
        "originalBuildObservation":identity(&raw),"originalBuildComplete":identity(&marker),
        "originalSourceInputs":identity(&snapshot),"originalPackageSource":identity(&source_raw),
        "originalPackageInputs":identity(&inventory_raw),
        "originalDeployment":identity(&original.deployment),
        "component":{"digest":original.observation.component_digest,"size":original.observation.component_size},
        "originalPackageDigest":latent_artifacts::package::package_digest(original.bundle.manifest_bytes()).as_str(),
        "sourceRepository":original.observation.source.repository,
        "sourceRevision":original.observation.source.revision,
        "sourceSnapshotDigest":original.observation.source.snapshot_digest
    });
    Ok(Captured {
        source,
        input,
        raw,
        ancestry,
    })
}

pub(super) fn load(root: &Path) -> Result<inputs::Build> {
    let original = inputs::load(root)?;
    let Captured {
        mut source,
        mut input,
        raw,
        mut ancestry,
    } = checked_original(root, &original)?;
    let capsule = input
        .layers
        .iter_mut()
        .find(|layer| layer.role == LayerRole::CapsuleManifest)
        .ok_or("original capsule missing")?;
    let original_capsule = identity(&capsule.bytes);
    let mut manifest: Value = serde_json::from_slice(&capsule.bytes)?;
    let mut deployment: Value = serde_json::from_slice(&original.deployment)?;
    neutral_documents(&mut manifest, &mut deployment, &input.name)?;
    capsule.bytes = serde_json::to_vec(&manifest)?;
    let derived_capsule = identity(&capsule.bytes);
    let deployment = serde_json::to_vec(&deployment)?;
    ancestry["originalCapsule"] = original_capsule;
    ancestry["derivedCapsule"] = derived_capsule;
    ancestry["derivedDeployment"] = identity(&deployment);
    let derivation = serde_json::to_vec(&ancestry)?;
    for (path, media, bytes) in [
        (
            ORIGINAL,
            "application/vnd.latent.build-observation.v1+json",
            raw,
        ),
        (
            DERIVATION,
            "application/vnd.latent.resource.neutral-packaging.v1+json",
            derivation,
        ),
    ] {
        source.layers.push(PackageFile {
            path: path.into(),
            source: path.into(),
            role: LayerRole::Asset,
            media_type: media.into(),
        });
        input.layers.push(LayerInput {
            path: path.into(),
            role: LayerRole::Asset,
            media_type: media.into(),
            bytes,
        });
    }
    let observation = packaging_observation(original.observation, &source, &input)?;
    let sbom = inputs::sbom(&input, &observation.source.snapshot_digest)?;
    let bundle = build_package_with_sbom(input, sbom, PackagingLimits::default())
        .map_err(|error| error.message)?;
    Ok(inputs::Build {
        bundle,
        observation,
        deployment,
        service: source.name,
        world: original.world,
    })
}

fn packaging_observation(
    mut observation: BuildObservation,
    source: &PackageSource,
    input: &PackageInput,
) -> Result<BuildObservation> {
    let source_raw = serde_json::to_vec(&source)?;
    let mut inventory = BTreeMap::from([("package-source.json".to_owned(), identity(&source_raw))]);
    for layer in &input.layers {
        inventory.insert(layer.path.clone(), identity(&layer.bytes));
    }
    let inventory_raw = serde_json::to_vec(&inventory)?;
    // Source and typed recipe retain the original compilation identity. These
    // mandatory assets distinguish this fresh packaging event from that compile.
    observation
        .materials
        .retain(|row| row.name != "package-inputs");
    for (name, bytes) in [
        ("package-inputs", inventory_raw.as_slice()),
        ("resource-neutral-package-source", source_raw.as_slice()),
        (
            "resource-original-build-observation",
            input.layers[input.layers.len() - 2].bytes.as_slice(),
        ),
        (
            "resource-neutral-derivation",
            input.layers[input.layers.len() - 1].bytes.as_slice(),
        ),
    ] {
        observation.materials.push(BuildMaterial {
            name: name.into(),
            digest: artifact_blob_digest(bytes).to_string(),
            size: bytes.len() as u64,
        });
    }
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    observation.started_at = now;
    observation.finished_at = now;
    observation.hermetic = false;
    observation.reproducibility = "not-checked".into();
    // Validate the closed provenance schema before the caller generates keys.
    decode_build_observation(
        &serde_json::to_vec(&observation)?,
        ProvenanceLimits::default(),
    )?;
    Ok(observation)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn documents() -> (Value, Value) {
        (
            json!({"metadata":{"name":"examples/my-greeting","tenant":"examples"},
            "component":{"world":"examples:greeting/service@1.0.0","digest":"unchanged"},
            "exports":["examples:greeting/api@1.0.0"]}),
            json!({"metadata":{"name":"my-greeting","tenant":"examples"},
            "spec":{"service":"examples/my-greeting","release":"unchanged","grants":[]}}),
        )
    }

    #[test]
    fn neutral_resource_scope_preserves_component_world_exports_and_original_documents() {
        let (manifest, deployment) = documents();
        let (mut neutral, mut target) = (manifest.clone(), deployment.clone());
        neutral_documents(&mut neutral, &mut target, "my-greeting").unwrap();
        assert_eq!(neutral["component"], manifest["component"]);
        assert_eq!(neutral["exports"], manifest["exports"]);
        assert_eq!(target["spec"]["release"], deployment["spec"]["release"]);
        assert_eq!(neutral["metadata"]["name"], "my-greeting");
        assert!(neutral["metadata"].get("tenant").is_none());
        assert!(target["metadata"].get("tenant").is_none());
        assert!(inputs::require_fixture_tenant(&neutral, Some(TENANT)).is_err());
        assert!(inputs::require_fixture_tenant(&neutral, None).is_ok());
        assert!(inputs::require_fixture_tenant(&manifest, Some(TENANT)).is_ok());
    }

    #[test]
    fn neutral_resource_scope_refuses_foreign_scoped_names_and_new_grants() {
        for name in ["", "foreign/my-greeting", "foreign:my-greeting", "other"] {
            let (mut manifest, mut deployment) = documents();
            assert!(neutral_documents(&mut manifest, &mut deployment, name).is_err());
        }
        let (mut manifest, mut deployment) = documents();
        deployment["spec"]["grants"] = json!(["extra-authority"]);
        assert!(neutral_documents(&mut manifest, &mut deployment, "my-greeting").is_err());
        let (mut manifest, mut deployment) = documents();
        manifest["metadata"]["tenant"] = json!("foreign");
        assert!(neutral_documents(&mut manifest, &mut deployment, "my-greeting").is_err());
    }

    #[test]
    fn neutral_resource_derivation_refuses_changed_original_inventory_and_reserved_assets() {
        let bytes = b"original-complete-package-input-inventory";
        let material = BuildMaterial {
            name: "package-inputs".into(),
            digest: artifact_blob_digest(bytes).to_string(),
            size: bytes.len() as u64,
        };
        assert!(require_package_inputs(&material, bytes).is_ok());
        assert!(
            require_package_inputs(&material, b"changed-complete-package-input-inventory").is_err()
        );
        let mut invalid = material;
        invalid.size += 1;
        assert!(require_package_inputs(&invalid, bytes).is_err());
        assert!(require_original_asset_path("component.wasm").is_ok());
        assert!(require_original_asset_path(ORIGINAL).is_err());
        assert!(require_original_asset_path(DERIVATION).is_err());
    }
}
