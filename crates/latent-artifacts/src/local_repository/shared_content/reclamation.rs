//! Exact selected-content accounting. No path here removes a file or a reference.
use super::{
    corrupt, directory, error, fs, io_error, regular, resource_exhausted, validate_name,
    ArtifactBlobDigest, BTreeMap, File, Path, PathBuf, PlatformError, PlatformErrorCode,
    PublicationFiles, PublicationId, Read, SharedContent,
};
use crate::{PublicationReclamationContent, PublicationReclamationLimits};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::time::Instant;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::local_repository) struct FileRecord {
    pub name: String,
    pub key: String,
    pub bytes: u64,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::local_repository) struct DirectoryPlan {
    #[serde(with = "crate::publication::id_codec")]
    pub id: PublicationId,
    #[serde(default, skip_serializing_if = "is_false")]
    pub web: bool,
    pub files: Vec<FileRecord>,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::local_repository) struct BlobPlan {
    pub key: String,
    pub bytes: u64,
    pub last_reference: bool,
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub(in crate::local_repository) struct ContentPlan {
    pub directories: Vec<DirectoryPlan>,
    pub blobs: Vec<BlobPlan>,
    pub content: PublicationReclamationContent,
}

fn is_false(value: &bool) -> bool {
    !*value
}
impl DirectoryPlan {
    pub(in crate::local_repository) fn path(&self, root: &Path) -> PathBuf {
        let parent = if self.web {
            root.join("web/publications")
        } else {
            root.join(super::RELEASES_DIR)
        };
        parent.join(self.id.hex())
    }
}

impl SharedContent {
    pub(in crate::local_repository) fn inspect_reclamation(
        &self,
        selected: &[(PublicationId, PathBuf)],
        limits: PublicationReclamationLimits,
        deadline: Instant,
    ) -> Result<PublicationReclamationContent, PlatformError> {
        self.plan_reclamation(selected, limits, deadline)
            .map(|plan| plan.content)
    }

    pub(in crate::local_repository) fn plan_reclamation(
        &self,
        selected: &[(PublicationId, PathBuf)],
        limits: PublicationReclamationLimits,
        deadline: Instant,
    ) -> Result<ContentPlan, PlatformError> {
        self.check()?;
        limits.validate()?;
        if selected.is_empty()
            || selected.len() > crate::MAX_PUBLICATION_RETENTION_BATCH
            || selected.windows(2).any(|p| p[0].0 >= p[1].0)
        {
            return Err(corrupt("publication-reclamation-selection"));
        }
        let mut work = Work {
            limits,
            deadline,
            bytes: 0,
        };
        work.check_time()?;
        let mut result = PublicationReclamationContent {
            publications: selected.len(),
            ..Default::default()
        };
        // Count selected file references before allocating the inverse working
        // set. The persistent index is already charged; no unrelated row is read.
        for (id, _) in selected {
            work.check_time()?;
            let old = self
                .publications
                .get(id)
                .ok_or_else(|| corrupt("publication-reclamation-reference-missing"))?;
            result.publication_files = result
                .publication_files
                .checked_add(old.keys.len())
                .filter(|n| *n <= limits.maximum_files)
                .ok_or_else(budget)?;
            result.publication_file_bytes = result
                .publication_file_bytes
                .checked_add(old.bytes)
                .filter(|n| *n <= limits.maximum_bytes_hashed)
                .ok_or_else(budget)?;
        }
        let mut references: BTreeMap<ArtifactBlobDigest, usize> = BTreeMap::new();
        for (id, _) in selected {
            for key in &self.publications.get(id).expect("checked publication").keys {
                work.check_time()?;
                let count = references.entry(key.clone()).or_default();
                *count = count.checked_add(1).ok_or_else(budget)?;
            }
        }
        result.selected_blobs = references.len();
        if result
            .publication_files
            .checked_add(references.len())
            .is_none_or(|n| n > limits.maximum_files)
        {
            return Err(budget());
        }
        let mut expected_hash_bytes = result.publication_file_bytes;
        for (key, selected_references) in &references {
            work.check_time()?;
            let blob = self
                .blobs
                .get(key)
                .ok_or_else(|| corrupt("publication-reclamation-blob-missing"))?;
            if blob.references < *selected_references || self.unreferenced.contains(key) {
                return Err(corrupt("publication-reclamation-reference-conflict"));
            }
            expected_hash_bytes = expected_hash_bytes
                .checked_add(blob.bytes)
                .filter(|n| *n <= limits.maximum_bytes_hashed)
                .ok_or_else(budget)?;
            if blob.references == *selected_references {
                result.last_reference_blobs += 1;
                result.last_reference_blob_bytes = result
                    .last_reference_blob_bytes
                    .checked_add(blob.bytes)
                    .ok_or_else(budget)?;
            } else {
                result.shared_blobs_retained += 1;
                result.shared_blob_bytes_retained = result
                    .shared_blob_bytes_retained
                    .checked_add(blob.bytes)
                    .ok_or_else(budget)?;
            }
        }
        // Verify the actual native publication files and canonical blob names.
        // All estimates are withheld until every selected byte has been checked.
        let mut directories = Vec::with_capacity(selected.len());
        for (id, path) in selected {
            let files = verify_publication(
                path,
                self.publications.get(id).expect("checked publication"),
                &mut work,
            )?;
            directories.push(DirectoryPlan {
                id: id.clone(),
                web: false,
                files,
            });
        }
        let mut blobs = Vec::with_capacity(references.len());
        directory(&self.root)?;
        for key in references.keys() {
            work.check_time()?;
            let blob = self.blobs.get(key).expect("checked blob");
            let path = self.root.join(&key.as_str()[7..]);
            if work.hash_file(&path, blob.bytes)? != *key {
                return Err(corrupt("publication-reclamation-blob-changed"));
            }
            blobs.push(BlobPlan {
                key: key.as_str().into(),
                bytes: blob.bytes,
                last_reference: blob.references == references[key],
            });
        }
        work.check_time()?;
        if work.bytes != expected_hash_bytes {
            return Err(corrupt("publication-reclamation-work-accounting"));
        }
        result.bytes_hashed = work.bytes;
        Ok(ContentPlan {
            directories,
            blobs,
            content: result,
        })
    }
}

fn verify_publication(
    path: &Path,
    expected: &PublicationFiles,
    work: &mut Work,
) -> Result<Vec<FileRecord>, PlatformError> {
    work.check_time()?;
    directory(path)?;
    let mut files = Vec::with_capacity(expected.keys.len());
    let mut keys = Vec::with_capacity(expected.keys.len());
    let mut bytes = 0u64;
    for entry in fs::read_dir(path).map_err(io_error)? {
        work.check_time()?;
        if keys.len() >= expected.keys.len() {
            return Err(corrupt("publication-reclamation-file-set-changed"));
        }
        let entry = entry.map_err(io_error)?;
        let name = entry
            .file_name()
            .into_string()
            .map_err(|_| corrupt("publication-file-name"))?;
        validate_name(&name)?;
        let size = regular(&entry.path())?.len();
        bytes = bytes
            .checked_add(size)
            .filter(|n| *n <= expected.bytes)
            .ok_or_else(|| corrupt("publication-reclamation-size-changed"))?;
        let key = work.hash_file(&entry.path(), size)?;
        files.push(FileRecord {
            name,
            key: key.as_str().into(),
            bytes: size,
        });
        keys.push(key);
    }
    keys.sort();
    if keys != expected.keys || bytes != expected.bytes {
        return Err(corrupt("publication-reclamation-content-changed"));
    }
    files.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(files)
}

pub(super) struct Work {
    pub(super) limits: PublicationReclamationLimits,
    pub(super) deadline: Instant,
    pub(super) bytes: u64,
}
impl Work {
    pub(super) fn check_time(&self) -> Result<(), PlatformError> {
        if Instant::now() >= self.deadline {
            return Err(error(
                PlatformErrorCode::DeadlineExceeded,
                "publication-reclamation-deadline",
            ));
        }
        Ok(())
    }
    pub(super) fn hash_file(
        &mut self,
        path: &Path,
        expected: u64,
    ) -> Result<ArtifactBlobDigest, PlatformError> {
        self.check_time()?;
        if regular(path)?.len() != expected {
            return Err(corrupt("publication-reclamation-size-changed"));
        }
        let mut file = File::open(path).map_err(io_error)?;
        let opened = file.metadata().map_err(io_error)?;
        if !opened.is_file() || opened.len() != expected {
            return Err(corrupt("publication-reclamation-size-changed"));
        }
        let mut digest = Sha256::new();
        let mut size = 0u64;
        let mut buffer = [0u8; 16 * 1024];
        loop {
            self.check_time()?;
            let maximum =
                usize::try_from((expected - size).saturating_add(1).min(buffer.len() as u64))
                    .map_err(|_| budget())?;
            let count = match file.read(&mut buffer[..maximum]) {
                Ok(0) => break,
                Ok(n) => n,
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(io_error(e)),
            };
            size = size
                .checked_add(count as u64)
                .filter(|n| *n <= expected)
                .ok_or_else(|| corrupt("publication-reclamation-size-changed"))?;
            self.bytes = self
                .bytes
                .checked_add(count as u64)
                .filter(|n| *n <= self.limits.maximum_bytes_hashed)
                .ok_or_else(budget)?;
            digest.update(&buffer[..count]);
        }
        self.check_time()?;
        if size != expected || regular(path)?.len() != expected {
            return Err(corrupt("publication-reclamation-size-changed"));
        }
        crate::content_hash::format_digest(digest.finalize().into())
            .0
            .parse()
            .map_err(|_| corrupt("publication-reclamation-digest"))
    }
}
fn budget() -> PlatformError {
    resource_exhausted("publication-reclamation-work-limit")
}
