use super::*;

pub(super) fn entry(
    repository: &latent_artifacts::DirectoryArtifactRepository,
) -> NodeTopologyEntry {
    let mut attributes = Metadata::new();
    match repository.publication_capacity_snapshot() {
        Ok(snapshot) => {
            let limits = snapshot.limits;
            let content = snapshot.storage;
            attributes.insert("measurementStatus".into(), "available".into());
            for (name, value) in [
                ("chargedStorageBytes", snapshot.charged_storage_bytes),
                ("maximumStorageBytes", limits.max_storage_bytes),
                ("sharedBlobBytes", content.shared_blob_bytes),
                ("publicationLinkBytes", content.publication_file_bytes),
                ("incompleteFileBytes", content.incomplete_file_bytes),
                ("webControlBytes", content.web_control_bytes),
                ("contentIndexBytes", count(content.accounted_metadata_bytes)),
                (
                    "maximumContentIndexBytes",
                    count(limits.max_content_index_bytes),
                ),
                ("sharedBlobs", count(content.shared_blobs)),
                ("maximumSharedBlobs", count(limits.max_content_blobs)),
                ("indexedPublications", count(snapshot.indexed_publications)),
                ("maximumPublications", count(limits.max_index_entries)),
                ("releaseDirectories", count(snapshot.release_directories)),
                (
                    "maximumRecoveryDirectories",
                    count(limits.max_recovery_directories),
                ),
                ("releaseIndexBytes", count(snapshot.index_bytes)),
                ("maximumReleaseIndexBytes", count(limits.max_index_bytes)),
                (
                    "maximumFilesPerPublication",
                    count(limits.max_publication_files),
                ),
            ] {
                attributes.insert(name.into(), value.to_string());
            }
        }
        Err(_) => {
            attributes.insert("measurementStatus".into(), "unavailable".into());
        }
    }
    NodeTopologyEntry {
        name: "publication-catalog".into(),
        kind: "store".into(),
        ownership: ResourceOwnership::NodeFixed,
        configured_count: 1,
        active_count: Some(1),
        attributes,
    }
}
