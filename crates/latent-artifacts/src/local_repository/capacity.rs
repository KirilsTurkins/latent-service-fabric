//! Fixed-cost, nonblocking observations of the actual admission ledgers.
use super::*;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PublicationCapacitySnapshot {
    pub storage: PublicationStorageSnapshot,
    pub limits: DirectoryArtifactRepositoryConfig,
    /// Includes pending reservations and componentless web publications.
    pub indexed_publications: usize,
    pub index_bytes: usize,
    /// Includes incomplete directories that still consume recovery capacity.
    pub release_directories: usize,
    pub charged_storage_bytes: u64,
}

impl DirectoryArtifactRepository {
    /// No filesystem scan, retained publication list, new worker or waiting.
    /// A concurrent write or uncertain owner reports unavailable, never zero.
    pub fn publication_capacity_snapshot(
        &self,
    ) -> Result<PublicationCapacitySnapshot, PlatformError> {
        let unavailable = || {
            error(
                PlatformErrorCode::Unavailable,
                "catalog-capacity-unavailable",
            )
        };
        let writer = self.publish_lock.try_lock().map_err(|_| unavailable())?;
        if writer.pending.is_some() {
            return Err(unavailable());
        }
        let index = self.index.try_read().map_err(|_| unavailable())?;
        let content = self.content.try_lock().map_err(|_| unavailable())?;
        content.check()?;
        let storage = content.snapshot();
        let charged_storage_bytes = storage
            .shared_blob_bytes
            .checked_add(storage.publication_file_bytes)
            .and_then(|n| n.checked_add(storage.incomplete_file_bytes))
            .and_then(|n| n.checked_add(storage.web_control_bytes))
            .ok_or_else(unavailable)?;
        Ok(PublicationCapacitySnapshot {
            storage,
            limits: self.config,
            indexed_publications: index.capacity_entries(),
            index_bytes: index.accounted_bytes,
            release_directories: writer.release_directories,
            charged_storage_bytes,
        })
    }
}
