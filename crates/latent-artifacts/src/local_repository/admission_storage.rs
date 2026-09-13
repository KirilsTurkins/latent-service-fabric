//! Closed exact-byte side material, bound by the version-2 completion record.
mod read;

use std::path::Path;

use latent_core::PlatformError;
use serde::{Deserialize, Serialize};

use super::{corrupt, resource_exhausted, write_synced, COMPONENT_FILE};
use crate::package::{inspect_package, verify_layer_bytes, LayerRole, PackageKind, PackageLimits};
use crate::{
    content_digest, AdmissionBinding, AdmissionEvidence, AdmissionStorageLimits, CapsuleArtifact,
    PackageAdmissionUpload,
};

pub(super) const RECORD_FILE: &str = "admission.json";

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Blob {
    file: String,
    digest: String,
    size: u64,
}
#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Layer {
    path: String,
    blob: Blob,
}
#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Evidence {
    manifest: Blob,
    configuration: Blob,
    payload: Blob,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct StoredAdmission {
    format_version: u32,
    tenant: String,
    package: String,
    release: String,
    receipt: Blob,
    manifest: Blob,
    configuration: Blob,
    layers: Vec<Layer>,
    signatures: Vec<Evidence>,
    provenance: Vec<Evidence>,
    sboms: Vec<Evidence>,
}

pub(super) struct PreparedAdmissionFiles {
    pub(super) record_bytes: Vec<u8>,
    files: Vec<(String, Vec<u8>)>,
    record: StoredAdmission,
}
impl PreparedAdmissionFiles {
    pub(super) fn prepare(
        binding: &AdmissionBinding,
        mut upload: PackageAdmissionUpload,
        artifact: &CapsuleArtifact,
        limits: AdmissionStorageLimits,
        component_limit: usize,
    ) -> Result<Self, PlatformError> {
        limits.check_binding(binding)?;
        limits.check_upload(&upload, component_limit)?;
        let layout = inspect_package(
            &upload.manifest,
            &upload.configuration,
            PackageLimits::default(),
        )?;
        if layout.digest() != &binding.package
            || layout.config().kind != PackageKind::Capsule
            || artifact.manifest.metadata.tenant.as_ref() != Some(&binding.tenant)
            || artifact.descriptor.release_digest != binding.release
            || artifact.manifest.component_digest != binding.release
            || upload.layers.len() != layout.config().layers.len()
        {
            return Err(corrupt("admission-package-association"));
        }
        upload.layers.sort_by(|a, b| a.0.cmp(&b.0));
        let mut component_path = None;
        for ((path, bytes), layer) in upload.layers.iter().zip(&layout.config().layers) {
            if path != &layer.path {
                return Err(corrupt("admission-package-layer-set"));
            }
            verify_layer_bytes(layer, bytes, PackageLimits::default())?;
            if layer.role == LayerRole::Component {
                if bytes != &artifact.component_bytes || component_path.is_some() {
                    return Err(corrupt("admission-component-association"));
                }
                component_path = Some(path.clone());
            }
        }
        let component_path =
            component_path.ok_or_else(|| corrupt("admission-component-missing"))?;
        drop(layout);
        let mut files = Vec::new();
        let receipt = add(&mut files, binding.receipt.clone());
        let manifest = add(&mut files, upload.manifest);
        let configuration = add(&mut files, upload.configuration);
        let layers = upload
            .layers
            .into_iter()
            .map(|(path, bytes)| {
                let blob = if path == component_path {
                    Blob {
                        file: COMPONENT_FILE.to_owned(),
                        digest: content_digest(&bytes).0,
                        size: bytes.len() as u64,
                    }
                } else {
                    add(&mut files, bytes)
                };
                Layer { path, blob }
            })
            .collect();
        let signatures = evidence(&mut files, upload.signatures);
        let provenance = evidence(&mut files, upload.provenance);
        let sboms = evidence(&mut files, upload.sboms);
        let record = StoredAdmission {
            format_version: 1,
            tenant: binding.tenant.0.clone(),
            package: binding.package.as_str().to_owned(),
            release: binding.release.0.clone(),
            receipt,
            manifest,
            configuration,
            layers,
            signatures,
            provenance,
            sboms,
        };
        let auxiliary = files
            .iter()
            .try_fold(0_usize, |used, (_, bytes)| used.checked_add(bytes.len()))
            .ok_or_else(|| resource_exhausted("admission-auxiliary-byte-limit"))?;
        if auxiliary > limits.max_auxiliary_bytes {
            return Err(resource_exhausted("admission-auxiliary-byte-limit"));
        }
        let record_bytes =
            serde_json::to_vec(&record).map_err(|_| corrupt("admission-record-encoding"))?;
        if record_bytes.len() > limits.max_document_bytes {
            return Err(resource_exhausted("admission-record-byte-limit"));
        }
        Ok(Self {
            record_bytes,
            files,
            record,
        })
    }

    pub(super) fn write(&self, directory: &Path) -> Result<(), PlatformError> {
        for (name, bytes) in &self.files {
            write_synced(&directory.join(name), bytes)?;
        }
        write_synced(&directory.join(RECORD_FILE), &self.record_bytes)
    }

    pub(super) fn same_upload(&self, stored: &StoredAdmission) -> bool {
        let value = &self.record;
        value.tenant == stored.tenant
            && value.package == stored.package
            && value.release == stored.release
            && value.manifest == stored.manifest
            && value.configuration == stored.configuration
            && value.layers == stored.layers
            && value.signatures == stored.signatures
            && value.provenance == stored.provenance
            && value.sboms == stored.sboms
    }
}

fn add(files: &mut Vec<(String, Vec<u8>)>, bytes: Vec<u8>) -> Blob {
    let file = format!("admission-{:04}.bin", files.len());
    let blob = Blob {
        file: file.clone(),
        digest: content_digest(&bytes).0,
        size: bytes.len() as u64,
    };
    files.push((file, bytes));
    blob
}
fn evidence(files: &mut Vec<(String, Vec<u8>)>, entries: Vec<AdmissionEvidence>) -> Vec<Evidence> {
    entries
        .into_iter()
        .map(|value| Evidence {
            manifest: add(files, value.manifest),
            configuration: add(files, value.configuration),
            payload: add(files, value.payload),
        })
        .collect()
}
