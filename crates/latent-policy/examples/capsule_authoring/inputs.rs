use std::{collections::BTreeMap, path::Path};

use latent_artifacts::package::{artifact_blob_digest, decode_wit_lock, LayerRole, PackageLimits};
use latent_packaging::{
    build_package_with_sbom, decode_package_source, read_package_file, read_package_input,
    PackageBundle, PackageInput, PackagingLimits, SbomDependencyCompleteness, SbomDigestScope,
    SbomEntryKind, SbomEntryOrigin, SbomInventory, SbomInventoryEntry,
};
use latent_signing::{
    decode_build_observation, BuildObservation, BuildRecipe, ProvenanceLimits, C_GUEST_BUILD_TYPE,
    GO_CAPSULE_BUILD_TYPE, RUST_CAPSULE_BUILD_TYPE,
};
use serde_json::{json, Value};

use super::{Result, TENANT};

pub(super) struct Build {
    pub bundle: PackageBundle,
    pub observation: BuildObservation,
    pub deployment: Vec<u8>,
    pub service: String,
    pub world: String,
}

fn read(root: &Path, name: &str, maximum: u64) -> Result<Vec<u8>> {
    read_package_file(root, name, maximum).map_err(|error| error.message.into())
}

pub(super) fn load(root: &Path) -> Result<Build> {
    let marker: Value = serde_json::from_slice(&read(root, "BUILD-COMPLETE.json", 65536)?)?;
    let raw = read(root, "build-observation.json", 32768)?;
    let observation = decode_build_observation(&raw, ProvenanceLimits::default())?;
    if !matches!(
        observation.build_type.as_str(),
        RUST_CAPSULE_BUILD_TYPE | C_GUEST_BUILD_TYPE | GO_CAPSULE_BUILD_TYPE
    ) || marker["formatVersion"] != 1
        || marker["observationDigest"] != artifact_blob_digest(&raw).as_str()
    {
        return Err("completed standalone build observation required".into());
    }
    let snapshot = read(root, "source-inputs.json", 4 * 1024 * 1024)?;
    if observation.source.snapshot_digest != artifact_blob_digest(&snapshot).as_str()
        || marker["sourceDigest"] != observation.source.snapshot_digest
    {
        return Err("build source snapshot association mismatch".into());
    }
    let limits = PackagingLimits::default();
    let source_bytes = read(root, "package-source.json", 65536)?;
    let source = decode_package_source(&source_bytes, limits).map_err(|error| error.message)?;
    let input = read_package_input(root, &source, limits).map_err(|error| error.message)?;
    let mut identities =
        BTreeMap::from([("package-source.json".to_owned(), identity(&source_bytes))]);
    for layer in &input.layers {
        identities.insert(layer.path.clone(), identity(&layer.bytes));
    }
    let inventory_bytes = serde_json::to_vec(&identities)?;
    let material = observation
        .materials
        .iter()
        .find(|m| m.name == "package-inputs")
        .ok_or("missing package input observation")?;
    if material.digest != artifact_blob_digest(&inventory_bytes).as_str()
        || material.size != inventory_bytes.len() as u64
    {
        return Err("package inputs changed since the observed build".into());
    }
    let manifest = input
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::CapsuleManifest)
        .ok_or("capsule manifest missing")?;
    let manifest: Value = serde_json::from_slice(&manifest.bytes)?;
    if manifest["metadata"]["tenant"] != TENANT {
        return Err("demo signer is confined to the examples tenant".into());
    }
    let service = manifest["metadata"]["name"]
        .as_str()
        .ok_or("service identity missing")?
        .to_owned();
    let world = manifest["component"]["world"]
        .as_str()
        .ok_or("world identity missing")?
        .to_owned();
    match &observation.parameters {
        BuildRecipe::RustCapsule(recipe) if input.name == recipe.cargo_package => {}
        BuildRecipe::C(recipe) if recipe.fixture == "application" => {}
        BuildRecipe::GoCapsule(recipe) if input.name == recipe.go_package => {}
        _ => return Err("standalone recipe and matching package identity required".into()),
    }
    let inventory = sbom(&input, &observation)?;
    let bundle =
        build_package_with_sbom(input, inventory, limits).map_err(|error| error.message)?;
    let deployment = read(root, "deployment.json", 65536)?;
    let deployment_value: Value = serde_json::from_slice(&deployment)?;
    if deployment_value["metadata"]["tenant"] != TENANT
        || deployment_value["spec"]["service"] != service
        || deployment_value["spec"]["release"] != observation.component_digest
        || deployment_value["spec"]["grants"] != json!([])
    {
        return Err("demo deployment must match the package and grant no authority".into());
    }
    Ok(Build {
        bundle,
        observation,
        deployment,
        service,
        world,
    })
}

fn identity(bytes: &[u8]) -> Value {
    json!({"digest":artifact_blob_digest(bytes).as_str(),"size":bytes.len()})
}

fn sbom(input: &PackageInput, observation: &BuildObservation) -> Result<SbomInventory> {
    let layer = input
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::WitLock)
        .ok_or("WIT lock missing")?;
    let lock =
        decode_wit_lock(&layer.bytes, PackageLimits::default()).map_err(|error| error.message)?;
    let mut entries = Vec::new();
    for layer in &input.layers {
        if !matches!(layer.role, LayerRole::Component | LayerRole::Asset) {
            continue;
        }
        let wit = lock
            .packages
            .iter()
            .find(|package| package.source_path == layer.path);
        let (kind, scope, name, version) = match wit {
            Some(wit) => {
                let (name, version) = wit.id.rsplit_once('@').ok_or("unversioned WIT package")?;
                (
                    SbomEntryKind::WitPackage,
                    SbomDigestScope::WitSource,
                    name.to_owned(),
                    Some(version.to_owned()),
                )
            }
            None => (
                SbomEntryKind::Component,
                SbomDigestScope::OutputBytes,
                layer.path.clone(),
                None,
            ),
        };
        entries.push(SbomInventoryEntry {
            kind,
            name,
            version,
            source: None,
            license_expression: None,
            digest: Some(artifact_blob_digest(&layer.bytes)),
            digest_scope: Some(scope),
            size: Some(layer.bytes.len() as u64),
            path: Some(layer.path.clone()),
            manifest_digest: None,
            manifest_size: None,
            origin: SbomEntryOrigin::PackageInput,
        });
    }
    Ok(SbomInventory {
        format_version: 1,
        package_kind: input.kind,
        package_name: input.name.clone(),
        package_version: input.version.clone(),
        dependency_completeness: SbomDependencyCompleteness::DeclaredInputsIncomplete,
        source_snapshot_digest: Some(observation.source.snapshot_digest.parse()?),
        entries,
    })
}
