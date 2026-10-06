//! Explicit synthetic trust for real captured Java bytes. This is a package test
//! fixture, not a newly observed Java build or packaged distribution approval.
use super::{inputs, Result, TENANT};
use latent_artifacts::package::{artifact_blob_digest, LayerRole};
use latent_packaging::{
    build_package_with_sbom, decode_package_source, read_package_file, read_package_input,
    PackagingLimits,
};
use latent_signing::{
    decode_build_observation, BuildObservation, ProvenanceLimits, JAVA_CAPSULE_BUILD_TYPE,
};
use serde::Deserialize;
use serde_json::Value;
use std::path::Path;

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Fixture {
    schema_version: String,
    evidence_kind: String,
    compiler_source: String,
    compiler_report_digest: String,
    source_archive_digest: String,
    component_digest: String,
    source_snapshot_digest: String,
    companion_digest: String,
    requirements_digest: Option<String>,
    compiler_executed_by_signer: bool,
    packaged_distribution_qualified: bool,
    signed_node_execution_qualified: bool,
    provenance_model: BuildObservation,
}

pub(super) fn load(root: &Path) -> Result<inputs::Build> {
    let raw = read(root, "fixture-provenance-input.json", 65536)?;
    let fixture: Fixture = serde_json::from_slice(&raw)?;
    check_model(root, &fixture)?;
    let limits = PackagingLimits::default();
    let source_bytes = read(root, "package-source.json", 65536)?;
    let source = decode_package_source(&source_bytes, limits).map_err(|error| error.message)?;
    let input = read_package_input(root, &source, limits).map_err(|error| error.message)?;
    inputs::verify_package_inputs(&input, &source_bytes, &fixture.provenance_model)?;
    let component = input
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::Component)
        .ok_or("component missing")?;
    if artifact_blob_digest(&component.bytes).as_str() != fixture.component_digest
        || component.bytes.len() as u64 != fixture.provenance_model.component_size
    {
        return Err("original Java component association changed".into());
    }
    check_asset(
        &input,
        "transaction-binding.json",
        "application/vnd.latent.transaction-binding.v1+json",
        &fixture.companion_digest,
    )?;
    if let Some(digest) = &fixture.requirements_digest {
        check_asset(
            &input,
            "deferred-http-requirements.json",
            "application/json",
            digest,
        )?;
    }
    let manifest = input
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::CapsuleManifest)
        .ok_or("capsule manifest missing")?;
    let manifest: Value = serde_json::from_slice(&manifest.bytes)?;
    let service = manifest["metadata"]["name"]
        .as_str()
        .ok_or("service missing")?
        .to_owned();
    let world = manifest["component"]["world"]
        .as_str()
        .ok_or("world missing")?
        .to_owned();
    if manifest["metadata"]["tenant"] != TENANT
        || world != "examples:transactional-aggregate/service@1.0.0"
    {
        return Err("Java fixture scope changed".into());
    }
    let inventory = inputs::sbom(&input, &fixture.source_snapshot_digest)?;
    let bundle =
        build_package_with_sbom(input, inventory, limits).map_err(|error| error.message)?;
    let deployment = read(root, "deployment.json", 65536)?;
    let declared: Value = serde_json::from_slice(&deployment)?;
    if declared["metadata"]["tenant"] != TENANT
        || declared["spec"]["service"] != service
        || declared["spec"]["release"] != fixture.component_digest
        || declared["spec"]["grants"] != serde_json::json!([])
    {
        return Err("fixture deployment grants or component association changed".into());
    }
    Ok(inputs::Build {
        bundle,
        observation: fixture.provenance_model,
        deployment,
        service,
        world,
        fixture_evidence: Some(raw),
    })
}

fn check_model(root: &Path, fixture: &Fixture) -> Result<()> {
    if fixture.schema_version != "latent.component.signing-fixture-input.v1"
        || fixture.evidence_kind != "synthetic-native-package-trust"
        || fixture.compiler_source != "ff9ecd0733456bceacf5b96f14274b9c2dc0e8e6"
        || fixture.compiler_executed_by_signer
        || fixture.packaged_distribution_qualified
        || fixture.signed_node_execution_qualified
        || fixture.provenance_model.build_type != JAVA_CAPSULE_BUILD_TYPE
        || fixture.provenance_model.started_at != 0
        || fixture.provenance_model.finished_at != 0
        || fixture.provenance_model.component_digest != fixture.component_digest
        || fixture.provenance_model.source.snapshot_digest != fixture.source_snapshot_digest
    {
        return Err(
            "explicit unsigned fixture model required; compiler execution is not inferred".into(),
        );
    }
    decode_build_observation(
        &serde_json::to_vec(&fixture.provenance_model)?,
        ProvenanceLimits::default(),
    )?;
    for (name, digest, bound) in [
        (
            "source-inputs.json",
            &fixture.source_snapshot_digest,
            4 * 1024 * 1024,
        ),
        (
            "source.tar.gz",
            &fixture.source_archive_digest,
            32 * 1024 * 1024,
        ),
        (
            "compiler-report.json",
            &fixture.compiler_report_digest,
            262144,
        ),
    ] {
        if artifact_blob_digest(&read(root, name, bound)?).as_str() != digest {
            return Err("original compiler fixture material changed".into());
        }
    }
    Ok(())
}

fn check_asset(
    input: &latent_packaging::PackageInput,
    name: &str,
    media: &str,
    digest: &str,
) -> Result<()> {
    let asset = input
        .layers
        .iter()
        .find(|layer| layer.role == LayerRole::Asset && layer.path == name)
        .ok_or("original signed fixture asset missing")?;
    if asset.media_type != media || artifact_blob_digest(&asset.bytes).as_str() != digest {
        return Err("original signed fixture asset digest changed".into());
    }
    Ok(())
}
fn read(root: &Path, name: &str, maximum: u64) -> Result<Vec<u8>> {
    read_package_file(root, name, maximum).map_err(|error| error.message.into())
}
