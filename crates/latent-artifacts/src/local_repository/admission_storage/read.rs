use std::collections::BTreeSet;
use std::fs::{self, File};
use std::io::Read;
use std::path::Path;

use latent_core::{PlatformError, ReleaseDigest};
use sha2::{Digest, Sha256};

use super::super::{
    corrupt, read_bounded_file, resource_exhausted, COMPLETE_FILE, COMPONENT_FILE, MANIFEST_FILE,
    METADATA_FILE,
};
use super::{Blob, Evidence, StoredAdmission, RECORD_FILE};
use crate::package::{validate_package_json, validate_package_path, PackageLimits};
use crate::{
    content_digest, AdmissionBinding, AdmissionEvidence, AdmissionStorageLimits,
    PackageAdmissionUpload,
};

impl StoredAdmission {
    pub(in crate::local_repository) fn read(
        directory: &Path,
        expected: &str,
        limits: AdmissionStorageLimits,
        component_limit: usize,
    ) -> Result<Self, PlatformError> {
        regular(&directory.join(RECORD_FILE))?;
        let bytes = read_bounded_file(
            &directory.join(RECORD_FILE),
            limits.max_document_bytes,
            "admission record",
        )?;
        if content_digest(&bytes).0 != expected {
            return Err(corrupt("admission-record-digest"));
        }
        validate_package_json(
            &bytes,
            PackageLimits {
                max_document_bytes: limits.max_document_bytes,
                max_nodes: 8192,
                max_depth: 8,
                max_layers: limits.max_layers,
                ..PackageLimits::default()
            },
        )?;
        let value: Self =
            serde_json::from_slice(&bytes).map_err(|_| corrupt("invalid-admission-record"))?;
        if value.format_version != 1
            || serde_json::to_vec(&value).map_err(|_| corrupt("invalid-admission-record"))? != bytes
            || value.layers.len() > limits.max_layers
            || [&value.signatures, &value.provenance, &value.sboms]
                .iter()
                .any(|items| items.len() > limits.max_evidence_per_kind)
        {
            return Err(corrupt("invalid-admission-record"));
        }
        let seen = value.validate_shape(limits, component_limit)?;
        let maximum_files = seen.len() + 4;
        let mut count = 0;
        for entry in fs::read_dir(directory).map_err(|_| corrupt("admission-directory-read"))? {
            let entry = entry.map_err(|_| corrupt("admission-directory-read"))?;
            count += 1;
            if count > maximum_files {
                return Err(corrupt("unexpected-admission-file"));
            }
            let name = entry.file_name();
            let name = name
                .to_str()
                .ok_or_else(|| corrupt("invalid-admission-file-name"))?;
            if !seen.contains(name)
                && ![RECORD_FILE, COMPLETE_FILE, MANIFEST_FILE, METADATA_FILE].contains(&name)
            {
                return Err(corrupt("unexpected-admission-file"));
            }
        }
        for blob in value.blobs() {
            // The enclosing catalog reader always streams and verifies the one
            // component against COMPLETE immediately after this side record.
            // Recovery additionally checks this blob's package association.
            if blob.file == COMPONENT_FILE {
                regular(&directory.join(COMPONENT_FILE))?;
            } else {
                verify(directory, blob)?;
            }
        }
        let binding = value.binding(directory, limits)?;
        limits.check_binding(&binding)?;
        Ok(value)
    }

    fn validate_shape(
        &self,
        limits: AdmissionStorageLimits,
        component_limit: usize,
    ) -> Result<BTreeSet<&str>, PlatformError> {
        let mut seen = BTreeSet::new();
        let mut auxiliary = 0_usize;
        let mut components = 0;
        let mut paths = BTreeSet::new();
        for layer in &self.layers {
            validate_package_path(&layer.path, PackageLimits::default())?;
            if !paths.insert(&layer.path) {
                return Err(corrupt("duplicate-admission-layer"));
            }
        }
        for blob in self.blobs() {
            if !seen.insert(blob.file.as_str()) {
                return Err(corrupt("duplicate-admission-file"));
            }
            let size = usize::try_from(blob.size)
                .map_err(|_| resource_exhausted("admission-file-size"))?;
            if blob.file == COMPONENT_FILE {
                components += 1;
                if size > component_limit {
                    return Err(resource_exhausted("admission-component-size"));
                }
            } else {
                let index = blob
                    .file
                    .strip_prefix("admission-")
                    .and_then(|name| name.strip_suffix(".bin"))
                    .filter(|name| name.len() == 4 && name.bytes().all(|b| b.is_ascii_digit()))
                    .and_then(|name| name.parse::<usize>().ok())
                    .ok_or_else(|| corrupt("invalid-admission-file-name"))?;
                if index >= 3 + limits.max_layers + 9 * limits.max_evidence_per_kind {
                    return Err(corrupt("invalid-admission-file-index"));
                }
                auxiliary = auxiliary
                    .checked_add(size)
                    .ok_or_else(|| resource_exhausted("admission-auxiliary-size"))?;
            }
            if blob
                .digest
                .parse::<latent_core::ArtifactBlobDigest>()
                .is_err()
            {
                return Err(corrupt("invalid-admission-file-digest"));
            }
        }
        if components != 1
            || auxiliary > limits.max_auxiliary_bytes
            || self.receipt.size > limits.max_receipt_bytes as u64
            || self.manifest.size > limits.max_document_bytes as u64
            || self.configuration.size > limits.max_document_bytes as u64
        {
            return Err(resource_exhausted("admission-storage-limit"));
        }
        for kind in [&self.signatures, &self.provenance, &self.sboms] {
            if kind.iter().any(|item| {
                item.manifest.size > limits.max_document_bytes as u64
                    || item.configuration.size > limits.max_document_bytes as u64
            }) {
                return Err(resource_exhausted("admission-evidence-document-limit"));
            }
        }
        Ok(seen)
    }

    pub(in crate::local_repository) fn binding(
        &self,
        directory: &Path,
        limits: AdmissionStorageLimits,
    ) -> Result<AdmissionBinding, PlatformError> {
        Ok(AdmissionBinding {
            tenant: latent_core::TenantId(self.tenant.clone()),
            package: self
                .package
                .parse()
                .map_err(|_| corrupt("admission-package-digest"))?,
            release: ReleaseDigest(self.release.clone()),
            receipt: read_blob(directory, &self.receipt, limits.max_receipt_bytes)?,
        })
    }

    pub(in crate::local_repository) fn upload(
        &self,
        directory: &Path,
        limits: AdmissionStorageLimits,
        component_limit: usize,
    ) -> Result<PackageAdmissionUpload, PlatformError> {
        let mut layers = Vec::with_capacity(self.layers.len());
        for layer in &self.layers {
            let maximum = if layer.blob.file == COMPONENT_FILE {
                component_limit
            } else {
                limits.max_auxiliary_bytes
            };
            layers.push((
                layer.path.clone(),
                read_blob(directory, &layer.blob, maximum)?,
            ));
        }
        let value = PackageAdmissionUpload {
            manifest: read_blob(directory, &self.manifest, limits.max_document_bytes)?,
            configuration: read_blob(directory, &self.configuration, limits.max_document_bytes)?,
            layers,
            signatures: read_evidence(directory, &self.signatures, limits)?,
            provenance: read_evidence(directory, &self.provenance, limits)?,
            sboms: read_evidence(directory, &self.sboms, limits)?,
        };
        limits.check_upload(&value, component_limit)?;
        Ok(value)
    }

    /// Reads only immutable package content. Detached policy evidence is neither
    /// retained nor returned to a structural comparison consumer.
    pub(in crate::local_repository) fn package_input(
        &self,
        directory: &Path,
        maximum_bytes: usize,
    ) -> Result<PackageAdmissionUpload, PlatformError> {
        // Reserve conservative collection/identity space before allocating raw
        // bytes. Each read uses the recorded exact size as its growth ceiling.
        let mut charge = 2048_usize
            .checked_add(
                self.layers
                    .len()
                    .saturating_mul(std::mem::size_of::<(String, Vec<u8>)>()),
            )
            .ok_or_else(|| resource_exhausted("package-source-retention-limit"))?;
        for layer in &self.layers {
            charge = charge
                .checked_add(layer.path.len())
                .filter(|value| *value <= maximum_bytes)
                .ok_or_else(|| resource_exhausted("package-source-retention-limit"))?;
        }
        for blob in [&self.manifest, &self.configuration]
            .into_iter()
            .chain(self.layers.iter().map(|layer| &layer.blob))
        {
            let size = usize::try_from(blob.size)
                .map_err(|_| resource_exhausted("package-source-byte-limit"))?;
            charge = charge
                .checked_add(size)
                .filter(|value| *value <= maximum_bytes)
                .ok_or_else(|| resource_exhausted("package-source-retention-limit"))?;
        }
        let read = |blob: &Blob| {
            let limit = usize::try_from(blob.size)
                .map_err(|_| resource_exhausted("package-source-byte-limit"))?;
            read_blob(directory, blob, limit)
        };
        let layers = self
            .layers
            .iter()
            .map(|layer| Ok((layer.path.clone(), read(&layer.blob)?)))
            .collect::<Result<Vec<_>, PlatformError>>()?;
        Ok(PackageAdmissionUpload {
            manifest: read(&self.manifest)?,
            configuration: read(&self.configuration)?,
            layers,
            signatures: Vec::new(),
            provenance: Vec::new(),
            sboms: Vec::new(),
        })
    }

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
}

fn regular(path: &Path) -> Result<(), PlatformError> {
    let metadata = fs::symlink_metadata(path).map_err(|_| corrupt("missing-admission-file"))?;
    if !metadata.file_type().is_file() {
        return Err(corrupt("invalid-admission-file-type"));
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err(corrupt("linked-admission-file"));
        }
    }
    Ok(())
}
fn verify(directory: &Path, blob: &Blob) -> Result<(), PlatformError> {
    let path = directory.join(&blob.file);
    regular(&path)?;
    let mut file = File::open(path).map_err(|_| corrupt("missing-admission-file"))?;
    if file
        .metadata()
        .map_err(|_| corrupt("admission-file-metadata"))?
        .len()
        != blob.size
    {
        return Err(corrupt("admission-file-size-mismatch"));
    }
    let mut hash = Sha256::new();
    let mut total = 0_u64;
    let mut scratch = [0_u8; 16 * 1024];
    loop {
        let count = file
            .read(&mut scratch)
            .map_err(|_| corrupt("admission-file-read"))?;
        if count == 0 {
            break;
        }
        total = total
            .checked_add(count as u64)
            .filter(|size| *size <= blob.size)
            .ok_or_else(|| corrupt("admission-file-growth"))?;
        hash.update(&scratch[..count]);
    }
    if total != blob.size || format!("sha256:{:x}", hash.finalize()) != blob.digest {
        return Err(corrupt("admission-file-digest-mismatch"));
    }
    Ok(())
}
fn read_blob(directory: &Path, blob: &Blob, limit: usize) -> Result<Vec<u8>, PlatformError> {
    regular(&directory.join(&blob.file))?;
    let bytes = read_bounded_file(&directory.join(&blob.file), limit, "admission material")?;
    if bytes.len() as u64 != blob.size || content_digest(&bytes).0 != blob.digest {
        return Err(corrupt("admission-file-digest-mismatch"));
    }
    Ok(bytes)
}
fn read_evidence(
    directory: &Path,
    entries: &[Evidence],
    limits: AdmissionStorageLimits,
) -> Result<Vec<AdmissionEvidence>, PlatformError> {
    entries
        .iter()
        .map(|entry| {
            Ok(AdmissionEvidence {
                manifest: read_blob(directory, &entry.manifest, limits.max_document_bytes)?,
                configuration: read_blob(
                    directory,
                    &entry.configuration,
                    limits.max_document_bytes,
                )?,
                payload: read_blob(directory, &entry.payload, limits.max_auxiliary_bytes)?,
            })
        })
        .collect()
}
