//! Bounded immutable blobs, hard-linked into publication directories.
//!
//! Committed publication/history membership pins its files, including after
//! retirement. Only uncommitted directories and zero-reference blobs are GC
//! candidates. No live source can lose a committed payload through this GC.

use super::*;
use latent_core::{ArtifactBlobDigest, PublicationId};
use std::{
    collections::{BTreeMap, BTreeSet},
    io::Read,
};

const BLOB_DIR: &str = "blobs";
const BLOB_CHARGE: usize = 2048 + 2 * 71;
const PUBLICATION_CHARGE: usize = 1024 + PublicationId::TEXT_BYTES;

struct Blob {
    bytes: u64,
    references: usize,
}
struct PublicationFiles {
    keys: Vec<ArtifactBlobDigest>,
    bytes: u64,
}

pub(super) struct SharedContent {
    root: PathBuf,
    config: DirectoryArtifactRepositoryConfig,
    blobs: BTreeMap<ArtifactBlobDigest, Blob>,
    publications: BTreeMap<PublicationId, PublicationFiles>,
    unreferenced: BTreeSet<ArtifactBlobDigest>,
    blob_bytes: u64,
    publication_bytes: u64,
    incomplete_bytes: u64,
    external_bytes: u64,
    metadata_bytes: usize,
    healthy: bool,
}

/// Accounting is a conservative exposure ceiling, not an OS disk/RSS metric.
/// Publication links are additionally charged at their full logical size.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct PublicationStorageSnapshot {
    pub shared_blobs: usize,
    pub shared_blob_bytes: u64,
    pub retained_publications: usize,
    pub publication_file_bytes: u64,
    pub incomplete_file_bytes: u64,
    /// Web lifecycle/evidence files, including bounded atomic-write exposure.
    pub web_control_bytes: u64,
    pub accounted_metadata_bytes: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct PublicationContentReclamation {
    pub publications: usize,
    pub blobs: usize,
    pub unlinked_blob_bytes: u64,
}

impl SharedContent {
    pub(super) fn check_web_control(&self, bytes: u64) -> Result<(), PlatformError> {
        self.check()?;
        self.check_exposure(bytes.saturating_sub(self.external_bytes), 0, 0)
    }
    pub(super) fn replace_web_control(&mut self, bytes: u64) -> Result<(), PlatformError> {
        self.check_web_control(bytes)?;
        self.external_bytes = bytes;
        Ok(())
    }
    pub(super) fn new(root: &Path, config: DirectoryArtifactRepositoryConfig) -> Self {
        Self {
            root: root.join(BLOB_DIR),
            config,
            blobs: BTreeMap::new(),
            publications: BTreeMap::new(),
            unreferenced: BTreeSet::new(),
            blob_bytes: 0,
            publication_bytes: 0,
            incomplete_bytes: 0,
            external_bytes: 0,
            metadata_bytes: 0,
            healthy: true,
        }
    }
    fn check(&self) -> Result<(), PlatformError> {
        if self.healthy {
            Ok(())
        } else {
            Err(error(
                PlatformErrorCode::Unavailable,
                "publication-storage-reopen-required",
            ))
        }
    }
    pub(super) fn open(&mut self) -> Result<(), PlatformError> {
        fs::create_dir_all(&self.root).map_err(io_error)?;
        directory(&self.root)?;
        let mut count = 0usize;
        for entry in fs::read_dir(&self.root).map_err(io_error)? {
            let entry = entry.map_err(io_error)?;
            count = count.checked_add(1).ok_or_else(capacity)?;
            if count > self.config.max_content_blobs + 1 {
                return Err(capacity());
            }
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| corrupt("content-blob-name"))?;
            let is_temporary = name.ends_with(".next");
            let hex = name.strip_suffix(".next").unwrap_or(&name);
            let key: ArtifactBlobDigest = format!("sha256:{hex}")
                .parse()
                .map_err(|_| corrupt("content-blob-name"))?;
            let bytes = regular(&entry.path())?.len();
            if bytes > maximum_file(self.config) as u64 {
                return Err(capacity());
            }
            self.check_exposure(bytes, 0, BLOB_CHARGE)?;
            if is_temporary {
                // One registered unpublished write is never a retained reference.
                fs::remove_file(entry.path()).map_err(io_error)?;
                continue;
            }
            if self.blobs.len() >= self.config.max_content_blobs {
                return Err(capacity());
            }
            self.unreferenced.insert(key.clone());
            self.blob_bytes += bytes;
            self.metadata_bytes += BLOB_CHARGE;
            if self
                .blobs
                .insert(
                    key,
                    Blob {
                        bytes,
                        references: 0,
                    },
                )
                .is_some()
            {
                return Err(corrupt("duplicate-content-blob"));
            }
        }
        sync_dir(&self.root)?;
        sync_dir(self.root.parent().expect("catalog root"))
    }

    fn check_exposure(
        &self,
        blobs: u64,
        publications: u64,
        metadata: usize,
    ) -> Result<(), PlatformError> {
        if self
            .blob_bytes
            .checked_add(self.publication_bytes)
            .and_then(|n| n.checked_add(self.incomplete_bytes))
            .and_then(|n| n.checked_add(self.external_bytes))
            .and_then(|n| n.checked_add(blobs))
            .and_then(|n| n.checked_add(publications))
            .is_none_or(|n| n > self.config.max_storage_bytes)
            || self
                .metadata_bytes
                .checked_add(metadata)
                .is_none_or(|n| n > self.config.max_content_index_bytes)
        {
            return Err(capacity());
        }
        Ok(())
    }

    pub(super) fn preflight(
        &self,
        id: &PublicationId,
        files: &[(&str, &[u8])],
    ) -> Result<(), PlatformError> {
        self.check()?;
        if files.is_empty() || files.len() > self.config.max_publication_files {
            return Err(capacity());
        }
        let mut unique = BTreeMap::new();
        let mut logical = 0u64;
        let mut keys = Vec::with_capacity(files.len());
        for (name, bytes) in files {
            validate_name(name)?;
            let key = crate::package::artifact_blob_digest(bytes);
            logical = logical
                .checked_add(bytes.len() as u64)
                .ok_or_else(capacity)?;
            keys.push(key.clone());
            if let Some(old) = self.blobs.get(&key) {
                if old.bytes != bytes.len() as u64 {
                    return Err(corrupt("content-blob-size-conflict"));
                }
            } else {
                unique.insert(key, bytes.len() as u64);
            }
        }
        if let Some(old) = self.publications.get(id) {
            keys.sort();
            if old.keys != keys || old.bytes != logical {
                return Err(corrupt("publication-content-reference-conflict"));
            }
            return Ok(());
        }
        if self
            .blobs
            .len()
            .checked_add(unique.len())
            .is_none_or(|n| n > self.config.max_content_blobs)
            || self.publications.len() >= self.config.max_recovery_directories
        {
            return Err(capacity());
        }
        let new_bytes = unique
            .values()
            .try_fold(0u64, |n, size| n.checked_add(*size))
            .ok_or_else(capacity)?;
        let metadata = unique
            .len()
            .checked_mul(BLOB_CHARGE)
            .and_then(|n| n.checked_add(PUBLICATION_CHARGE))
            .and_then(|n| n.checked_add(files.len().checked_mul(128)?))
            .ok_or_else(capacity)?;
        self.check_exposure(new_bytes, logical, metadata)
    }

    /// One admission-work owner has already reserved the complete file set.
    pub(super) fn link_bytes(
        &mut self,
        destination: &Path,
        bytes: &[u8],
    ) -> Result<(), PlatformError> {
        self.check()?;
        let key = crate::package::artifact_blob_digest(bytes);
        let source = self.root.join(&key.as_str()[7..]);
        if source.exists() {
            if self
                .blobs
                .get(&key)
                .is_none_or(|blob| blob.bytes != bytes.len() as u64)
            {
                return Err(corrupt("content-blob-index-conflict"));
            }
            verify_bytes(&source, bytes)?;
        } else {
            if self.blobs.contains_key(&key) {
                return Err(corrupt("retained-content-blob-missing"));
            }
            self.check_exposure(bytes.len() as u64, 0, BLOB_CHARGE)?;
            if self.blobs.len() >= self.config.max_content_blobs {
                return Err(capacity());
            }
            let temporary = source.with_extension("next");
            let result = (|| {
                write_synced(&temporary, bytes)?;
                fs::rename(&temporary, &source).map_err(io_error)?;
                sync_dir(&self.root)
            })();
            if result.is_err() {
                self.healthy = false;
                return result;
            }
            self.blob_bytes += bytes.len() as u64;
            self.metadata_bytes += BLOB_CHARGE;
            self.unreferenced.insert(key.clone());
            self.blobs.insert(
                key,
                Blob {
                    bytes: bytes.len() as u64,
                    references: 0,
                },
            );
        }
        fs::hard_link(&source, destination).map_err(io_error)
    }

    pub(super) fn register_directory(
        &mut self,
        id: &PublicationId,
        path: &Path,
    ) -> Result<(), PlatformError> {
        self.check()?;
        let (keys, bytes) = self.directory_keys(path)?;
        self.register_keys(id, keys, bytes)
    }

    fn register_keys(
        &mut self,
        id: &PublicationId,
        keys: Vec<ArtifactBlobDigest>,
        bytes: u64,
    ) -> Result<(), PlatformError> {
        if let Some(old) = self.publications.get(id) {
            if old.keys != keys || old.bytes != bytes {
                return Err(corrupt("publication-content-reference-conflict"));
            }
            return Ok(());
        }
        if self.publications.len() >= self.config.max_recovery_directories {
            return Err(capacity());
        }
        let charge = PUBLICATION_CHARGE
            .checked_add(keys.len().checked_mul(128).ok_or_else(capacity)?)
            .ok_or_else(capacity)?;
        self.check_exposure(0, bytes, charge)?;
        for key in &keys {
            self.blobs
                .get(key)
                .ok_or_else(|| corrupt("publication-shared-blob-missing"))?
                .references
                .checked_add(1)
                .ok_or_else(capacity)?;
        }
        for key in &keys {
            self.blobs.get_mut(key).expect("checked blob").references += 1;
            self.unreferenced.remove(key);
        }
        self.publication_bytes += bytes;
        self.metadata_bytes += charge;
        self.publications
            .insert(id.clone(), PublicationFiles { keys, bytes });
        Ok(())
    }

    pub(super) fn charge_incomplete(&mut self, path: &Path) -> Result<(), PlatformError> {
        let files = bounded_files(path, self.config)?;
        let bytes = files
            .iter()
            .try_fold(0u64, |n, (_, bytes)| n.checked_add(*bytes))
            .ok_or_else(capacity)?;
        let metadata = files
            .len()
            .checked_mul(128)
            .and_then(|n| n.checked_add(PUBLICATION_CHARGE))
            .ok_or_else(capacity)?;
        self.check_exposure(0, bytes, metadata)?;
        self.incomplete_bytes += bytes;
        self.metadata_bytes += metadata;
        Ok(())
    }

    fn directory_keys(&self, path: &Path) -> Result<(Vec<ArtifactBlobDigest>, u64), PlatformError> {
        directory(path)?;
        let mut keys = Vec::new();
        let mut bytes = 0u64;
        for entry in fs::read_dir(path).map_err(io_error)? {
            if keys.len() >= self.config.max_publication_files {
                return Err(capacity());
            }
            let entry = entry.map_err(io_error)?;
            let name = entry
                .file_name()
                .into_string()
                .map_err(|_| corrupt("publication-file-name"))?;
            validate_name(&name)?;
            let (key, size) = file_key(&entry.path(), self.config)?;
            bytes = bytes
                .checked_add(size)
                .filter(|n| *n <= self.config.max_storage_bytes)
                .ok_or_else(capacity)?;
            if self.blobs.get(&key).is_none_or(|blob| blob.bytes != size) {
                return Err(corrupt("publication-shared-blob-missing"));
            }
            keys.push(key);
        }
        keys.sort();
        Ok((keys, bytes))
    }

    /// Caller has established that no lifecycle record or operation committed
    /// this publication. Directory unlink and parent sync precede the refund.
    pub(super) fn forget_uncommitted(
        &mut self,
        id: &PublicationId,
        path: &Path,
    ) -> Result<(), PlatformError> {
        self.check()?;
        let old = self
            .publications
            .get(id)
            .ok_or_else(|| corrupt("orphan-content-reference-missing"))?;
        let (keys, bytes) = self.directory_keys(path)?;
        if old.keys != keys || old.bytes != bytes {
            return Err(corrupt("orphan-content-changed"));
        }
        let temporary = self
            .root
            .parent()
            .expect("catalog root")
            .join(TEMP_DIR)
            .join(format!("gc-{}", id.hex()));
        if temporary.exists() {
            return Err(corrupt("orphan-reclamation-staging-conflict"));
        }
        let result = (|| {
            fs::rename(path, &temporary).map_err(io_error)?;
            #[cfg(test)]
            reclamation_fault(1)?;
            sync_dir(path.parent().expect("publication parent"))?;
            for entry in fs::read_dir(&temporary).map_err(io_error)? {
                let path = entry.map_err(io_error)?.path();
                regular(&path)?;
                fs::remove_file(&path).map_err(io_error)?;
            }
            fs::remove_dir(&temporary).map_err(io_error)?;
            sync_dir(temporary.parent().expect("staging parent"))
        })();
        if result.is_err() {
            self.healthy = false;
            return result;
        }
        let old = self.publications.remove(id).expect("checked publication");
        for key in &old.keys {
            let blob = self.blobs.get_mut(key).expect("retained reference");
            blob.references -= 1;
            if blob.references == 0 {
                self.unreferenced.insert(key.clone());
            }
        }
        self.publication_bytes -= old.bytes;
        self.metadata_bytes -= PUBLICATION_CHARGE + old.keys.len() * 128;
        Ok(())
    }

    pub(super) fn reclaim(
        &mut self,
        maximum: usize,
    ) -> Result<PublicationContentReclamation, PlatformError> {
        self.check()?;
        if maximum == 0 || maximum > 1024 {
            return Err(capacity());
        }
        let candidates: Vec<_> = self.unreferenced.iter().take(maximum).cloned().collect();
        let mut result = PublicationContentReclamation::default();
        for key in candidates {
            let path = self.root.join(&key.as_str()[7..]);
            let bytes = regular(&path)?.len();
            if self
                .blobs
                .get(&key)
                .is_none_or(|blob| blob.references != 0 || blob.bytes != bytes)
            {
                return Err(corrupt("content-reclamation-conflict"));
            }
            let removed = (|| {
                fs::remove_file(&path).map_err(io_error)?;
                #[cfg(test)]
                reclamation_fault(2)?;
                sync_dir(&self.root)
            })();
            if let Err(failure) = removed {
                self.healthy = false;
                return Err(failure);
            }
            self.blobs.remove(&key);
            self.unreferenced.remove(&key);
            self.blob_bytes -= bytes;
            self.metadata_bytes -= BLOB_CHARGE;
            result.blobs += 1;
            result.unlinked_blob_bytes += bytes;
        }
        Ok(result)
    }

    pub(super) fn snapshot(&self) -> PublicationStorageSnapshot {
        PublicationStorageSnapshot {
            shared_blobs: self.blobs.len(),
            shared_blob_bytes: self.blob_bytes,
            retained_publications: self.publications.len(),
            publication_file_bytes: self.publication_bytes,
            incomplete_file_bytes: self.incomplete_bytes,
            web_control_bytes: self.external_bytes,
            accounted_metadata_bytes: self.metadata_bytes,
        }
    }
}

fn capacity() -> PlatformError {
    resource_exhausted("publication-content-storage-limit")
}
pub(super) fn bounded_files(
    path: &Path,
    config: DirectoryArtifactRepositoryConfig,
) -> Result<Vec<(String, u64)>, PlatformError> {
    directory(path)?;
    let mut files = Vec::new();
    let mut total = 0u64;
    for entry in fs::read_dir(path).map_err(io_error)? {
        if files.len() >= config.max_publication_files {
            return Err(capacity());
        }
        let entry = entry.map_err(io_error)?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| corrupt("publication-file-name"))?;
        validate_name(&name)?;
        let size = regular(&entry.path())?.len();
        if size > maximum_file(config) as u64 {
            return Err(capacity());
        }
        total = total
            .checked_add(size)
            .filter(|n| *n <= config.max_storage_bytes)
            .ok_or_else(capacity)?;
        files.push((name, size));
    }
    files.sort_by(|a, b| a.0.cmp(&b.0));
    Ok(files)
}
fn maximum_file(config: DirectoryArtifactRepositoryConfig) -> usize {
    config
        .max_component_bytes
        .max(config.max_metadata_bytes)
        .max(crate::AdmissionStorageLimits::default().max_auxiliary_bytes)
}
fn file_key(
    path: &Path,
    config: DirectoryArtifactRepositoryConfig,
) -> Result<(ArtifactBlobDigest, u64), PlatformError> {
    let size = regular(path)?.len();
    if size > maximum_file(config) as u64 {
        return Err(capacity());
    }
    let content = read_component(
        path,
        maximum_file(config),
        Retention::Metadata,
        &VerificationStatistics::default(),
    )?;
    if content.size != size {
        return Err(corrupt("content-file-size-changed"));
    }
    Ok((
        content
            .digest
            .0
            .parse()
            .map_err(|_| corrupt("content-file-digest"))?,
        size,
    ))
}
fn validate_name(name: &str) -> Result<(), PlatformError> {
    if name.is_empty()
        || name.len() > 128
        || name == "."
        || name == ".."
        || name.contains(['/', '\\', ':'])
    {
        return Err(corrupt("publication-file-name"));
    }
    Ok(())
}
pub(super) fn directory(path: &Path) -> Result<(), PlatformError> {
    let metadata = fs::symlink_metadata(path).map_err(io_error)?;
    if !metadata.is_dir() || linked(&metadata) {
        return Err(corrupt("publication-content-directory"));
    }
    Ok(())
}
pub(super) fn regular(path: &Path) -> Result<fs::Metadata, PlatformError> {
    let metadata = fs::symlink_metadata(path).map_err(io_error)?;
    if !metadata.is_file() || linked(&metadata) {
        return Err(corrupt("publication-content-file-type"));
    }
    Ok(metadata)
}
fn linked(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return true;
        }
    }
    metadata.file_type().is_symlink()
}
fn verify_bytes(path: &Path, expected: &[u8]) -> Result<(), PlatformError> {
    if regular(path)?.len() != expected.len() as u64 {
        return Err(corrupt("content-blob-size-conflict"));
    }
    let mut file = File::open(path).map_err(io_error)?;
    if file.metadata().map_err(io_error)?.len() != expected.len() as u64 {
        return Err(corrupt("content-blob-size-conflict"));
    }
    let mut buffer = [0u8; 16 * 1024];
    for bytes in expected.chunks(buffer.len()) {
        file.read_exact(&mut buffer[..bytes.len()])
            .map_err(io_error)?;
        if &buffer[..bytes.len()] != bytes {
            return Err(corrupt("content-blob-integrity-mismatch"));
        }
    }
    if file.read(&mut buffer[..1]).map_err(io_error)? != 0 {
        return Err(corrupt("content-blob-size-conflict"));
    }
    Ok(())
}

#[cfg(test)]
thread_local! { static RECLAIM_FAIL: std::cell::Cell<u8> = const { std::cell::Cell::new(0) }; }
#[cfg(all(test, unix))]
pub(super) fn interrupt_reclamation_at(point: u8) {
    RECLAIM_FAIL.with(|fail| fail.set(point));
}
#[cfg(test)]
fn reclamation_fault(point: u8) -> Result<(), PlatformError> {
    if RECLAIM_FAIL.with(|fail| {
        if fail.get() == point {
            fail.set(0);
            true
        } else {
            false
        }
    }) {
        return Err(error(
            PlatformErrorCode::Internal,
            "injected-content-reclamation-interruption",
        ));
    }
    Ok(())
}
