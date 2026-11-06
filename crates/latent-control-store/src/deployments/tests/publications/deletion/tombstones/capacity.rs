use super::*;
#[test]
fn native_tombstone_exact_32_and_oversized_batches_are_atomic() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let mut publications: Vec<_> = (0..33)
        .map(|n| retired(&repo, &format!("batch-{n}")))
        .collect();
    publications.sort_by(|a, b| a.id.cmp(&b.id));
    let _catalog = bind(&roots[1], &repo);
    let request = batch(&repo, &publications[..32], "batch");
    let mut oversized = request.clone();
    oversized.targets.push(PublicationRetentionTarget {
        publication: publications[32].clone(),
        expected_generation: 2,
    });
    let before = bytes(&roots[0].0);
    assert_eq!(
        commit(&repo, &oversized).unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    assert_eq!(before, bytes(&roots[0].0));
    commit(&repo, &request).unwrap();
    for publication in &publications[..32] {
        hidden(&repo, publication);
    }
    assert!(repo
        .publication_catalog_entry(&publications[32])
        .unwrap()
        .is_some());
    assert_eq!(
        repo.publication_capacity_snapshot()
            .unwrap()
            .indexed_publications,
        33
    );
}
#[test]
fn native_tombstone_receipt_eviction_is_unknown_not_permission_to_reuse_operation() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publications: Vec<_> = (0..66)
        .map(|n| retired(&repo, &format!("receipt-{n}")))
        .collect();
    let catalog = bind(&roots[1], &repo);
    let first = batch(&repo, &publications[..1], "delete-0");
    commit(&repo, &first).unwrap();
    for (n, p) in publications[1..65].iter().enumerate() {
        commit(
            &repo,
            &batch(&repo, std::slice::from_ref(p), &format!("delete-{}", n + 1)),
        )
        .unwrap();
    }
    assert_eq!(
        repo.publication_deletion_operation(&first.scope, &first.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Unknown
    );
    let before = bytes(&roots[0].0);
    assert!(commit(&repo, &first).is_err());
    assert!(commit(&repo, &batch(&repo, &publications[65..], "delete-0")).is_err());
    assert_eq!(before, bytes(&roots[0].0));
    drop(catalog);
    drop(repo);
    let repo = artifacts(&roots[0]);
    let _catalog = bind(&roots[1], &repo);
    hidden(&repo, &publications[0]);
    assert_eq!(
        repo.publication_deletion_operation(&first.scope, &first.operation_id)
            .unwrap(),
        PublicationDeletionLookup::Unknown
    );
    assert!(commit(&repo, &batch(&repo, &publications[65..], "delete-0")).is_err());
    commit(
        &repo,
        &batch(&repo, &publications[65..], "explicit-new-selection"),
    )
    .unwrap();
}
#[test]
fn native_tombstone_near_metadata_budget_refuses_before_preflight_or_intent() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = artifacts(&roots[0]);
    let publication = retired(&repo, "budget");
    let used = repo.publication_capacity_snapshot().unwrap();
    drop(repo);
    let mut config = DirectoryArtifactRepositoryConfig::default();
    config.max_index_bytes = used.index_bytes + 1024;
    let repo = Arc::new(DirectoryArtifactRepository::open(&roots[0].0, config).unwrap());
    let _catalog = bind(&roots[1], &repo);
    let request = selection(&repo, &publication);
    let before = bytes(&roots[0].0);
    let capacity = repo.publication_capacity_snapshot().unwrap();
    assert_eq!(
        repo.tombstone_publications(&request, TIMEOUT, &mut |_| panic!("no capacity reserved"))
            .unwrap_err()
            .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(before, bytes(&roots[0].0));
    assert_eq!(capacity, repo.publication_capacity_snapshot().unwrap());
    assert!(repo
        .publication_catalog_entry(&publication)
        .unwrap()
        .is_some());
}
#[test]
fn native_tombstoned_publications_still_consume_the_catalog_count_budget() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let mut config = DirectoryArtifactRepositoryConfig::default();
    config.max_index_entries = 1;
    let repo = Arc::new(DirectoryArtifactRepository::open(&roots[0].0, config).unwrap());
    let publication = retired(&repo, "only");
    let catalog = bind(&roots[1], &repo);
    commit(&repo, &selection(&repo, &publication)).unwrap();
    assert_eq!(
        repo.publication_capacity_snapshot()
            .unwrap()
            .indexed_publications,
        1
    );
    let mut upload = artifact("different");
    upload.manifest.metadata.tenant = Some(TenantId("alice".into()));
    let contract = latent_core::ContractId("alice:echo/api@1.0.0".into());
    upload.manifest.world = contract.clone();
    upload.manifest.exports[0].contract = contract.clone();
    upload.contracts[0].id = contract.clone();
    upload.contracts[0].package_name = "alice:echo".into();
    upload.contracts[0].interfaces[0].id = latent_core::InterfaceId(contract.0);
    let failure = run(repo.publish_managed(
        context("alice", "another", 0),
        ManagedPublicationUpload::Local(upload),
        &mut |_| Ok(()),
    ))
    .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    drop(catalog);
    drop(repo);
    let repo = DirectoryArtifactRepository::open(&roots[0].0, config).unwrap();
    assert_eq!(
        repo.publication_capacity_snapshot()
            .unwrap()
            .indexed_publications,
        1
    );
    hidden(&repo, &publication);
}

#[test]
fn native_tombstone_finite_history_accepts_1024_and_refuses_the_next_publication() {
    use latent_artifacts::MAX_PUBLICATION_TOMBSTONES;
    let roots = [TempRoot::new(), TempRoot::new()];
    // A small existing lifecycle-receipt window keeps fixture construction
    // finite without reducing the production tombstone bound under test.
    let limits = latent_artifacts::LifecycleLimits {
        max_recent_operations: 8,
        ..Default::default()
    };
    let open = || {
        Arc::new(
            DirectoryArtifactRepository::open_with_lifecycle_limits(
                &roots[0].0,
                DirectoryArtifactRepositoryConfig::default(),
                limits,
            )
            .unwrap(),
        )
    };
    let repo = open();
    let mut publications = Vec::with_capacity(MAX_PUBLICATION_TOMBSTONES + 1);
    for n in 0..=MAX_PUBLICATION_TOMBSTONES {
        publications.push(retired(&repo, &format!("bounded-{n}")));
    }
    let catalog = bind(&roots[1], &repo);
    for (n, chunk) in publications[..MAX_PUBLICATION_TOMBSTONES]
        .chunks(32)
        .enumerate()
    {
        commit(&repo, &batch(&repo, chunk, &format!("bounded-delete-{n}"))).unwrap();
    }
    let attempted = batch(
        &repo,
        &publications[MAX_PUBLICATION_TOMBSTONES..],
        "one-over",
    );
    let before = bytes(&roots[0].0);
    assert_eq!(
        repo.tombstone_publications(&attempted, TIMEOUT, &mut |_| panic!(
            "tombstone capacity exhausted"
        ))
        .unwrap_err()
        .code,
        PlatformErrorCode::ResourceExhausted
    );
    assert_eq!(before, bytes(&roots[0].0));
    drop(catalog);
    drop(repo);
    let repo = open();
    let _catalog = bind(&roots[1], &repo);
    hidden(&repo, &publications[0]);
    hidden(&repo, &publications[MAX_PUBLICATION_TOMBSTONES - 1]);
    assert!(repo
        .publication_catalog_entry(&publications[MAX_PUBLICATION_TOMBSTONES])
        .unwrap()
        .is_some());
    assert!(commit(
        &repo,
        &batch(
            &repo,
            &publications[MAX_PUBLICATION_TOMBSTONES..],
            "still-full"
        )
    )
    .is_err());
}
