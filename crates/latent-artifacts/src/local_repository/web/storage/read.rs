use super::super::super::{
    admission_storage::read::{read_blob, read_evidence, verify},
    read_bounded_file, shared_content,
};
use super::{
    check_binding, corrupt, renderer_limit, resource_exhausted, AdmissionStorageLimits,
    PackageAdmissionUpload, PackageLimits, PlatformError, PublicationRef, Stored,
    WebAdmissionBinding, COMPLETE, RECORD,
};
use crate::package::{artifact_blob_digest, validate_package_json};
use latent_core::ArtifactBlobDigest;
use std::{collections::BTreeSet, path::Path};

impl Stored {
    pub(in crate::local_repository::web) fn read(
        directory: &Path,
        limits: AdmissionStorageLimits,
        component_limit: usize,
    ) -> Result<Self, PlatformError> {
        let record = Self::read_header(directory, limits, component_limit)?;
        for blob in record.blobs() {
            verify(directory, blob)?;
        }
        Ok(record)
    }

    /// Already sealed catalog metadata anchors this header on the asset path.
    /// Only the selected payload is read there; admission/recovery verify all.
    pub(in crate::local_repository::web) fn read_header(
        directory: &Path,
        limits: AdmissionStorageLimits,
        component_limit: usize,
    ) -> Result<Self, PlatformError> {
        limits.validate()?;
        shared_content::directory(directory)?;
        shared_content::regular(&directory.join(RECORD))?;
        shared_content::regular(&directory.join(COMPLETE))?;
        let bytes = read_bounded_file(
            &directory.join(RECORD),
            limits.max_document_bytes,
            "web record",
        )?;
        let completion = read_bounded_file(&directory.join(COMPLETE), 71, "web completion")?;
        if completion != artifact_blob_digest(&bytes).as_str().as_bytes() {
            return Err(corrupt("web-completion-mismatch"));
        }
        validate_package_json(
            &bytes,
            PackageLimits {
                max_document_bytes: limits.max_document_bytes,
                max_nodes: 8192,
                max_depth: 8,
                ..PackageLimits::default()
            },
        )?;
        let record: Self =
            serde_json::from_slice(&bytes).map_err(|_| corrupt("web-record-shape"))?;
        if record.format_version != 1
            || serde_json::to_vec(&record).map_err(|_| corrupt("web-record-shape"))? != bytes
        {
            return Err(corrupt("web-record-version"));
        }
        let seen = record.check_shape(limits, component_limit)?;
        let mut count = 0;
        for entry in std::fs::read_dir(directory).map_err(|_| corrupt("web-directory-read"))? {
            count += 1;
            if count > seen.len() + 2 {
                return Err(corrupt("unexpected-web-file"));
            }
            let entry = entry.map_err(|_| corrupt("web-directory-read"))?;
            let name = entry.file_name();
            let name = name
                .to_str()
                .ok_or_else(|| corrupt("unexpected-web-file"))?;
            if !seen.contains(name) && name != RECORD && name != COMPLETE {
                return Err(corrupt("unexpected-web-file"));
            }
        }
        if count != seen.len() + 2 {
            return Err(corrupt("missing-web-file"));
        }
        Ok(record)
    }

    pub(super) fn check_shape(
        &self,
        limits: AdmissionStorageLimits,
        component_limit: usize,
    ) -> Result<BTreeSet<&str>, PlatformError> {
        if self.layers.is_empty()
            || self.layers.len() > limits.max_layers
            || self.signatures.len() != 1
            || self.provenance.len() != 1
            || self.sboms.len() > limits.max_evidence_per_kind
        {
            return Err(corrupt("web-record-count"));
        }
        let package = self
            .package
            .parse()
            .map_err(|_| corrupt("web-package-digest"))?;
        if self.publication != PublicationRef::package(self.publication.scope.clone(), &package)?
            || self.tenant()?.0.len() > 128
        {
            return Err(corrupt("web-publication-association"));
        }
        for value in [&self.web_manifest, &self.assets] {
            value
                .parse::<ArtifactBlobDigest>()
                .map_err(|_| corrupt("web-association-digest"))?;
        }
        let maximum = renderer_limit(component_limit)?
            .checked_add(limits.max_auxiliary_bytes)
            .and_then(|n| n.checked_add(limits.max_receipt_bytes))
            .ok_or_else(|| resource_exhausted("web-storage-size"))?;
        let mut total = 0usize;
        let mut seen = BTreeSet::new();
        for (index, blob) in self.blobs().enumerate() {
            if blob.file != format!("admission-{index:04}.bin") {
                return Err(corrupt("web-file-order"));
            }
            seen.insert(blob.file.as_str());
            blob.digest
                .parse::<ArtifactBlobDigest>()
                .map_err(|_| corrupt("web-file-digest"))?;
            total = total
                .checked_add(
                    usize::try_from(blob.size).map_err(|_| resource_exhausted("web-file-size"))?,
                )
                .filter(|n| *n <= maximum)
                .ok_or_else(|| resource_exhausted("web-storage-size"))?;
        }
        if self.receipt.size > limits.max_receipt_bytes as u64
            || self.manifest.size > limits.max_document_bytes as u64
            || self.configuration.size > limits.max_document_bytes as u64
        {
            return Err(resource_exhausted("web-document-size"));
        }
        for entry in self
            .signatures
            .iter()
            .chain(&self.provenance)
            .chain(&self.sboms)
        {
            if entry.manifest.size > limits.max_document_bytes as u64
                || entry.configuration.size > limits.max_document_bytes as u64
                || entry.payload.size > limits.max_auxiliary_bytes as u64
            {
                return Err(resource_exhausted("web-evidence-size"));
            }
        }
        let mut previous: Option<&str> = None;
        for layer in &self.layers {
            crate::package::validate_package_path(&layer.path, PackageLimits::default())?;
            if previous.is_some_and(|path| path >= layer.path.as_str()) {
                return Err(corrupt("web-layer-order"));
            }
            previous = Some(&layer.path);
        }
        Ok(seen)
    }

    pub(in crate::local_repository::web) fn binding(
        &self,
        directory: &Path,
        limits: AdmissionStorageLimits,
    ) -> Result<WebAdmissionBinding, PlatformError> {
        let binding = WebAdmissionBinding {
            tenant: self.tenant()?.clone(),
            package: self
                .package
                .parse()
                .map_err(|_| corrupt("web-package-digest"))?,
            manifest: self
                .web_manifest
                .parse()
                .map_err(|_| corrupt("web-manifest-digest"))?,
            assets: self
                .assets
                .parse()
                .map_err(|_| corrupt("web-assets-digest"))?,
            receipt: read_blob(directory, &self.receipt, limits.max_receipt_bytes)?,
        };
        check_binding(&binding, limits)?;
        Ok(binding)
    }

    pub(in crate::local_repository::web) fn upload(
        &self,
        directory: &Path,
        limits: AdmissionStorageLimits,
        component_limit: usize,
    ) -> Result<PackageAdmissionUpload, PlatformError> {
        self.check_shape(limits, component_limit)?;
        let mut layers = Vec::with_capacity(self.layers.len());
        for layer in &self.layers {
            let size = usize::try_from(layer.blob.size)
                .map_err(|_| resource_exhausted("web-layer-size"))?;
            layers.push((layer.path.clone(), read_blob(directory, &layer.blob, size)?));
        }
        let upload = PackageAdmissionUpload {
            manifest: read_blob(directory, &self.manifest, limits.max_document_bytes)?,
            configuration: read_blob(directory, &self.configuration, limits.max_document_bytes)?,
            layers,
            signatures: read_evidence(directory, &self.signatures, limits)?,
            provenance: read_evidence(directory, &self.provenance, limits)?,
            sboms: read_evidence(directory, &self.sboms, limits)?,
        };
        limits.check_upload(&upload, renderer_limit(component_limit)?)?;
        Ok(upload)
    }
}
