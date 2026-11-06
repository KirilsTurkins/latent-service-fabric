use super::*;

#[test]
fn native_cleanup_rechecks_preparation_clones_and_disappearing_owner() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "cleanup-holds");
    let catalog = bind(&roots[1], &repo);
    let deletion = deleted(&repo, &one);
    let request = request(&repo, &deletion);
    let before = bytes(&roots[0].0);
    let mut held = None;
    assert!(repo
        .reclaim_tombstoned_capsules(&request, TIMEOUT, &mut |_| {
            held = Some(Arc::clone(&repo).owned_preparation_source().unwrap());
            Ok(())
        })
        .is_err());
    let cloned = held.as_ref().unwrap().clone();
    drop(held);
    assert!(reclaim(&repo, &request).is_err());
    drop(cloned);
    assert_eq!(before, bytes(&roots[0].0));
    drop(catalog);
    assert_eq!(
        reclaim(&repo, &request).unwrap_err().message,
        "publication-deletion-reference-authority-unavailable"
    );
    assert_eq!(before, bytes(&roots[0].0));
}

#[test]
fn native_cleanup_both_hash_passes_fit_exact_total_work_budget() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "cleanup-work");
    let _catalog = bind(&roots[1], &repo);
    let deletion = deleted(&repo, &one);
    let plan = repo
        .inspect_publication_reclamation(
            &deletion,
            PublicationReclamationLimits::default(),
            TIMEOUT,
        )
        .unwrap();
    let mut request = request(&repo, &deletion);
    let files = plan.content.publication_files + plan.content.selected_blobs;
    request.limits.maximum_files = files * 2;
    request.limits.maximum_bytes_hashed = plan.content.bytes_hashed * 2;
    let before = bytes(&roots[0].0);
    for limits in [
        PublicationReclamationLimits {
            maximum_files: files * 2 - 1,
            ..request.limits
        },
        PublicationReclamationLimits {
            maximum_bytes_hashed: plan.content.bytes_hashed * 2 - 1,
            ..request.limits
        },
    ] {
        let mut rejected = request.clone();
        rejected.limits = limits;
        assert_eq!(
            repo.reclaim_tombstoned_capsules(&rejected, TIMEOUT, &mut |_| panic!(
                "work not admitted"
            ))
            .unwrap_err()
            .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(bytes(&roots[0].0), before);
    }
    let result = reclaim(&repo, &request).unwrap();
    assert_eq!(result.receipt.content, plan.content);
    assert!(payload_bytes(&roots[0].0).is_empty());
}

#[test]
fn native_cleanup_near_metadata_and_storage_budget_refuses_before_preflight() {
    for metadata in [true, false] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = artifacts(&roots[0]);
        let one = retired(&repo, "cleanup-budget");
        let catalog = bind(&roots[1], &repo);
        let deletion = deleted(&repo, &one);
        let used = repo.publication_capacity_snapshot().unwrap();
        drop(catalog);
        drop(repo);
        let mut config = DirectoryArtifactRepositoryConfig::default();
        if metadata {
            config.max_index_bytes = used.index_bytes + 1024;
        } else {
            config.max_storage_bytes = used.charged_storage_bytes + 1024;
        }
        let repo = Arc::new(DirectoryArtifactRepository::open(&roots[0].0, config).unwrap());
        let _catalog = bind(&roots[1], &repo);
        let request = request(&repo, &deletion);
        let before = bytes(&roots[0].0);
        let before_capacity = repo.publication_capacity_snapshot().unwrap();
        assert_eq!(
            repo.reclaim_tombstoned_capsules(&request, TIMEOUT, &mut |_| panic!(
                "candidate envelope not reserved"
            ))
            .unwrap_err()
            .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert_eq!(before, bytes(&roots[0].0));
        assert_eq!(
            before_capacity,
            repo.publication_capacity_snapshot().unwrap()
        );
    }
}

#[test]
fn native_cleanup_holds_actual_control_writer_through_unlink_and_receipt() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct ObservedNative {
        native: Arc<Store>,
        visits: AtomicUsize,
    }
    impl PublicationReferenceAuthority for ObservedNative {
        fn catalog_authority(
            &self,
        ) -> std::result::Result<latent_artifacts::LifecycleAuthorityHandle, PlatformError>
        {
            self.native.catalog_authority()
        }
        fn with_unreferenced_publications(
            &self,
            owner: &latent_artifacts::LifecycleAuthorityHandle,
            publications: &[PublicationRef],
            action: &mut dyn FnMut(u64) -> std::result::Result<(), PlatformError>,
        ) -> std::result::Result<(), PlatformError> {
            self.native
                .with_unreferenced_publications(owner, publications, &mut |revision| {
                    assert!(self.native.writer.try_lock().is_err());
                    assert!(self.native.current.try_write().is_err());
                    let result = action(revision);
                    assert!(self.native.writer.try_lock().is_err());
                    assert!(self.native.current.try_write().is_err());
                    self.visits.fetch_add(1, Ordering::SeqCst);
                    result
                })
        }
    }
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let one = retired(&repo, "cleanup-locks");
    let native = Arc::new(store(&roots[1], &repo));
    let observed = Arc::new(ObservedNative {
        native: native.clone(),
        visits: AtomicUsize::new(0),
    });
    let owner: Arc<dyn PublicationReferenceAuthority> = observed.clone();
    repo.install_publication_reference_authority(&owner)
        .unwrap();
    let deletion = deleted(&repo, &one);
    let request = request(&repo, &deletion);
    let before = observed.visits.load(Ordering::SeqCst);
    reclaim(&repo, &request).unwrap();
    assert_eq!(observed.visits.load(Ordering::SeqCst), before + 2);
    assert!(payload_bytes(&roots[0].0).is_empty());
    assert!(matches!(
        repo.publication_reclamation_operation(&deletion.scope, &deletion.operation_id)
            .unwrap(),
        PublicationReclamationLookup::Found(_)
    ));
    assert!(native.writer.try_lock().is_ok());
    assert!(native.current.try_write().is_ok());
}

#[test]
fn native_cleanup_receipt_eviction_never_authorizes_replay_or_publication_resurrection() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let catalog = bind(&roots[1], &repo);
    let mut first = None;
    for n in 0..65 {
        let one = retired(&repo, &format!("cleanup-receipt-{n}"));
        let deletion = batch(&repo, &[one], &format!("cleanup-delete-{n}"));
        commit(&repo, &deletion).unwrap();
        let request = request(&repo, &deletion);
        reclaim(&repo, &request).unwrap();
        if n == 0 {
            first = Some(request);
        }
    }
    let first = first.unwrap();
    assert_eq!(
        repo.publication_reclamation_operation(&first.deletion.scope, &first.deletion.operation_id)
            .unwrap(),
        PublicationReclamationLookup::Unknown
    );
    let before = bytes(&roots[0].0);
    assert!(reclaim(&repo, &first).is_err());
    assert_eq!(before, bytes(&roots[0].0));
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    assert_eq!(
        repo.publication_reclamation_operation(&first.deletion.scope, &first.deletion.operation_id)
            .unwrap(),
        PublicationReclamationLookup::Unknown
    );
    assert!(reclaim(&repo, &first).is_err());
    assert!(payload_bytes(&roots[0].0).is_empty());
    hidden(&repo, &first.deletion.targets[0].publication);
}

#[test]
fn native_cleanup_finite_release_sequence_reclaims_payload_not_independent_history() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let catalog = bind(&roots[1], &repo);
    for n in 0..3 {
        let mut value = artifact("large-cleanup-sequence");
        value.component_bytes = vec![b'A' + n; 1024 * 1024];
        value.descriptor.release_digest = latent_artifacts::content_digest(&value.component_bytes);
        value.descriptor.size_bytes = value.component_bytes.len() as u64;
        value.manifest.component_digest = value.descriptor.release_digest.clone();
        let one = publish_artifact(&repo, "alice", &format!("cleanup-sequence-{n}"), value);
        repo.change_publication_lifecycle(
            context("alice", &format!("retire-sequence-{n}"), 1),
            &one,
            ReleaseLifecycleAction::Retire,
            ReleaseLifecycleReason::OperatorRetirement,
            &mut |_| Ok(()),
        )
        .unwrap();
        let deletion = batch(
            &repo,
            std::slice::from_ref(&one),
            &format!("delete-sequence-{n}"),
        );
        commit(&repo, &deletion).unwrap();
        let before = repo.publication_capacity_snapshot().unwrap();
        let result = reclaim(&repo, &request(&repo, &deletion)).unwrap();
        let after = repo.publication_capacity_snapshot().unwrap();
        assert!(after.charged_storage_bytes < before.charged_storage_bytes);
        assert_eq!(after.storage.publication_file_bytes, 0);
        assert_eq!(after.storage.shared_blob_bytes, 0);
        assert!(after.charged_storage_bytes > 0);
        println!("CAPSULE_RECLAMATION_SEQUENCE {n} before={} after={} publication_bytes={} blob_bytes={} retained_control={}",
            before.charged_storage_bytes, after.charged_storage_bytes,
            result.receipt.content.publication_file_bytes, result.receipt.content.last_reference_blob_bytes,
            after.storage.retention_control_bytes);
        hidden(&repo, &one);
    }
    let final_capacity = repo.publication_capacity_snapshot().unwrap();
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    assert_eq!(
        repo.publication_capacity_snapshot().unwrap(),
        final_capacity
    );
}

#[test]
fn native_cleanup_stopped_coupled_restore_continues_pending_unlinks_and_preserves_pins() {
    use std::os::unix::fs::MetadataExt;
    fn copy(
        source: &Path,
        destination: &Path,
        links: &mut BTreeMap<(u64, u64), PathBuf>,
        count: &mut usize,
    ) {
        for entry in fs::read_dir(source).unwrap() {
            *count += 1;
            assert!(*count < 10000);
            let entry = entry.unwrap();
            let metadata = fs::symlink_metadata(entry.path()).unwrap();
            let target = destination.join(entry.file_name());
            if metadata.is_dir() {
                fs::create_dir(&target).unwrap();
                copy(&entry.path(), &target, links, count);
            } else {
                assert!(metadata.is_file() && !metadata.file_type().is_symlink());
                if let Some(original) = links.get(&(metadata.dev(), metadata.ino())) {
                    fs::hard_link(original, &target).unwrap();
                } else {
                    fs::copy(entry.path(), &target).unwrap();
                    links.insert((metadata.dev(), metadata.ino()), target.clone());
                }
            }
            fs::set_permissions(&target, metadata.permissions()).unwrap();
        }
    }
    for pending in [true, false] {
        let roots = [
            TempRoot::new(),
            TempRoot::new(),
            TempRoot::new(),
            TempRoot::new(),
        ];
        let repo = artifacts(&roots[0]);
        let one = retired(&repo, "cleanup-backup");
        let other = publish(&repo, "alice", "cleanup-survivor");
        let catalog = bind(&roots[1], &repo);
        let selected = selection(&repo, &other);
        repo.change_publication_retention(
            &PublicationRetentionRequest {
                scope: other.scope.clone(),
                actor: actor(),
                operation_id: "backup-pin".into(),
                expected_catalog_fence: selected.expected_catalog_fence,
                action: PublicationRetentionAction::Pin,
                targets: selected.targets,
            },
            TIMEOUT,
            &mut |_| Ok(()),
        )
        .unwrap();
        let deletion = deleted(&repo, &one);
        let request = request(&repo, &deletion);
        if pending {
            repo.inject_retention_fault_for_test(
                DevelopmentRetentionFault::AfterPublicationFileUnlink,
            );
            assert!(reclaim(&repo, &request).is_err());
        } else {
            reclaim(&repo, &request).unwrap();
        }
        drop(catalog);
        drop(repo);
        let mut count = 0;
        copy(&roots[0].0, &roots[2].0, &mut BTreeMap::new(), &mut count);
        copy(&roots[1].0, &roots[3].0, &mut BTreeMap::new(), &mut count);
        let restored = artifacts(&roots[2]);
        let _catalog = bind(&roots[3], &restored);
        let original = artifacts(&roots[0]);
        let _original_catalog = bind(&roots[1], &original);
        assert_eq!(
            restored.publication_capacity_snapshot().unwrap(),
            original.publication_capacity_snapshot().unwrap()
        );
        assert_eq!(bytes(&roots[2].0), bytes(&roots[0].0));
        hidden(&restored, &one);
        assert!(restored.fetch_publication(&other).is_ok());
        assert!(restored
            .publication_retention_snapshot(&other.scope, std::slice::from_ref(&other), TIMEOUT)
            .unwrap()
            .selections[0]
            .pin
            .is_some());
        assert!(reclaim(&restored, &request).unwrap().replay);
        assert!(!roots[2].0.join("publications").join(one.id.hex()).exists());
    }
}
