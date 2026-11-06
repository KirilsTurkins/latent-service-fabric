use super::*;

#[test]
fn native_web_cleanup_recovers_each_committed_unlink_sync_and_refund_boundary() {
    for point in [
        DevelopmentRetentionFault::AfterIntent,
        DevelopmentRetentionFault::AfterHead,
        DevelopmentRetentionFault::AfterIntentRemoval,
        DevelopmentRetentionFault::AfterReclamationCommit,
        DevelopmentRetentionFault::AfterPublicationFileUnlink,
        DevelopmentRetentionFault::AfterPublicationDirectorySync,
        DevelopmentRetentionFault::AfterBlobUnlink,
        DevelopmentRetentionFault::AfterBlobParentSync,
        DevelopmentRetentionFault::BeforeReclamationReceipt,
        DevelopmentRetentionFault::AfterReclamationReceipt,
    ] {
        let roots = [TempRoot::new(), TempRoot::new()];
        let repo = static_repo(&roots[0]);
        let publication = publish_static(&repo, "alice");
        let store = bound(&roots[1], &repo);
        let request = deleted_web(&repo, &publication);
        repo.inject_retention_fault_for_test(point);
        assert_eq!(
            reclaim(&repo, &request).unwrap_err().code,
            PlatformErrorCode::Unavailable,
            "{point:?}"
        );
        assert!(repo.publication_capacity_snapshot().is_err());
        assert_eq!(
            repo.publication_reclamation_operation(
                &request.deletion.scope,
                &request.deletion.operation_id
            )
            .unwrap(),
            PublicationReclamationLookup::Uncertain
        );
        drop(store);
        drop(repo);
        let repo = static_repo(&roots[0]);
        let _store = bound(&roots[1], &repo);
        assert!(reclaim(&repo, &request).unwrap().replay, "{point:?}");
        hidden(&repo, &publication);
        assert!(!payload(&roots[0], &publication).exists());
        assert_eq!(repo.publication_storage_snapshot().unwrap().shared_blobs, 0);
        assert_eq!(
            repo.publication_capacity_snapshot()
                .unwrap()
                .release_directories,
            0
        );
        assert!(!roots[0].0.join("lifecycle/retention/INTENT").exists());
    }
}

#[test]
fn native_web_cleanup_format_promotion_without_intent_preserves_payload_and_unknown() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let store = bound(&roots[1], &repo);
    let request = deleted_web(&repo, &publication);
    let original = bytes(&payload(&roots[0], &publication));
    repo.inject_retention_fault_for_test(
        DevelopmentRetentionFault::AfterReclamationFormatPromotion,
    );
    assert!(reclaim(&repo, &request).is_err());
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    let _store = bound(&roots[1], &repo);
    assert_eq!(bytes(&payload(&roots[0], &publication)), original);
    assert_eq!(
        repo.publication_reclamation_operation(
            &request.deletion.scope,
            &request.deletion.operation_id
        )
        .unwrap(),
        PublicationReclamationLookup::Unknown
    );
    assert!(!reclaim(&repo, &request).unwrap().replay);
}

#[test]
fn native_web_cleanup_pending_corruption_blocks_all_further_unlinks() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let store = bound(&roots[1], &repo);
    let request = deleted_web(&repo, &publication);
    repo.inject_retention_fault_for_test(DevelopmentRetentionFault::AfterReclamationCommit);
    assert!(reclaim(&repo, &request).is_err());
    drop(store);
    drop(repo);
    let file = fs::read_dir(payload(&roots[0], &publication))
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let mut value = fs::read(&file).unwrap();
    value[0] ^= 1;
    fs::write(file, value).unwrap();
    let before = bytes(&roots[0].0);
    assert!(try_open(&roots[0]).is_err());
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_web_cleanup_downgraded_reader_fence_refuses_before_temporary_cleanup() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let store = bound(&roots[1], &repo);
    let request = deleted_web(&repo, &publication);
    reclaim(&repo, &request).unwrap();
    drop(store);
    drop(repo);
    assert_eq!(
        fs::read(roots[0].0.join("LIFECYCLE_MODE")).unwrap(),
        b"lsf-release-lifecycle-reclamation-v2\n"
    );
    fs::write(
        roots[0].0.join("LIFECYCLE_MODE"),
        b"lsf-release-lifecycle-reclamation-v1\n",
    )
    .unwrap();
    fs::write(roots[0].0.join(".tmp/preserve"), b"must survive rejection").unwrap();
    let before = bytes(&roots[0].0);
    assert!(try_open(&roots[0]).is_err());
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_web_cleanup_reintroduced_completed_directory_is_not_an_orphan() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let store = bound(&roots[1], &repo);
    let request = deleted_web(&repo, &publication);
    let original = bytes(&payload(&roots[0], &publication));
    reclaim(&repo, &request).unwrap();
    drop(store);
    drop(repo);
    fs::create_dir(payload(&roots[0], &publication)).unwrap();
    for (file, value) in original {
        fs::write(payload(&roots[0], &publication).join(file), value).unwrap();
    }
    let before = bytes(&roots[0].0);
    assert!(try_open(&roots[0]).is_err());
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_web_cleanup_checksum_valid_changed_history_is_refused() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let store = bound(&roots[1], &repo);
    let request = deleted_web(&repo, &publication);
    reclaim(&repo, &request).unwrap();
    drop(store);
    drop(repo);
    let path = roots[0].0.join("web/HEAD");
    let value = fs::read(&path).unwrap();
    let mut lines: Vec<Vec<u8>> = value.split(|b| *b == b'\n').map(|l| l.to_vec()).collect();
    let mut row: json::Value = json::from_slice(&lines[1]).unwrap();
    row["record"]["generation"] = json::json!(3);
    // Preserve typed field ordering rather than accepting a canonicalization error.
    let old = String::from_utf8(lines[1].clone()).unwrap();
    lines[1] = old
        .replace("\"generation\":2", "\"generation\":3")
        .into_bytes();
    assert_eq!(json::from_slice::<json::Value>(&lines[1]).unwrap(), row);
    let mut encoded = Vec::new();
    for line in &lines[..lines.len() - 2] {
        encoded.extend_from_slice(line);
        encoded.push(b'\n');
    }
    let digest = artifact_blob_digest(&encoded);
    encoded.extend_from_slice(digest.as_str().as_bytes());
    encoded.push(b'\n');
    fs::write(&path, encoded).unwrap();
    let before = bytes(&roots[0].0);
    assert_eq!(
        try_open(&roots[0]).err().unwrap().message,
        "web-cleanup-retained-row-changed"
    );
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_web_cleanup_retains_selected_evidence_and_rejects_missing_evidence_on_recovery() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let upload = static_web_upload();
    repo.renew_web_evidence(
        publication_context("alice", "renew-web", 1),
        &publication,
        ReleaseEvidenceUpload {
            signatures: upload.signatures,
            provenance: upload.provenance,
            sboms: upload.sboms,
        },
        &mut |_| Ok(()),
    )
    .unwrap();
    repo.transition_web_publication(
        publication_context("alice", "revoke-renewed", 2),
        &publication,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
    let store = bound(&roots[1], &repo);
    let deletion = selection(&repo, &publication);
    repo.tombstone_publications(&deletion, TIMEOUT, &mut |_| Ok(()))
        .unwrap();
    let request = cleanup_request(&repo, deletion);
    let evidence = bytes(&roots[0].0.join("web/evidence"));
    assert!(!evidence.is_empty());
    reclaim(&repo, &request).unwrap();
    assert_eq!(bytes(&roots[0].0.join("web/evidence")), evidence);
    drop(store);
    drop(repo);
    let repo = static_repo(&roots[0]);
    hidden(&repo, &publication);
    assert_eq!(repo.reclaim_uncommitted_web_content(32).unwrap(), 0);
    drop(repo);
    let file = evidence.keys().next().unwrap();
    fs::remove_file(roots[0].0.join("web/evidence").join(file)).unwrap();
    let before = bytes(&roots[0].0);
    assert!(try_open(&roots[0]).is_err());
    assert_eq!(bytes(&roots[0].0), before);
}

#[test]
fn native_web_cleanup_stopped_coupled_restore_resumes_original_partial_unlink() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let backup = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let one = publish_static(&repo, "alice");
    let two = publish_static(&repo, "bob");
    let store = bound(&roots[1], &repo);
    let request = deleted_web(&repo, &one);
    repo.inject_retention_fault_for_test(DevelopmentRetentionFault::AfterPublicationFileUnlink);
    assert!(reclaim(&repo, &request).is_err());
    drop(store);
    drop(repo);
    copy_tree(&roots[0].0, &backup[0].0);
    copy_tree(&roots[1].0, &backup[1].0);
    let repo = static_repo(&backup[0]);
    let _store = bound(&backup[1], &repo);
    assert!(reclaim(&repo, &request).unwrap().replay);
    hidden(&repo, &one);
    assert!(repo.read_web_asset(&two, "/index.html").is_ok());
    assert!(!payload(&backup[0], &one).exists());
}

#[test]
fn native_web_cleanup_older_control_restore_cannot_reference_removed_payloads() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let older_control = TempRoot::new();
    let restored = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let store = bound(&roots[1], &repo);
    execute(
        &store,
        request(
            &store,
            "apply",
            static_definition("alice", "site", &publication, "/", "prefix"),
            0,
        ),
    );
    drop(store);
    drop(repo);
    copy_tree(&roots[1].0, &older_control.0);
    let repo = static_repo(&roots[0]);
    let store = bound(&roots[1], &repo);
    delete(&store, "remove-route", "alice", "site", 1);
    let cleanup = deleted_web(&repo, &publication);
    reclaim(&repo, &cleanup).unwrap();
    drop(store);
    drop(repo);
    copy_tree(&roots[0].0, &restored[0].0);
    copy_tree(&older_control.0, &restored[1].0);
    let repo = static_repo(&restored[0]);
    assert!(run(Store::open_with_catalog(
        &restored[1].0,
        repo.clone(),
        Limits::default(),
        repo.lifecycle_authority(),
        crate::deployments::tests::lifecycle::profile("48.0.7")
    ))
    .is_err());
    hidden(&repo, &publication);
    assert!(!payload(&restored[0], &publication).exists());
}

#[test]
fn native_web_cleanup_missing_entire_selected_evidence_revision_is_not_ignored() {
    let roots = [TempRoot::new(), TempRoot::new()];
    let repo = static_repo(&roots[0]);
    let publication = publish_static(&repo, "alice");
    let upload = static_web_upload();
    repo.renew_web_evidence(
        publication_context("alice", "renew-required", 1),
        &publication,
        ReleaseEvidenceUpload {
            signatures: upload.signatures,
            provenance: upload.provenance,
            sboms: upload.sboms,
        },
        &mut |_| Ok(()),
    )
    .unwrap();
    repo.transition_web_publication(
        publication_context("alice", "revoke-required", 2),
        &publication,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut |_| Ok(()),
    )
    .unwrap();
    let store = bound(&roots[1], &repo);
    let request = delete_batch(&repo, std::slice::from_ref(&publication), "delete-required");
    reclaim(&repo, &request).unwrap();
    drop(store);
    drop(repo);
    let evidence = roots[0].0.join("web/evidence");
    let revisions: Vec<_> = fs::read_dir(&evidence)
        .unwrap()
        .map(|e| e.unwrap().path())
        .collect();
    assert_eq!(revisions.len(), 1);
    fs::remove_dir_all(&revisions[0]).unwrap();
    let before = bytes(&roots[0].0);
    assert_eq!(
        try_open(&roots[0]).err().unwrap().message,
        "web-selected-evidence-missing"
    );
    assert_eq!(bytes(&roots[0].0), before);
}
