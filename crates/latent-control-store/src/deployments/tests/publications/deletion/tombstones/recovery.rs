use super::*;

#[test]
fn native_tombstones_roll_forward_each_durable_boundary_with_original_identity() {
    for (index, point) in [
        DevelopmentRetentionFault::AfterIntent,
        DevelopmentRetentionFault::AfterHead,
        DevelopmentRetentionFault::AfterIntentRemoval,
        DevelopmentRetentionFault::AfterDeletionVisibility,
    ]
    .into_iter()
    .enumerate()
    {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = artifacts(&roots[0]);
        let publication = retired(&repo, &format!("crash-{index}"));
        let catalog = bind(&roots[1], &repo);
        let request = selection(&repo, &publication);
        let payloads = payload_bytes(&roots[0].0);
        repo.inject_retention_fault_for_test(point);
        assert_eq!(
            commit(&repo, &request).unwrap_err().code,
            PlatformErrorCode::Unavailable
        );
        assert_eq!(
            repo.publication_deletion_operation(&request.scope, &request.operation_id)
                .unwrap(),
            PublicationDeletionLookup::Uncertain
        );
        assert!(repo.publication_capacity_snapshot().is_err());
        assert!(commit(&repo, &request).is_err());
        drop(catalog);
        drop(repo);
        let repo = artifacts(&roots[0]);
        let _catalog = bind(&roots[1], &repo);
        hidden(&repo, &publication);
        let PublicationDeletionLookup::Found(receipt) = repo
            .publication_deletion_operation(&request.scope, &request.operation_id)
            .unwrap()
        else {
            panic!("original tombstone receipt lost at {point:?}")
        };
        assert_eq!(receipt.request, request);
        assert_eq!(receipt.stage, PublicationDeletionStage::VisibilityRemoved);
        assert_eq!(receipt.revision, 1);
        assert!(!roots[0].0.join("lifecycle/retention/INTENT").exists());
        assert!(commit(&repo, &request).unwrap().replay);
        assert_eq!(payloads, payload_bytes(&roots[0].0));
    }
}
#[test]
fn native_tombstone_format_promotion_without_intent_remains_unknown_and_visible() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = retired(&repo, "before-intent");
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    repo.inject_retention_fault_for_test(DevelopmentRetentionFault::AfterDeletionFormatPromotion);
    assert!(commit(&repo, &request).is_err());
    assert_eq!(
        repo.publication_deletion_operation(&request.scope, &request.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Uncertain
    );
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    assert!(repo
        .publication_catalog_entry(&publication)
        .unwrap()
        .is_some());
    assert_eq!(
        repo.publication_deletion_operation(&request.scope, &request.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Unknown
    );
    assert!(!roots[0].0.join("lifecycle/retention/INTENT").exists());
    assert!(repo
        .publication_execution_eligibility(&publication)
        .is_err());
}
#[test]
fn native_tombstone_missing_corrupt_or_downgraded_authority_refuses_without_cleanup() {
    for mutation in 0..4 {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = artifacts(&roots[0]);
        let publication = retired(&repo, "corrupt");
        let catalog = bind(&roots[1], &repo);
        commit(&repo, &selection(&repo, &publication)).unwrap();
        drop(catalog);
        drop(repo);
        let path = roots[0].0.join("lifecycle/retention/HEAD");
        match mutation {
            0 => fs::remove_file(&path).unwrap(),
            1 => fs::write(&path, b"{}").unwrap(),
            2 => fs::write(
                roots[0].0.join("LIFECYCLE_MODE"),
                b"lsf-release-lifecycle-retention-v1\n",
            )
            .unwrap(),
            _ => fs::write(
                roots[0].0.join("LIFECYCLE_MODE"),
                b"unsupported-deletion-v99\n",
            )
            .unwrap(),
        }
        let scratch = roots[0].0.join(".tmp").join("must-remain");
        fs::write(&scratch, b"not authority").unwrap();
        let before = bytes(&roots[0].0);
        assert!(DirectoryArtifactRepository::open(
            &roots[0].0,
            DirectoryArtifactRepositoryConfig::default()
        )
        .is_err());
        assert_eq!(before, bytes(&roots[0].0));
    }
}
#[test]
fn native_tombstone_pin_mutations_preserve_format_and_both_histories_on_reopen() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let deleted = retired(&repo, "deleted");
    let other = publish(&repo, "alice", "other");
    let catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &deleted);
    let result = commit(&repo, &request).unwrap();
    let selected = selection(&repo, &other);
    let pin = PublicationRetentionRequest {
        scope: other.scope.clone(),
        actor: actor(),
        operation_id: "protect-other".into(),
        expected_catalog_fence: selected.expected_catalog_fence,
        action: PublicationRetentionAction::Pin,
        targets: selected.targets,
    };
    repo.change_publication_retention(&pin, TIMEOUT, &mut |_| Ok(()))
        .unwrap();
    let marker = fs::read(roots[0].0.join("LIFECYCLE_MODE")).unwrap();
    assert_eq!(marker, b"lsf-release-lifecycle-deletion-v1\n");
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    hidden(&repo, &deleted);
    assert!(repo
        .publication_retention_snapshot(&other.scope, std::slice::from_ref(&other), TIMEOUT)
        .unwrap()
        .selections[0]
        .pin
        .is_some());
    assert_eq!(
        repo.publication_deletion_operation(&request.scope, &request.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Found(result.receipt)
    );
    assert!(
        repo.change_publication_retention(&pin, TIMEOUT, &mut |_| Ok(()))
            .unwrap()
            .replay
    );
    assert!(repo.fetch_publication(&other).is_ok());
}
#[test]
fn native_stopped_restore_preserves_tombstones_pins_receipts_and_shared_hardlinks() {
    use std::os::unix::fs::MetadataExt;
    fn copy(
        source: &Path,
        destination: &Path,
        links: &mut BTreeMap<(u64, u64), PathBuf>,
        count: &mut usize,
    ) {
        for entry in fs::read_dir(source).unwrap() {
            *count += 1;
            assert!(*count <= 10000);
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
    let roots = [
        TempRoot::new(),
        TempRoot::new(),
        TempRoot::new(),
        TempRoot::new(),
    ];
    let repo = artifacts(&roots[0]);
    let deleted = retired(&repo, "backup");
    let other = publish(&repo, "alice", "other");
    let catalog = bind(&roots[1], &repo);
    let result = commit(&repo, &selection(&repo, &deleted)).unwrap();
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
    let capacity = repo.publication_capacity_snapshot().unwrap();
    drop(catalog);
    drop(repo);
    let mut count = 0;
    copy(&roots[0].0, &roots[2].0, &mut BTreeMap::new(), &mut count);
    copy(&roots[1].0, &roots[3].0, &mut BTreeMap::new(), &mut count);
    assert_eq!(bytes(&roots[0].0), bytes(&roots[2].0));
    let repo = artifacts(&roots[2]);
    let _catalog = bind(&roots[3], &repo);
    hidden(&repo, &deleted);
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), capacity);
    assert!(repo
        .publication_retention_snapshot(&other.scope, std::slice::from_ref(&other), TIMEOUT)
        .unwrap()
        .selections[0]
        .pin
        .is_some());
    assert_eq!(
        repo.publication_deletion_operation(
            &result.receipt.request.scope,
            &result.receipt.request.operation_id
        )
        .unwrap(),
        PublicationDeletionLookup::Found(result.receipt)
    );
    assert_eq!(
        fs::metadata(
            roots[2]
                .0
                .join("publications")
                .join(deleted.id.hex())
                .join("component.wasm")
        )
        .unwrap()
        .ino(),
        fs::metadata(
            roots[2]
                .0
                .join("publications")
                .join(other.id.hex())
                .join("component.wasm")
        )
        .unwrap()
        .ino()
    );
    assert!(repo.fetch_publication(&other).is_ok());
}

#[test]
fn native_tombstone_restore_rejects_an_older_control_catalog_that_references_deleted_history() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = publish(&repo, "alice", "restore-reference");
    let catalog = bind(&roots[1], &repo);
    let desired = deployment("base", "alice", &release());
    run(catalog.apply(desired.clone())).unwrap();
    let old_control = bytes(&roots[1].0);
    run(catalog.delete(&desired.id)).unwrap();
    revoke(&repo, &publication);
    commit(&repo, &selection(&repo, &publication)).unwrap();
    let payloads = payload_bytes(&roots[0].0);
    drop(catalog);
    drop(repo);
    // Deliberately mismatched stopped fixture, never a supported operator recipe.
    fs::remove_dir_all(&roots[1].0).unwrap();
    fs::create_dir(&roots[1].0).unwrap();
    for (path, content) in old_control {
        let path = roots[1].0.join(path);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, content).unwrap();
    }
    let repo = artifacts(&roots[0]);
    hidden(&repo, &publication);
    let failure = run(Store::open_with_catalog(
        &roots[1].0,
        repo.clone(),
        Limits::default(),
        repo.lifecycle_authority(),
        crate::deployments::tests::lifecycle::profile("48.0.7"),
    ))
    .err()
    .expect("older control authority must not reopen");
    assert_eq!(failure.code, PlatformErrorCode::NotFound, "{failure:?}");
    assert_eq!(payloads, payload_bytes(&roots[0].0));
}
