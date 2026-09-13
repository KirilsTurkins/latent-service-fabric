//! Frozen-v1 persistence fixtures, small batches and interruption recovery.
use super::lifecycle::{accept, context, scope};
use super::*;
use crate::lifecycle::LegacyLifecycleSnapshot;
use crate::{
    CatalogMigrationLimits, LifecycleLimits, ManagedPublicationReceipt, ManagedPublicationUpload,
    PublicationSelector, ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseLifecycleState,
};

struct Fixture {
    root: TempRoot,
    values: Vec<CapsuleArtifact>,
    receipts: Vec<ManagedPublicationReceipt>,
    original_history: Vec<(PathBuf, Vec<u8>)>,
}
impl Fixture {
    fn new(count: usize) -> Self {
        let root = TempRoot::new();
        let repo = repository(root.path());
        let mut values = Vec::new();
        let mut receipts = Vec::new();
        for index in 0..count {
            let value = artifact(&format!("legacy-{index}"), &index.to_le_bytes());
            let receipt = block_on(repo.publish_managed(
                context(&format!("create-{index}"), 0),
                ManagedPublicationUpload::Local(value.clone()),
                &mut accept,
            ))
            .unwrap();
            values.push(value);
            receipts.push(receipt);
        }
        if let Some(first) = values.first() {
            block_on(repo.change_release_lifecycle(
                context("legacy-revoke", 1),
                &first.descriptor.release_digest,
                ReleaseLifecycleAction::Revoke,
                ReleaseLifecycleReason::OperatorRevocation,
                &mut accept,
            ))
            .unwrap();
        }
        drop(repo);
        let root_path = root.path();
        fs::create_dir(root_path.join("releases")).unwrap();
        for (value, receipt) in values.iter().zip(&receipts) {
            fs::rename(
                root_path
                    .join("publications")
                    .join(receipt.publication.id.hex()),
                root_path
                    .join("releases")
                    .join(&value.descriptor.release_digest.0[7..]),
            )
            .unwrap();
        }
        fs::remove_dir(root_path.join("publications")).unwrap();
        fs::remove_dir_all(root_path.join("blobs")).unwrap();
        LegacyLifecycleSnapshot::write_legacy_fixture(
            &root_path.join("lifecycle"),
            LifecycleLimits::default(),
        )
        .unwrap();
        let mut original_history = Vec::new();
        capture(
            &root_path.join("lifecycle"),
            Path::new(""),
            &mut original_history,
        );
        Self {
            root,
            values,
            receipts,
            original_history,
        }
    }
    fn migrate(&self) -> Result<crate::CatalogMigrationReceipt, latent_core::PlatformError> {
        DirectoryArtifactRepository::migrate_catalog(
            self.root.path(),
            DirectoryArtifactRepositoryConfig::default(),
            LifecycleLimits::default(),
            CatalogMigrationLimits {
                batch_size: 1,
                ..CatalogMigrationLimits::default()
            },
        )
    }
    fn assert_preserved(&self) {
        for (path, bytes) in &self.original_history {
            assert_eq!(
                &fs::read(
                    self.root
                        .path()
                        .join(".publication-migration/legacy-lifecycle")
                        .join(path)
                )
                .unwrap(),
                bytes
            );
        }
        for (value, receipt) in self.values.iter().zip(&self.receipts) {
            let original = self
                .root
                .path()
                .join("releases")
                .join(&value.descriptor.release_digest.0[7..]);
            let migrated = self
                .root
                .path()
                .join("publications")
                .join(receipt.publication.id.hex());
            for entry in fs::read_dir(original).unwrap() {
                let entry = entry.unwrap();
                assert_eq!(
                    fs::read(entry.path()).unwrap(),
                    fs::read(migrated.join(entry.file_name())).unwrap()
                );
            }
        }
        let repo = repository(self.root.path());
        for (index, (value, receipt)) in self.values.iter().zip(&self.receipts).enumerate() {
            let status = repo
                .publication_lifecycle_status(&receipt.publication)
                .unwrap()
                .unwrap();
            assert_eq!(
                status.record.state,
                if index == 0 {
                    ReleaseLifecycleState::Revoked
                } else {
                    ReleaseLifecycleState::Admitted
                }
            );
            assert_eq!(status.record.generation, if index == 0 { 2 } else { 1 });
            assert_eq!(
                block_on(repo.publish_managed(
                    context(&format!("create-{index}"), 0),
                    ManagedPublicationUpload::Local(value.clone()),
                    &mut accept
                ))
                .unwrap(),
                *receipt
            );
        }
        if self.values.len() >= 2 {
            let mut corrected = self.values[1].clone();
            corrected
                .descriptor
                .annotations
                .insert("correction".into(), "metadata".into());
            let second = block_on(repo.publish_managed(
                context("metadata-correction", 0),
                ManagedPublicationUpload::Local(corrected),
                &mut accept,
            ))
            .unwrap();
            assert_ne!(second.publication, self.receipts[1].publication);
            assert!(repo
                .resolve_publication(
                    &scope(),
                    &PublicationSelector::LegacyComponent(
                        self.values[1].descriptor.release_digest.clone()
                    )
                )
                .is_err());
            assert_eq!(
                block_on(repo.publish_managed(
                    context("create-1", 0),
                    ManagedPublicationUpload::Local(self.values[1].clone()),
                    &mut accept
                ))
                .unwrap(),
                self.receipts[1]
            );
        }
    }
}
fn capture(root: &Path, relative: &Path, files: &mut Vec<(PathBuf, Vec<u8>)>) {
    for entry in fs::read_dir(root.join(relative)).unwrap() {
        let entry = entry.unwrap();
        let path = relative.join(entry.file_name());
        if entry.file_type().unwrap().is_dir() {
            capture(root, &path, files);
        } else {
            files.push((path, fs::read(entry.path()).unwrap()));
        }
    }
}

#[test]
fn offline_migration_preserves_original_bytes_receipts_and_revocation() {
    let fixture = Fixture::new(3);
    assert!(DirectoryArtifactRepository::open(
        fixture.root.path(),
        DirectoryArtifactRepositoryConfig::default()
    )
    .unwrap_err()
    .message
    .contains("catalog-migration-required"));
    let receipt = fixture.migrate().unwrap();
    assert_eq!(receipt.publications, 3);
    assert_eq!(receipt.retained_operations, 4);
    assert_eq!(fixture.migrate().unwrap(), receipt);
    assert!(
        LegacyLifecycleSnapshot::open(
            &fixture.root.path().join("lifecycle"),
            LifecycleLimits::default(),
            false,
            &[]
        )
        .is_err(),
        "the frozen v1 lifecycle reader rejects the completed v2 catalog"
    );
    fixture.assert_preserved();
}

#[test]
fn every_migration_cutpoint_resumes_without_restoring_revoked_authority() {
    for point in 1..=8 {
        let fixture = Fixture::new(3);
        super::super::migration::interrupt_at(point);
        assert!(fixture.migrate().is_err(), "cutpoint {point}");
        if point != 8 {
            let failure = DirectoryArtifactRepository::open(
                fixture.root.path(),
                DirectoryArtifactRepositoryConfig::default(),
            )
            .unwrap_err();
            assert!(
                failure.message.contains("catalog-migration-in-progress"),
                "{point}: {failure:?}"
            );
            let marker = fs::read(fixture.root.path().join("LIFECYCLE_MODE")).unwrap();
            assert_ne!(
                marker, b"lsf-release-lifecycle-v1\n",
                "old startup rejects the fence even for an empty catalog"
            );
        }
        assert_eq!(
            fixture.migrate().unwrap().publications,
            3,
            "cutpoint {point}"
        );
        fixture.assert_preserved();
    }
}

#[test]
fn migration_requires_the_owner_and_preflights_limits_before_fencing() {
    for case in 0..5 {
        let fixture = Fixture::new(2);
        let mut config = DirectoryArtifactRepositoryConfig::default();
        let mut limits = CatalogMigrationLimits::default();
        match case {
            0 => config.max_storage_bytes = 1,
            1 => config.max_content_blobs = 1,
            2 => limits.max_files = 8,
            3 => limits.max_metadata_bytes = 1,
            _ => limits.max_work_bytes = 1,
        }
        assert!(DirectoryArtifactRepository::migrate_catalog(
            fixture.root.path(),
            config,
            LifecycleLimits::default(),
            limits
        )
        .is_err());
        assert_eq!(
            fs::read(fixture.root.path().join("LIFECYCLE_MODE")).unwrap(),
            b"lsf-release-lifecycle-v1\n"
        );
        assert!(!fixture.root.path().join(".publication-migration").exists());
        fixture.migrate().unwrap();
        let owner = repository(fixture.root.path());
        assert_eq!(
            fixture.migrate().unwrap_err().code,
            PlatformErrorCode::Unavailable
        );
        drop(owner);
    }
}

#[test]
fn changed_source_missing_history_and_modified_configuration_never_resume() {
    for case in 0..3 {
        let fixture = Fixture::new(2);
        super::super::migration::interrupt_at(1);
        assert!(fixture.migrate().is_err());
        if case == 0 {
            fs::remove_file(fixture.root.path().join("lifecycle/HEAD")).unwrap();
        }
        if case == 1 {
            let component = fixture
                .root
                .path()
                .join("releases")
                .join(&fixture.values[0].descriptor.release_digest.0[7..])
                .join("component.wasm");
            fs::write(component, b"changed").unwrap();
        }
        let result = if case == 2 {
            DirectoryArtifactRepository::migrate_catalog(
                fixture.root.path(),
                DirectoryArtifactRepositoryConfig {
                    max_index_entries: 99,
                    ..DirectoryArtifactRepositoryConfig::default()
                },
                LifecycleLimits::default(),
                CatalogMigrationLimits {
                    batch_size: 1,
                    ..CatalogMigrationLimits::default()
                },
            )
        } else {
            fixture.migrate()
        };
        assert!(result.is_err());
        assert!(DirectoryArtifactRepository::open(
            fixture.root.path(),
            DirectoryArtifactRepositoryConfig::default()
        )
        .is_err());
    }
}

#[test]
fn empty_legacy_catalog_is_fenced_and_migrated_explicitly() {
    let fixture = Fixture::new(0);
    super::super::migration::interrupt_at(1);
    assert!(fixture.migrate().is_err());
    assert!(DirectoryArtifactRepository::open(
        fixture.root.path(),
        DirectoryArtifactRepositoryConfig::default()
    )
    .is_err());
    assert_eq!(fixture.migrate().unwrap().publications, 0);
    assert!(block_on(repository(fixture.root.path()).list(None, 1))
        .unwrap()
        .entries
        .is_empty());
}
