//! Actual persisted storage reads and independent package associations. The
//! configured test authority does not establish cryptographic guest validity.
use super::*;
use crate::local_repository::{
    admission::association,
    admission_storage::{StoredAdmission, RECORD_FILE},
    integrity::CompletionRecord,
    Retention, COMPLETE_FILE,
};
use crate::{content_digest, VerifiedArtifactMetadata};
use latent_manifest::JsonManifestCodec;
use serde_json::Value;
use std::{fs, path::PathBuf};

struct Disk {
    _root: TempRoot,
    directory: PathBuf,
    record: Value,
    binding: AdmissionBinding,
    metadata: VerifiedArtifactMetadata,
}

impl Disk {
    fn new() -> Self {
        let root = TempRoot::new();
        let owner = Authority::new();
        let repo = open(&root, &owner);
        let summary = admit(&repo).unwrap();
        let directory = release_dir(root.path(), &summary.descriptor.release_digest);
        let verified = repo
            .load_complete_entry(&directory, Retention::Metadata)
            .unwrap();
        let binding = verified
            .admission
            .as_ref()
            .unwrap()
            .binding(&directory, AdmissionStorageLimits::default())
            .unwrap();
        let record =
            serde_json::from_slice(&fs::read(directory.join(RECORD_FILE)).unwrap()).unwrap();
        drop(repo);
        Self {
            _root: root,
            directory,
            record,
            binding,
            metadata: verified.metadata,
        }
    }

    fn stored(&self) -> StoredAdmission {
        // Recompute the real canonical side record and outer completion binding.
        // The association tests deliberately isolate the next read/association
        // boundary, rather than reopening the entire shared-content catalog.
        let record: StoredAdmission = serde_json::from_value(self.record.clone()).unwrap();
        let bytes = serde_json::to_vec(&record).unwrap();
        fs::write(self.directory.join(RECORD_FILE), &bytes).unwrap();
        let mut completion = CompletionRecord::read(&self.directory).unwrap();
        completion.bind_admission(&bytes);
        fs::write(
            self.directory.join(COMPLETE_FILE),
            completion.encode().unwrap(),
        )
        .unwrap();
        let completion = CompletionRecord::read(&self.directory).unwrap();
        StoredAdmission::read(
            &self.directory,
            completion.admission_digest().unwrap(),
            AdmissionStorageLimits::default(),
            DirectoryArtifactRepositoryConfig::default().max_component_bytes,
        )
        .unwrap()
    }

    fn replace_blob(&mut self, pointer: &str, bytes: &[u8]) {
        let blob = self.record.pointer_mut(pointer).unwrap();
        let file = blob["file"].as_str().unwrap();
        fs::write(self.directory.join(file), bytes).unwrap();
        blob["size"] = u64::try_from(bytes.len()).unwrap().into();
        blob["digest"] = content_digest(bytes).0.into();
    }

    fn association_errors(
        &self,
        stored: &StoredAdmission,
        binding: &AdmissionBinding,
    ) -> PlatformError {
        let limits = AdmissionStorageLimits::default();
        let maximum = DirectoryArtifactRepositoryConfig::default().max_component_bytes;
        let raw = stored.upload(&self.directory, limits, maximum).unwrap();
        let original =
            association::verify(binding, &raw, &self.metadata, &JsonManifestCodec::default())
                .err()
                .unwrap();
        let checked = stored
            .checked_upload(&self.directory, limits, maximum)
            .unwrap();
        let current = association::verify_checked(
            binding,
            checked,
            &self.metadata,
            &JsonManifestCodec::default(),
        )
        .err()
        .unwrap();
        assert_eq!(current.code, original.code);
        assert_eq!(current.message, original.message);
        assert_eq!(current.retryable, original.retryable);
        assert!(current.details.is_empty() && original.details.is_empty());
        current
    }
}

#[test]
fn checked_storage_bytes_keep_owned_buffers_and_raw_mutations_require_fresh_hashes() {
    let disk = Disk::new();
    let stored = disk.stored();
    let checked = stored
        .checked_upload(
            &disk.directory,
            AdmissionStorageLimits::default(),
            DirectoryArtifactRepositoryConfig::default().max_component_bytes,
        )
        .unwrap();
    let component = checked.as_upload().layers[0].1.as_ptr();
    let capacity = checked.as_upload().layers[0].1.capacity();
    let mut value = association::verify_checked(
        &disk.binding,
        checked,
        &disk.metadata,
        &JsonManifestCodec::default(),
    )
    .unwrap();
    let expected = upload();
    assert_eq!(value.manifest, expected.manifest);
    assert_eq!(value.configuration, expected.configuration);
    assert_eq!(value.layers, expected.layers);
    assert_eq!(value.layers[0].1.as_ptr(), component);
    assert_eq!(value.layers[0].1.capacity(), capacity);
    value.layers[0].1[0] ^= 1;
    let error = association::verify(
        &disk.binding,
        &value,
        &disk.metadata,
        &JsonManifestCodec::default(),
    )
    .unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
    assert_eq!(error.message, "package-layer-content-mismatch");
}

#[test]
fn recomputed_storage_and_completion_digests_cannot_replace_package_layer_identity() {
    for case in 0..4 {
        let mut disk = Disk::new();
        if case == 3 {
            disk.record["layers"][0]["path"] = "wrong.wasm".into();
        } else {
            let index = if case == 1 { 3 } else { 0 };
            let mut bytes = upload().layers[index].1.clone();
            if case == 2 {
                bytes.push(0);
            } else {
                bytes[0] ^= 1;
            }
            disk.replace_blob(&format!("/layers/{index}/blob"), &bytes);
        }
        let stored = disk.stored();
        let error = disk.association_errors(&stored, &disk.binding);
        assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
        assert_eq!(
            error.message,
            if case == 3 {
                "retained-package-layer-set"
            } else {
                "package-layer-content-mismatch"
            }
        );
    }
}

#[test]
fn checked_storage_proof_cannot_cross_package_release_or_embedded_tenant_binding() {
    let disk = Disk::new();
    assert!(disk.metadata.manifest().metadata.tenant.is_some());
    let stored = disk.stored();
    for case in 0..3 {
        let mut changed = disk.binding.clone();
        match case {
            0 => changed.package = format!("sha256:{}", "0".repeat(64)).parse().unwrap(),
            1 => changed.release.0 = format!("sha256:{}", "0".repeat(64)),
            _ => changed.tenant.0 = "foreign".to_owned(),
        }
        let error = disk.association_errors(&stored, &changed);
        assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
        assert_eq!(error.message, "retained-package-association");
    }
}

#[test]
fn checked_storage_association_preserves_field_limits_paths_and_evidence_refusals() {
    for case in 0..4 {
        let mut disk = Disk::new();
        if case == 3 {
            disk.replace_blob("/signatures/0/payload", b"changed evidence");
        } else {
            let expected = upload();
            let mut configuration: Value = serde_json::from_slice(&expected.configuration).unwrap();
            let mut manifest: Value = serde_json::from_slice(&expected.manifest).unwrap();
            match case {
                0 => {
                    configuration["layers"][0]["mediaType"] = "text/plain".into();
                    manifest["layers"][0]["mediaType"] = "text/plain".into();
                }
                1 => {
                    let size = crate::package::PackageLimits::default().max_layer_bytes + 1;
                    configuration["layers"][0]["size"] = size.into();
                    manifest["layers"][0]["size"] = size.into();
                }
                _ => {
                    configuration["layers"][0]["path"] = "../escape.wasm".into();
                    manifest["layers"][0]["annotations"]["org.opencontainers.image.title"] =
                        "../escape.wasm".into();
                }
            }
            let configuration = serde_json::to_vec(&configuration).unwrap();
            manifest["config"]["digest"] = content_digest(&configuration).0.into();
            manifest["config"]["size"] = u64::try_from(configuration.len()).unwrap().into();
            let manifest = serde_json::to_vec(&manifest).unwrap();
            disk.replace_blob("/configuration", &configuration);
            disk.replace_blob("/manifest", &manifest);
        }
        let stored = disk.stored();
        let error = disk.association_errors(&stored, &disk.binding);
        if case == 1 {
            assert_eq!(error.code, PlatformErrorCode::ResourceExhausted);
            assert_eq!(error.message, "package-layer-size-limit");
        } else if case == 3 {
            assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
            assert_eq!(error.message, "retained-evidence-association");
        } else {
            assert_eq!(error.code, PlatformErrorCode::InvalidArgument);
        }
    }
}

#[test]
fn checked_upload_keeps_fresh_file_digest_and_component_capacity_failures() {
    let disk = Disk::new();
    let stored = disk.stored();
    let limits = AdmissionStorageLimits::default();
    let maximum = DirectoryArtifactRepositoryConfig::default().max_component_bytes;
    let too_small = upload().layers[0].1.len() - 1;
    let raw = stored
        .upload(&disk.directory, limits, too_small)
        .err()
        .unwrap();
    let checked = stored
        .checked_upload(&disk.directory, limits, too_small)
        .err()
        .unwrap();
    assert_eq!(raw.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(checked.code, raw.code);
    assert_eq!(checked.message, raw.message);
    let component = disk.record["layers"][0]["blob"]["file"].as_str().unwrap();
    let mut bytes = fs::read(disk.directory.join(component)).unwrap();
    bytes[0] ^= 1;
    fs::write(disk.directory.join(component), bytes).unwrap();
    let error = stored
        .checked_upload(&disk.directory, limits, maximum)
        .err()
        .unwrap();
    assert_eq!(error.code, PlatformErrorCode::CorruptArtifact);
    assert_eq!(error.message, "admission-file-digest-mismatch");
}
