//! Only a committed retention cleanup plan may enter this module.
use super::reclamation::{ContentPlan, Work};
use super::*;
use crate::{PublicationReclamationContent, PublicationReclamationLimits};
use std::time::Instant;

impl PublicationReclamationContent {
    pub(in crate::local_repository) fn validate_summary(
        &self,
        publications: usize,
    ) -> Result<(), PlatformError> {
        if self.publications != publications
            || publications == 0
            || publications > crate::MAX_PUBLICATION_RETENTION_BATCH
            || self.publication_files == 0
            || self
                .publication_files
                .checked_add(self.selected_blobs)
                .is_none_or(|n| n > crate::MAX_PUBLICATION_RECLAMATION_FILES)
            || self
                .last_reference_blobs
                .checked_add(self.shared_blobs_retained)
                != Some(self.selected_blobs)
            || self
                .publication_file_bytes
                .checked_add(self.last_reference_blob_bytes)
                .and_then(|n| n.checked_add(self.shared_blob_bytes_retained))
                != Some(self.bytes_hashed)
        {
            return Err(corrupt("publication-reclamation-summary"));
        }
        Ok(())
    }
}
impl ContentPlan {
    pub(in crate::local_repository) fn validate(
        &self,
        limits: PublicationReclamationLimits,
    ) -> Result<(), PlatformError> {
        limits.validate()?;
        self.content.validate_summary(self.directories.len())?;
        if self.directories.windows(2).any(|p| p[0].id >= p[1].id)
            || self.blobs.windows(2).any(|b| b[0].key >= b[1].key)
        {
            return Err(corrupt("publication-reclamation-plan-order"));
        }
        let file_count = self
            .directories
            .iter()
            .try_fold(0usize, |n, d| n.checked_add(d.files.len()))
            .ok_or_else(capacity)?;
        if file_count
            .checked_add(self.blobs.len())
            .is_none_or(|n| n > limits.maximum_files)
        {
            return Err(capacity());
        }
        let mut references = BTreeMap::<String, u64>::new();
        let mut result = PublicationReclamationContent {
            publications: self.directories.len(),
            ..Default::default()
        };
        for directory in &self.directories {
            if directory.files.is_empty()
                || directory.files.windows(2).any(|p| p[0].name >= p[1].name)
            {
                return Err(corrupt("publication-reclamation-plan-files"));
            }
            for file in &directory.files {
                validate_name(&file.name)?;
                let _: ArtifactBlobDigest = file
                    .key
                    .parse()
                    .map_err(|_| corrupt("publication-reclamation-plan-key"))?;
                if references
                    .insert(file.key.clone(), file.bytes)
                    .is_some_and(|n| n != file.bytes)
                {
                    return Err(corrupt("publication-reclamation-plan-size"));
                }
                result.publication_files = result
                    .publication_files
                    .checked_add(1)
                    .ok_or_else(capacity)?;
                result.publication_file_bytes = result
                    .publication_file_bytes
                    .checked_add(file.bytes)
                    .ok_or_else(capacity)?;
            }
        }
        result.selected_blobs = references.len();
        if self.blobs.len() != references.len() {
            return Err(corrupt("publication-reclamation-plan-blobs"));
        }
        for blob in &self.blobs {
            if references.get(&blob.key) != Some(&blob.bytes) {
                return Err(corrupt("publication-reclamation-plan-blobs"));
            }
            if blob.last_reference {
                result.last_reference_blobs += 1;
                result.last_reference_blob_bytes = result
                    .last_reference_blob_bytes
                    .checked_add(blob.bytes)
                    .ok_or_else(capacity)?;
            } else {
                result.shared_blobs_retained += 1;
                result.shared_blob_bytes_retained = result
                    .shared_blob_bytes_retained
                    .checked_add(blob.bytes)
                    .ok_or_else(capacity)?;
            }
        }
        result.bytes_hashed = result
            .publication_file_bytes
            .checked_add(result.last_reference_blob_bytes)
            .and_then(|n| n.checked_add(result.shared_blob_bytes_retained))
            .ok_or_else(capacity)?;
        if result != self.content
            || result.bytes_hashed > limits.maximum_bytes_hashed
            || result.publication_files + result.selected_blobs > limits.maximum_files
        {
            return Err(corrupt("publication-reclamation-plan-accounting"));
        }
        Ok(())
    }
}
impl SharedContent {
    /// Validate the ENTIRE remaining plan before the first recovery unlink. Only
    /// the already committed plan permits missing names. Foreign files, changed
    /// content, symlinks and unexpected surviving references fail closed.
    fn verify_remaining(
        &self,
        plan: &ContentPlan,
        limits: PublicationReclamationLimits,
        deadline: Instant,
    ) -> Result<(), PlatformError> {
        let mut work = Work {
            limits,
            deadline,
            bytes: 0,
        };
        for directory_plan in &plan.directories {
            work.check_time()?;
            let path = self
                .root
                .parent()
                .expect("catalog root")
                .join(RELEASES_DIR)
                .join(directory_plan.id.hex());
            if !optional_exists(&path)? {
                continue;
            }
            directory(&path)?;
            for (count, entry) in fs::read_dir(&path).map_err(io_error)?.enumerate() {
                work.check_time()?;
                if count >= directory_plan.files.len() {
                    return Err(corrupt("publication-reclamation-unexpected-file"));
                }
                let entry = entry.map_err(io_error)?;
                let name = entry
                    .file_name()
                    .into_string()
                    .map_err(|_| corrupt("publication-file-name"))?;
                let file = directory_plan
                    .files
                    .binary_search_by(|f| f.name.cmp(&name))
                    .ok()
                    .map(|i| &directory_plan.files[i])
                    .ok_or_else(|| corrupt("publication-reclamation-unexpected-file"))?;
                if work.hash_file(&entry.path(), file.bytes)?.as_str() != file.key {
                    return Err(corrupt("publication-reclamation-content-changed"));
                }
            }
        }
        for blob in &plan.blobs {
            work.check_time()?;
            let key: ArtifactBlobDigest = blob
                .key
                .parse()
                .map_err(|_| corrupt("publication-reclamation-key"))?;
            let path = self.root.join(&blob.key[7..]);
            let current = self.blobs.get(&key);
            if blob.last_reference && current.is_some_and(|b| b.references != 0) {
                return Err(corrupt("publication-reclamation-reference-conflict"));
            }
            if !optional_exists(&path)? {
                if !blob.last_reference || current.is_some() {
                    return Err(corrupt("publication-reclamation-blob-missing"));
                }
            } else if work.hash_file(&path, blob.bytes)?.as_str() != blob.key {
                return Err(corrupt("publication-reclamation-blob-changed"));
            }
        }
        work.check_time()
    }

    pub(in crate::local_repository) fn execute_cleanup(
        &mut self,
        plan: &ContentPlan,
        limits: PublicationReclamationLimits,
        deadline: Instant,
        recovery: bool,
    ) -> Result<(), PlatformError> {
        self.check()?;
        plan.validate(limits)?;
        if recovery {
            self.verify_remaining(plan, limits, deadline)?;
        }
        let root = self.root.parent().expect("catalog root");
        // Live callers hold all native ownership and have just reverified the
        // exact full plan. Recovery has verified all surviving bytes above.
        for planned in &plan.directories {
            let path = root.join(RELEASES_DIR).join(planned.id.hex());
            if optional_exists(&path)? {
                directory(&path)?;
                for file in &planned.files {
                    time(deadline)?;
                    let path = path.join(&file.name);
                    if optional_exists(&path)? {
                        if regular(&path)?.len() != file.bytes {
                            return Err(corrupt("publication-reclamation-size-changed"));
                        }
                        fs::remove_file(&path).map_err(io_error)?;
                        cleanup_fault(9)?;
                    } else if !recovery {
                        return Err(corrupt("publication-reclamation-file-missing"));
                    }
                }
                sync_dir(&path)?;
                fs::remove_dir(&path).map_err(io_error)?;
            } else if !recovery {
                return Err(corrupt("publication-reclamation-directory-missing"));
            }
            // Sync even when absent: an earlier interrupted unlink is not yet a
            // durable refund, and a missing name is not evidence of prior fsync.
            sync_dir(path.parent().expect("publication parent"))?;
            cleanup_fault(10)?;
        }
        if !recovery {
            for planned in &plan.directories {
                let old = self
                    .publications
                    .remove(&planned.id)
                    .ok_or_else(|| corrupt("publication-reclamation-reference-missing"))?;
                for key in &old.keys {
                    let blob = self
                        .blobs
                        .get_mut(key)
                        .ok_or_else(|| corrupt("publication-reclamation-blob-missing"))?;
                    blob.references = blob
                        .references
                        .checked_sub(1)
                        .ok_or_else(|| corrupt("publication-reclamation-reference-conflict"))?;
                    if blob.references == 0 {
                        self.unreferenced.insert(key.clone());
                    }
                }
                self.publication_bytes = self
                    .publication_bytes
                    .checked_sub(old.bytes)
                    .ok_or_else(capacity)?;
                self.metadata_bytes = self
                    .metadata_bytes
                    .checked_sub(PUBLICATION_CHARGE + old.keys.len() * 128)
                    .ok_or_else(capacity)?;
            }
        }
        for blob in &plan.blobs {
            time(deadline)?;
            if !blob.last_reference {
                continue;
            }
            let key: ArtifactBlobDigest = blob
                .key
                .parse()
                .map_err(|_| corrupt("publication-reclamation-key"))?;
            if self
                .blobs
                .get(&key)
                .is_some_and(|b| b.references != 0 || b.bytes != blob.bytes)
            {
                return Err(corrupt("publication-reclamation-reference-conflict"));
            }
            let path = self.root.join(&blob.key[7..]);
            if optional_exists(&path)? {
                if regular(&path)?.len() != blob.bytes {
                    return Err(corrupt("publication-reclamation-size-changed"));
                }
                fs::remove_file(&path).map_err(io_error)?;
                cleanup_fault(11)?;
            } else if !recovery {
                return Err(corrupt("publication-reclamation-blob-missing"));
            }
            sync_dir(&self.root)?;
            cleanup_fault(12)?;
            if self.blobs.remove(&key).is_some() {
                self.unreferenced.remove(&key);
                self.blob_bytes = self
                    .blob_bytes
                    .checked_sub(blob.bytes)
                    .ok_or_else(capacity)?;
                self.metadata_bytes = self
                    .metadata_bytes
                    .checked_sub(BLOB_CHARGE)
                    .ok_or_else(capacity)?;
            }
        }
        Ok(())
    }
}
fn time(deadline: Instant) -> Result<(), PlatformError> {
    if Instant::now() >= deadline {
        return Err(error(
            PlatformErrorCode::DeadlineExceeded,
            "publication-reclamation-deadline",
        ));
    }
    Ok(())
}
fn optional_exists(path: &Path) -> Result<bool, PlatformError> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(io_error(e)),
    }
}
fn cleanup_fault(point: u8) -> Result<(), PlatformError> {
    super::super::retention::cleanup_fault(point)
}
