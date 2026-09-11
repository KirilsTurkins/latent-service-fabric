use latent_artifacts::{content_digest, CapsuleArtifact};
use latent_core::{ArtifactReference, DeploymentId, ReleaseDigest, ServiceId};
use latent_manifest::{DeploymentManifest, JsonManifestCodec, ManifestCodec};
use serde_json::{json, Value};

use super::super::super::fixtures::Fixture;
use super::{Plan, Result};

pub(in crate::standalone::measurements::comparison) fn id(index: u32) -> String {
    format!("scale-{index:06}")
}

pub(super) fn service(plan: &Plan, index: u32) -> String {
    service_for_shape(&plan.shape, index)
}

pub(in crate::standalone::measurements::comparison) fn service_for_shape(
    shape: &str,
    index: u32,
) -> String {
    if shape == "shared" {
        "scale-shared".to_owned()
    } else {
        id(index)
    }
}

fn append_identity(component: &mut Vec<u8>, index: u32) {
    const NAME: &[u8] = b"latent.scale.identity.v1";
    component.push(0);
    component.push(u8::try_from(1 + NAME.len() + 4).unwrap());
    component.push(u8::try_from(NAME.len()).unwrap());
    component.extend_from_slice(NAME);
    component.extend_from_slice(&index.to_le_bytes());
}

pub(in crate::standalone::measurements::comparison) fn release(
    fixture: &Fixture,
    index: u32,
) -> ReleaseDigest {
    let mut bytes = fixture.artifact.component_bytes.clone();
    append_identity(&mut bytes, index);
    content_digest(&bytes)
}

pub(super) fn deployment(fixture: &Fixture, plan: &Plan, index: u32) -> DeploymentManifest {
    deployment_for_shape(fixture, &plan.shape, index)
}

pub(in crate::standalone::measurements::comparison) fn deployment_for_shape(
    fixture: &Fixture,
    shape: &str,
    index: u32,
) -> DeploymentManifest {
    let mut deployment = fixture.deployment.clone();
    let name = id(index);
    deployment.id = DeploymentId(name.clone());
    deployment.metadata.name = name;
    deployment.service = ServiceId(service_for_shape(shape, index));
    deployment.release = release(fixture, index);
    deployment.route_weight = 1;
    deployment
}

pub(super) fn artifact(fixture: &Fixture, plan: &Plan, index: u32) -> CapsuleArtifact {
    artifact_for_shape(fixture, &plan.shape, index)
}

pub(in crate::standalone::measurements::comparison) fn artifact_for_shape(
    fixture: &Fixture,
    shape: &str,
    index: u32,
) -> CapsuleArtifact {
    let mut artifact = fixture.artifact.clone();
    append_identity(&mut artifact.component_bytes, index);
    let digest = content_digest(&artifact.component_bytes);
    artifact.descriptor.reference = ArtifactReference(format!("local://scale/{index:06}"));
    artifact.descriptor.release_digest = digest.clone();
    artifact.descriptor.size_bytes = artifact.component_bytes.len() as u64;
    artifact.manifest.component_digest = digest;
    artifact.manifest.metadata.name = service_for_shape(shape, index);
    artifact
}

pub(in crate::standalone::measurements::comparison) fn template(
    fixture: &Fixture,
) -> Result<Value> {
    let codec = JsonManifestCodec::default();
    Ok(json!({"component_digest":fixture.release_digest,
        "component_bytes":fixture.artifact.component_bytes.len().to_string(),
        "capsule":serde_json::from_slice::<Value>(&codec.encode_capsule(&fixture.artifact.manifest).map_err(|_| "catalog fixture capsule encoding")?)?,
        "deployment":serde_json::from_slice::<Value>(&codec.encode_deployment(&fixture.deployment).map_err(|_| "catalog fixture deployment encoding")?)?,
        "contracts":serde_json::from_slice::<Value>(&latent_artifacts::encode_contract_metadata(
            &fixture.artifact.contracts,latent_artifacts::ContractMetadataLimits::default()).map_err(super::super::super::platform)?)?,
        "identity_section":{"name":"latent.scale.identity.v1","index_encoding":"u32-little-endian","added_bytes":"31"}}))
}
