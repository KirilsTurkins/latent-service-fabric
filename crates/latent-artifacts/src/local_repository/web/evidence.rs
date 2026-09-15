use super::super::admission_storage::read::{read_blob, read_evidence, verify};
use super::super::admission_storage::{add, evidence, Blob, Evidence};
use super::{
    capacity, corrupt, fs, io_error, persistence, read_bounded_file, shared_content, storage,
    sync_dir, write_synced, ArtifactBlobDigest, DirectoryArtifactRepository, Path, PathBuf,
    PlatformError, PublicationRef, State, VerifiedWebAdmission, WebAdmissionBinding, EVIDENCE,
};
use crate::{package::artifact_blob_digest, AdmissionStorageLimits, PackageAdmissionUpload};
use serde::{Deserialize, Serialize};

const RECORD: &str = "revision.json";
const COMPLETE: &str = "COMPLETE";

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Revision {
    format_version: u32,
    publication: PublicationRef,
    #[serde(with = "crate::web::codec::blob")]
    original: ArtifactBlobDigest,
    receipt: Blob,
    signatures: Vec<Evidence>,
    provenance: Vec<Evidence>,
    sboms: Vec<Evidence>,
}
pub(super) struct PreparedEvidence {
    pub(super) digest: ArtifactBlobDigest,
    files: Vec<(String, Vec<u8>)>,
    pub(super) bytes: u64,
}
impl PreparedEvidence {
    pub(super) fn new(
        reference: &PublicationRef,
        original: &ArtifactBlobDigest,
        value: VerifiedWebAdmission,
        limits: AdmissionStorageLimits,
        maximum: usize,
    ) -> Result<Self, PlatformError> {
        let mut files = Vec::new();
        let record = Revision {
            format_version: 1,
            publication: reference.clone(),
            original: original.clone(),
            receipt: add(&mut files, value.grant.binding().receipt.clone()),
            signatures: evidence(&mut files, value.upload.signatures),
            provenance: evidence(&mut files, value.upload.provenance),
            sboms: evidence(&mut files, value.upload.sboms),
        };
        record.validate(limits, maximum)?;
        let encoded = persistence::encode_line(&record, limits.max_document_bytes)?;
        let digest = artifact_blob_digest(&encoded);
        files.push((RECORD.into(), encoded));
        files.push((COMPLETE.into(), digest.as_str().as_bytes().to_vec()));
        let bytes = files
            .iter()
            .try_fold(0usize, |n, (_, bytes)| n.checked_add(bytes.len()))
            .filter(|n| *n <= maximum)
            .ok_or_else(capacity)?;
        Ok(Self {
            digest,
            files,
            bytes: bytes as u64,
        })
    }
    pub(super) fn stage(&self, root: &Path) -> Result<(), PlatformError> {
        fs::create_dir(root).map_err(io_error)?;
        for (name, bytes) in &self.files {
            write_synced(&root.join(name), bytes)?;
        }
        sync_dir(root)?;
        sync_dir(
            root.parent()
                .ok_or_else(|| corrupt("web-evidence-parent"))?,
        )
    }
}
impl Revision {
    fn blobs(&self) -> impl Iterator<Item = &Blob> {
        std::iter::once(&self.receipt).chain(
            self.signatures
                .iter()
                .chain(&self.provenance)
                .chain(&self.sboms)
                .flat_map(|e| [&e.manifest, &e.configuration, &e.payload]),
        )
    }
    fn validate(
        &self,
        limits: AdmissionStorageLimits,
        maximum: usize,
    ) -> Result<(), PlatformError> {
        if self.format_version != 1
            || self.signatures.len() != 1
            || self.provenance.len() != 1
            || self.sboms.len() > limits.max_evidence_per_kind
            || self.receipt.size > limits.max_receipt_bytes as u64
        {
            return Err(corrupt("web-evidence-shape"));
        }
        let mut total = 0u64;
        for (index, blob) in self.blobs().enumerate() {
            if blob.file != format!("admission-{index:04}.bin") {
                return Err(corrupt("web-evidence-file-order"));
            }
            blob.digest
                .parse::<ArtifactBlobDigest>()
                .map_err(|_| corrupt("web-evidence-file-digest"))?;
            total = total
                .checked_add(blob.size)
                .filter(|n| *n <= maximum as u64)
                .ok_or_else(capacity)?;
        }
        for e in self
            .signatures
            .iter()
            .chain(&self.provenance)
            .chain(&self.sboms)
        {
            if e.manifest.size > limits.max_document_bytes as u64
                || e.configuration.size > limits.max_document_bytes as u64
                || e.payload.size > limits.max_auxiliary_bytes as u64
            {
                return Err(capacity());
            }
        }
        Ok(())
    }
}
impl DirectoryArtifactRepository {
    pub(super) fn web_evidence_path(&self, digest: &ArtifactBlobDigest) -> PathBuf {
        self.web_path().join(EVIDENCE).join(&digest.as_str()[7..])
    }
    pub(super) fn read_web_revision(
        &self,
        reference: &PublicationRef,
        digest: &ArtifactBlobDigest,
        completion: &ArtifactBlobDigest,
    ) -> Result<(WebAdmissionBinding, PackageAdmissionUpload), PlatformError> {
        let revision = self.web_revision(digest)?;
        if revision.publication != *reference || &revision.original != completion {
            return Err(corrupt("web-evidence-original-association"));
        }
        let original = self.web_storage(reference)?;
        if original.digest()? != *completion {
            return Err(corrupt("web-evidence-original-changed"));
        }
        let config = self.web_authority()?;
        let mut binding =
            original.binding(&self.web_publication_path(&reference.id), config.limits)?;
        let mut upload = original.upload(
            &self.web_publication_path(&reference.id),
            config.limits,
            self.config.max_component_bytes,
        )?;
        let root = self.web_evidence_path(digest);
        binding.receipt = read_blob(&root, &revision.receipt, config.limits.max_receipt_bytes)?;
        upload.signatures = read_evidence(&root, &revision.signatures, config.limits)?;
        upload.provenance = read_evidence(&root, &revision.provenance, config.limits)?;
        upload.sboms = read_evidence(&root, &revision.sboms, config.limits)?;
        storage::check_upload(
            &binding,
            &mut upload,
            config.limits,
            self.config.max_component_bytes,
        )?;
        Ok((binding, upload))
    }
    fn web_revision(&self, digest: &ArtifactBlobDigest) -> Result<Revision, PlatformError> {
        let root = self.web_evidence_path(digest);
        let config = self.web_authority()?;
        let files = shared_content::bounded_files(&root, self.config)?;
        let total = files
            .iter()
            .try_fold(0u64, |n, (_, size)| n.checked_add(*size))
            .filter(|n| *n <= self.lifecycle_limits.max_evidence_revision_bytes as u64)
            .ok_or_else(capacity)?;
        let _ = total;
        let bytes = read_bounded_file(
            &root.join(RECORD),
            config.limits.max_document_bytes,
            "web evidence record",
        )?;
        if artifact_blob_digest(&bytes) != *digest
            || read_bounded_file(&root.join(COMPLETE), 71, "web evidence completion")?
                != digest.as_str().as_bytes()
        {
            return Err(corrupt("web-evidence-completion"));
        }
        crate::package::validate_package_json(&bytes, crate::package::PackageLimits::default())?;
        let revision: Revision =
            serde_json::from_slice(&bytes).map_err(|_| corrupt("web-evidence-record"))?;
        if persistence::encode_line(&revision, config.limits.max_document_bytes)? != bytes {
            return Err(corrupt("web-evidence-noncanonical"));
        }
        revision.validate(
            config.limits,
            self.lifecycle_limits.max_evidence_revision_bytes,
        )?;
        if files.len() != revision.blobs().count() + 2 {
            return Err(corrupt("web-evidence-file-set"));
        }
        for blob in revision.blobs() {
            verify(&root, blob)?;
        }
        Ok(revision)
    }
    pub(super) fn recover_web_evidence(&self, state: &mut State) -> Result<(), PlatformError> {
        for entry in fs::read_dir(self.web_path().join(EVIDENCE)).map_err(io_error)? {
            let entry = entry.map_err(io_error)?;
            if !state.enabled {
                return Err(corrupt("web-evidence-without-mode"));
            }
            state.evidence_directories = state
                .evidence_directories
                .checked_add(1)
                .filter(|n| *n <= self.config.max_recovery_directories)
                .ok_or_else(capacity)?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| corrupt("web-evidence-directory"))?;
            let digest: ArtifactBlobDigest = format!("sha256:{name}")
                .parse()
                .map_err(|_| corrupt("web-evidence-directory"))?;
            let files = shared_content::bounded_files(&entry.path(), self.config)?;
            let bytes = files
                .iter()
                .try_fold(0u64, |n, (_, bytes)| n.checked_add(*bytes))
                .filter(|n| *n <= self.lifecycle_limits.max_evidence_revision_bytes as u64)
                .ok_or_else(capacity)?;
            state.evidence_bytes = state
                .evidence_bytes
                .checked_add(bytes)
                .filter(|n| *n <= self.lifecycle_limits.max_total_evidence_bytes as u64)
                .ok_or_else(capacity)?;
            if entry.path().join(COMPLETE).try_exists().map_err(io_error)? {
                let revision = self.web_revision(&digest)?;
                if self.web_storage(&revision.publication)?.digest()? != revision.original {
                    return Err(corrupt("web-evidence-original-changed"));
                }
            }
        }
        Ok(())
    }
}
