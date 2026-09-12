use latent_core::PublisherId;
use serde_json::{json, Value};

use super::super::{JsonManifestCodec, ManifestCodec};
use crate::package::{artifact_blob_digest, package_digest, EvidenceKind};
use crate::{AdmissionEvidence, CapsuleArtifact, ContractMetadataLimits, PackageAdmissionUpload};

pub(super) fn artifact() -> CapsuleArtifact {
    let mut value = super::super::artifact("admission", b"tiny non-executable storage fixture");
    value.descriptor.publisher = Some(PublisherId("test-publisher".to_owned()));
    value
}

pub(super) fn upload() -> PackageAdmissionUpload {
    let artifact = artifact();
    let layers = vec![
        ("a.wasm".to_owned(), artifact.component_bytes),
        (
            "b.json".to_owned(),
            JsonManifestCodec::default()
                .encode_capsule(&artifact.manifest)
                .unwrap(),
        ),
        (
            "c.json".to_owned(),
            crate::encode_contract_metadata(&artifact.contracts, ContractMetadataLimits::default())
                .unwrap(),
        ),
        ("d.json".to_owned(), b"{}".to_vec()),
    ];
    let roles = [
        ("component", "application/wasm"),
        (
            "capsule-manifest",
            "application/vnd.latent.capsule.manifest.v1+json",
        ),
        ("contracts", "application/vnd.latent.contracts.v1+json"),
        ("wit-lock", "application/vnd.latent.wit-lock.v1+json"),
    ];
    let config_layers: Vec<Value> = layers.iter().zip(roles).map(|((path, bytes), (role, mime))| json!({
        "path": path, "role": role, "mediaType": mime, "digest": artifact_blob_digest(bytes).as_str(), "size": bytes.len()
    })).collect();
    let configuration = serde_json::to_vec(&json!({"formatVersion":1,"kind":"capsule","name":"echo","version":"0.1.0",
        "entrypoint":"a.wasm","componentDigest":artifact_blob_digest(&layers[0].1).as_str(),"layers":config_layers,"annotations":{}})).unwrap();
    let manifest_layers: Vec<Value> = config_layers.iter().map(|layer| json!({"mediaType":layer["mediaType"],
        "digest":layer["digest"],"size":layer["size"],"annotations":{"org.opencontainers.image.title":layer["path"],"dev.latent.layer.role":layer["role"]}})).collect();
    let manifest = serde_json::to_vec(&json!({"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json",
        "artifactType":"application/vnd.latent.capsule.v1","config":{"mediaType":"application/vnd.latent.package.config.v1+json",
            "digest":artifact_blob_digest(&configuration).as_str(),"size":configuration.len()},"layers":manifest_layers,"annotations":{}})).unwrap();
    let signatures = vec![evidence(&manifest, EvidenceKind::Signature)];
    let provenance = vec![evidence(&manifest, EvidenceKind::Provenance)];
    PackageAdmissionUpload {
        manifest,
        configuration,
        layers,
        signatures,
        provenance,
        sboms: Vec::new(),
    }
}
fn evidence(subject: &[u8], kind: EvidenceKind) -> AdmissionEvidence {
    let payload = b"test evidence bytes".to_vec();
    let configuration = b"{}".to_vec();
    let manifest = serde_json::to_vec(&json!({"schemaVersion":2,"mediaType":"application/vnd.oci.image.manifest.v1+json",
        "artifactType":kind.artifact_type(),"config":{"mediaType":"application/vnd.oci.empty.v1+json",
            "digest":artifact_blob_digest(&configuration).as_str(),"size":2},"subject":{"mediaType":"application/vnd.oci.image.manifest.v1+json",
            "digest":package_digest(subject).as_str(),"size":subject.len()},
        "layers":[{"mediaType":kind.payload_media_type(),"digest":artifact_blob_digest(&payload).as_str(),"size":payload.len(),
            "annotations":{"org.opencontainers.image.title":"evidence.json","dev.latent.layer.role":"evidence"}}],"annotations":{}})).unwrap();
    AdmissionEvidence {
        manifest,
        configuration,
        payload,
    }
}
