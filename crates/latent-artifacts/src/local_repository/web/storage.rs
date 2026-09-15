mod read;

use super::super::{
    admission_storage::{add, evidence, Blob, Evidence, Layer},
    corrupt, resource_exhausted,
};
use crate::{
    package::{inspect_package, verify_layer_bytes, PackageLimits},
    web::{
        inspect_web_layout, CheckedWebLayout, WebAdmissionBinding, MAX_WEB_RENDERER_BYTES,
        WEB_MANIFEST_PATH,
    },
    AdmissionStorageLimits, PackageAdmissionUpload, PublicationRef,
};
use latent_core::{PlatformError, TenantId};
use serde::{Deserialize, Serialize};

pub(super) const RECORD: &str = "web-admission.json";
pub(super) const COMPLETE: &str = "WEB_COMPLETE";

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(super) struct Stored {
    format_version: u32,
    pub(super) publication: PublicationRef,
    package: String,
    web_manifest: String,
    assets: String,
    receipt: Blob,
    manifest: Blob,
    configuration: Blob,
    pub(super) layers: Vec<Layer>,
    signatures: Vec<Evidence>,
    provenance: Vec<Evidence>,
    sboms: Vec<Evidence>,
}

pub(super) struct Prepared {
    pub(super) record: Stored,
    pub(super) record_bytes: Vec<u8>,
    pub(super) files: Vec<(String, Vec<u8>)>,
    pub(super) completion: Vec<u8>,
}
impl Prepared {
    pub(super) fn new(
        publication: PublicationRef,
        binding: &WebAdmissionBinding,
        mut upload: PackageAdmissionUpload,
        layout: &CheckedWebLayout,
        limits: AdmissionStorageLimits,
        component_limit: usize,
    ) -> Result<Self, PlatformError> {
        if publication.scope.tenant() != Some(&binding.tenant)
            || publication != PublicationRef::package(publication.scope.clone(), &binding.package)?
        {
            return Err(corrupt("web-publication-association"));
        }
        let checked = check_upload(binding, &mut upload, limits, component_limit)?;
        if &checked != layout {
            return Err(corrupt("web-verified-layout-mismatch"));
        }
        let mut files = Vec::new();
        let record = Stored {
            format_version: 1,
            publication,
            package: binding.package.to_string(),
            web_manifest: binding.manifest.to_string(),
            assets: binding.assets.to_string(),
            receipt: add(&mut files, binding.receipt.clone()),
            manifest: add(&mut files, upload.manifest),
            configuration: add(&mut files, upload.configuration),
            layers: upload
                .layers
                .into_iter()
                .map(|(path, bytes)| Layer {
                    path,
                    blob: add(&mut files, bytes),
                })
                .collect(),
            signatures: evidence(&mut files, upload.signatures),
            provenance: evidence(&mut files, upload.provenance),
            sboms: evidence(&mut files, upload.sboms),
        };
        record.check_shape(limits, component_limit)?;
        let record_bytes =
            serde_json::to_vec(&record).map_err(|_| corrupt("web-record-encoding"))?;
        if record_bytes.len() > limits.max_document_bytes {
            return Err(resource_exhausted("web-record-size"));
        }
        let completion = crate::package::artifact_blob_digest(&record_bytes)
            .to_string()
            .into_bytes();
        Ok(Self {
            record,
            record_bytes,
            files,
            completion,
        })
    }
    pub(super) fn content_files(&self) -> Vec<(&str, &[u8])> {
        self.files
            .iter()
            .map(|(name, bytes)| (name.as_str(), bytes.as_slice()))
            .chain([
                (RECORD, self.record_bytes.as_slice()),
                (COMPLETE, self.completion.as_slice()),
            ])
            .collect()
    }
    pub(super) fn same_upload(&self, other: &Stored) -> bool {
        let value = &self.record;
        value.publication == other.publication
            && value.package == other.package
            && value.web_manifest == other.web_manifest
            && value.assets == other.assets
            && value.manifest == other.manifest
            && value.configuration == other.configuration
            && value.layers == other.layers
            && value.signatures == other.signatures
            && value.provenance == other.provenance
            && value.sboms == other.sboms
    }
}

pub(super) fn check_binding(
    binding: &WebAdmissionBinding,
    limits: AdmissionStorageLimits,
) -> Result<(), PlatformError> {
    limits.validate()?;
    if binding.tenant.0.is_empty()
        || binding.tenant.0.capacity() > 128
        || !binding.tenant.0.is_ascii()
        || binding
            .tenant
            .0
            .bytes()
            .any(|b| b.is_ascii_control() || b.is_ascii_whitespace())
        || binding.receipt.is_empty()
        || binding.receipt.capacity() > limits.max_receipt_bytes
    {
        return Err(resource_exhausted("web-binding-size"));
    }
    Ok(())
}

/// Independent repository association check. Host-injected authority still owns
/// renderer semantics, cryptography, time and policy; its data cannot substitute
/// a different blob set or layout after verification.
pub(super) fn check_upload(
    binding: &WebAdmissionBinding,
    upload: &mut PackageAdmissionUpload,
    limits: AdmissionStorageLimits,
    component_limit: usize,
) -> Result<CheckedWebLayout, PlatformError> {
    check_binding(binding, limits)?;
    limits.check_upload(upload, renderer_limit(component_limit)?)?;
    let package = inspect_package(
        &upload.manifest,
        &upload.configuration,
        PackageLimits::default(),
    )?;
    if package.digest() != &binding.package || upload.layers.len() != package.config().layers.len()
    {
        return Err(corrupt("web-package-association"));
    }
    upload.layers.sort_by(|a, b| a.0.cmp(&b.0));
    for ((path, bytes), layer) in upload.layers.iter().zip(&package.config().layers) {
        if path != &layer.path {
            return Err(corrupt("web-package-layer-set"));
        }
        verify_layer_bytes(layer, bytes, PackageLimits::default())?;
    }
    let (_, bytes) = upload
        .layers
        .iter()
        .find(|(path, _)| path == WEB_MANIFEST_PATH)
        .ok_or_else(|| corrupt("web-manifest-missing"))?;
    let layout = inspect_web_layout(&package, bytes)?;
    if layout.manifest_digest() != &binding.manifest || layout.assets_digest() != &binding.assets {
        return Err(corrupt("web-layout-association"));
    }
    Ok(layout)
}

pub(super) fn renderer_limit(configured: usize) -> Result<usize, PlatformError> {
    Ok(configured.min(
        usize::try_from(MAX_WEB_RENDERER_BYTES)
            .map_err(|_| resource_exhausted("web-renderer-size"))?,
    ))
}

impl Stored {
    fn blobs(&self) -> impl Iterator<Item = &Blob> {
        [&self.receipt, &self.manifest, &self.configuration]
            .into_iter()
            .chain(self.layers.iter().map(|layer| &layer.blob))
            .chain(
                [&self.signatures, &self.provenance, &self.sboms]
                    .into_iter()
                    .flat_map(|kind| {
                        kind.iter().flat_map(|entry| {
                            [&entry.manifest, &entry.configuration, &entry.payload]
                        })
                    }),
            )
    }
    fn tenant(&self) -> Result<&TenantId, PlatformError> {
        self.publication
            .scope
            .tenant()
            .ok_or_else(|| corrupt("web-publication-scope"))
    }
}
