//! Actual DirectoryArtifactRepository files/locks/fsyncs; no in-memory store model.
#![cfg(all(target_os = "linux", feature = "development-test-host"))]
#[path = "publication_retention/support.rs"]
mod support;
use latent_artifacts::*;
use latent_core::{PlatformErrorCode, TenantId};
use std::{fs, time::Duration};
use support::*;

#[test]
fn pin_is_durable_and_never_restores_retired_execution_eligibility() {
    let root = Root::new();
    let repo = root.open();
    let publication = publish(&repo, "retention");
    let held = repo
        .publication_execution_eligibility(&publication)
        .unwrap();
    let original = request(
        &repo,
        std::slice::from_ref(&publication),
        "pin",
        PublicationRetentionAction::Pin,
    );
    let result = mutate(&repo, original.clone()).unwrap();
    assert!(!result.replay);
    held.check_current().unwrap();
    retire(&repo, &publication);
    assert!(held.check_current().is_err());
    let selected = snapshot(&repo, std::slice::from_ref(&publication));
    assert_eq!(
        selected.selections[0]
            .pin
            .as_ref()
            .unwrap()
            .pinned_generation,
        1
    );
    assert_eq!(selected.selections[0].target.expected_generation, 2);
    drop(repo);
    let reopened = root.open();
    let selected = snapshot(&reopened, std::slice::from_ref(&publication));
    assert!(selected.selections[0].pin.is_some());
    assert!(reopened
        .publication_execution_eligibility(&publication)
        .is_err());
    let replay = mutate(&reopened, original).unwrap();
    assert!(replay.replay);
    assert_eq!(replay.receipt, result.receipt);
    mutate(
        &reopened,
        request(
            &reopened,
            std::slice::from_ref(&publication),
            "unpin",
            PublicationRetentionAction::Unpin,
        ),
    )
    .unwrap();
    assert!(
        snapshot(&reopened, std::slice::from_ref(&publication)).selections[0]
            .pin
            .is_none()
    );
    assert!(reopened
        .publication_execution_eligibility(&publication)
        .is_err());
    assert_eq!(
        reopened.reclaim_uncommitted_content(32).unwrap(),
        PublicationContentReclamation::default()
    );
}

#[test]
fn exact_batch_limit_and_duplicate_rejection_precede_any_persistent_side_effect() {
    let root = Root::new();
    let repo = root.open();
    let mut publications: Vec<_> = (0..33)
        .map(|n| publish(&repo, &format!("batch-{n}")))
        .collect();
    publications.sort_by(|a, b| a.id.cmp(&b.id));
    let mut too_many = request(
        &repo,
        &publications[..32],
        "oversize",
        PublicationRetentionAction::Pin,
    );
    too_many.targets.push(PublicationRetentionTarget {
        publication: publications[32].clone(),
        expected_generation: 1,
    });
    assert_eq!(
        mutate(&repo, too_many).unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    let mut duplicate = request(
        &repo,
        &publications[..1],
        "duplicate",
        PublicationRetentionAction::Pin,
    );
    duplicate.targets.push(duplicate.targets[0].clone());
    assert_eq!(
        mutate(&repo, duplicate).unwrap_err().code,
        PlatformErrorCode::InvalidArgument
    );
    assert!(!root.path().join("lifecycle/retention/HEAD").exists());
    mutate(
        &repo,
        request(
            &repo,
            &publications[..32],
            "exact-32",
            PublicationRetentionAction::Pin,
        ),
    )
    .unwrap();
    assert!(snapshot(&repo, &publications[..32])
        .selections
        .iter()
        .all(|s| s.pin.is_some()));
    assert!(snapshot(&repo, &publications[32..]).selections[0]
        .pin
        .is_none());
}

#[test]
fn foreign_scope_and_missing_target_have_the_same_nondisclosing_result() {
    let root = Root::new();
    let repo = root.open();
    let publication = publish(&repo, "foreign");
    let other = LifecycleScope::Tenant(TenantId("other".into()));
    let mut foreign = publication.clone();
    foreign.scope = other.clone();
    let missing = PublicationRef::package(
        other.clone(),
        &"sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
            .parse()
            .unwrap(),
    )
    .unwrap();
    let a = repo
        .publication_retention_snapshot(&other, &[foreign], TIMEOUT)
        .unwrap_err();
    let b = repo
        .publication_retention_snapshot(&other, &[missing], TIMEOUT)
        .unwrap_err();
    assert_eq!(a, b);
    assert_eq!(a.code, PlatformErrorCode::NotFound);
    let mut changed = request(
        &repo,
        &[publication],
        "foreign-request",
        PublicationRetentionAction::Pin,
    );
    changed.scope = other;
    assert_eq!(
        mutate(&repo, changed).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert!(!root.path().join("lifecycle/retention/HEAD").exists());
}

#[test]
fn catalog_fence_is_not_transferable_between_identical_native_catalogs() {
    let first = Root::new();
    let second = Root::new();
    let a = first.open();
    let b = second.open();
    let publication = publish(&a, "same");
    assert_eq!(publish(&b, "same"), publication);
    let attempted = request(
        &a,
        std::slice::from_ref(&publication),
        "foreign-owner",
        PublicationRetentionAction::Pin,
    );
    assert_ne!(
        attempted.expected_catalog_fence,
        snapshot(&b, &[publication]).catalog_fence
    );
    assert_eq!(
        mutate(&b, attempted).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    assert!(!second.path().join("lifecycle/retention/HEAD").exists());
}

#[test]
fn changed_generation_and_unrelated_catalog_changes_refuse_the_original_fence() {
    let root = Root::new();
    let repo = root.open();
    let publication = publish(&repo, "selected");
    let old = request(
        &repo,
        std::slice::from_ref(&publication),
        "stale",
        PublicationRetentionAction::Pin,
    );
    publish(&repo, "unrelated");
    assert_eq!(
        mutate(&repo, old).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    let old = request(
        &repo,
        std::slice::from_ref(&publication),
        "stale-generation",
        PublicationRetentionAction::Pin,
    );
    retire(&repo, &publication);
    assert_eq!(
        mutate(&repo, old).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    assert!(!root.path().join("lifecycle/retention/HEAD").exists());
}

#[test]
fn preflight_rejection_and_concurrent_commit_do_not_leave_a_pin_or_intent() {
    let root = Root::new();
    let repo = root.open();
    let publication = publish(&repo, "preflight");
    let attempted = request(
        &repo,
        std::slice::from_ref(&publication),
        "audit-full",
        PublicationRetentionAction::Pin,
    );
    let result = repo.change_publication_retention(&attempted, TIMEOUT, &mut |_| {
        Err(latent_core::PlatformError {
            code: PlatformErrorCode::ResourceExhausted,
            message: "test-audit-full".into(),
            retryable: false,
            details: Vec::new(),
        })
    });
    assert_eq!(
        result.unwrap_err().code,
        PlatformErrorCode::ResourceExhausted
    );
    assert!(!root.path().join("lifecycle/retention/HEAD").exists());
    let attempted = request(
        &repo,
        std::slice::from_ref(&publication),
        "race",
        PublicationRetentionAction::Pin,
    );
    let result = repo.change_publication_retention(&attempted, TIMEOUT, &mut |_| {
        publish(&repo, "concurrent-writer"); // must run outside the lifecycle/admission fences
        Ok(())
    });
    assert_eq!(result.unwrap_err().code, PlatformErrorCode::StateConflict);
    assert!(snapshot(&repo, &[publication]).selections[0].pin.is_none());
    assert!(!root.path().join("lifecycle/retention/INTENT").exists());
}

#[test]
fn interrupted_native_intent_head_and_removal_recover_only_the_original_operation() {
    for point in [
        DevelopmentRetentionFault::AfterIntent,
        DevelopmentRetentionFault::AfterHead,
        DevelopmentRetentionFault::AfterIntentRemoval,
    ] {
        let root = Root::new();
        let repo = root.open();
        let publication = publish(&repo, "interrupted");
        let attempted = request(
            &repo,
            std::slice::from_ref(&publication),
            "original",
            PublicationRetentionAction::Pin,
        );
        repo.inject_retention_fault_for_test(point);
        assert!(mutate(&repo, attempted.clone()).is_err());
        assert_eq!(
            repo.publication_retention_operation(&scope(), "original")
                .unwrap(),
            PublicationRetentionLookup::Uncertain
        );
        assert!(repo.publication_capacity_snapshot().is_err());
        assert!(repo
            .publication_execution_eligibility(&publication)
            .is_err());
        drop(repo);
        let reopened = root.open();
        assert!(
            snapshot(&reopened, std::slice::from_ref(&publication)).selections[0]
                .pin
                .is_some()
        );
        let PublicationRetentionLookup::Found(receipt) = reopened
            .publication_retention_operation(&scope(), "original")
            .unwrap()
        else {
            panic!("original durable receipt");
        };
        assert_eq!(receipt.request, attempted);
        assert!(mutate(&reopened, attempted).unwrap().replay);
        assert!(!root.path().join("lifecycle/retention/INTENT").exists());
    }
}

#[test]
fn interrupted_format_promotion_does_not_invent_a_committed_pin() {
    let root = Root::new();
    let repo = root.open();
    let publication = publish(&repo, "promotion");
    let attempted = request(
        &repo,
        std::slice::from_ref(&publication),
        "not-started",
        PublicationRetentionAction::Pin,
    );
    repo.inject_retention_fault_for_test(DevelopmentRetentionFault::AfterFormatPromotion);
    assert!(mutate(&repo, attempted).is_err());
    drop(repo);
    let reopened = root.open();
    assert!(snapshot(&reopened, &[publication]).selections[0]
        .pin
        .is_none());
    assert_eq!(
        reopened
            .publication_retention_operation(&scope(), "not-started")
            .unwrap(),
        PublicationRetentionLookup::Unknown
    );
    assert_ne!(
        fs::read(root.path().join("LIFECYCLE_MODE")).unwrap(),
        b"lsf-release-lifecycle-v1\n"
    );
}

#[test]
fn corrupt_missing_or_retargeted_retention_authority_is_rejected_before_cleanup() {
    for damage in ["corrupt", "missing", "retargeted"] {
        let root = Root::new();
        let repo = root.open();
        let publication = publish(&repo, "protected");
        mutate(
            &repo,
            request(
                &repo,
                &[publication],
                "protect",
                PublicationRetentionAction::Pin,
            ),
        )
        .unwrap();
        drop(repo);
        let head = root.path().join("lifecycle/retention/HEAD");
        match damage {
            "missing" => fs::remove_file(&head).unwrap(),
            "corrupt" => fs::write(&head, b"{}").unwrap(),
            _ => {
                let mut value: serde_json::Value =
                    serde_json::from_slice(&fs::read(&head).unwrap()).unwrap();
                value["head"]["pins"][0]["pinnedGeneration"] = 999.into();
                fs::write(&head, serde_json::to_vec(&value).unwrap()).unwrap();
            }
        }
        fs::write(
            root.path().join(".tmp/must-survive"),
            b"protected pending bytes",
        )
        .unwrap();
        assert!(DirectoryArtifactRepository::open(
            root.path(),
            DirectoryArtifactRepositoryConfig::default()
        )
        .is_err());
        assert_eq!(
            fs::read(root.path().join(".tmp/must-survive")).unwrap(),
            b"protected pending bytes"
        );
    }
}

#[test]
fn receipt_eviction_returns_unknown_and_does_not_reapply_the_old_fence() {
    let root = Root::new();
    let repo = root.open();
    let publication = publish(&repo, "receipt-ring");
    let original = request(
        &repo,
        std::slice::from_ref(&publication),
        "original",
        PublicationRetentionAction::Pin,
    );
    mutate(&repo, original.clone()).unwrap();
    for n in 0..MAX_PUBLICATION_RETENTION_RECEIPTS {
        let action = if n % 2 == 0 {
            PublicationRetentionAction::Unpin
        } else {
            PublicationRetentionAction::Pin
        };
        mutate(
            &repo,
            request(
                &repo,
                std::slice::from_ref(&publication),
                &format!("later-{n}"),
                action,
            ),
        )
        .unwrap();
    }
    assert_eq!(
        repo.publication_retention_operation(&scope(), "original")
            .unwrap(),
        PublicationRetentionLookup::Unknown
    );
    assert_eq!(
        mutate(&repo, original).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    drop(repo);
    let reopened = root.open();
    assert_eq!(
        reopened
            .publication_retention_operation(&scope(), "original")
            .unwrap(),
        PublicationRetentionLookup::Unknown
    );
}

#[test]
fn operation_identity_collision_is_not_an_unpin_or_a_foreign_receipt() {
    let root = Root::new();
    let repo = root.open();
    let publication = publish(&repo, "identity");
    let original = request(
        &repo,
        std::slice::from_ref(&publication),
        "same-id",
        PublicationRetentionAction::Pin,
    );
    mutate(&repo, original.clone()).unwrap();
    let mut changed = original;
    changed.action = PublicationRetentionAction::Unpin;
    assert_eq!(
        mutate(&repo, changed).unwrap_err().code,
        PlatformErrorCode::StateConflict
    );
    assert!(snapshot(&repo, &[publication]).selections[0].pin.is_some());
    assert_eq!(
        repo.publication_retention_operation(
            &LifecycleScope::Tenant(TenantId("foreign".into())),
            "same-id"
        )
        .unwrap(),
        PublicationRetentionLookup::Unknown
    );
}

#[test]
fn exhausted_storage_and_metadata_budgets_refuse_before_intent() {
    for metadata in [false, true] {
        let root = Root::new();
        let repo = root.open();
        let publication = publish(&repo, "budget");
        let before = repo.publication_capacity_snapshot().unwrap();
        drop(repo);
        let mut config = DirectoryArtifactRepositoryConfig::default();
        if metadata {
            config.max_index_bytes = before.index_bytes + 1;
        } else {
            config.max_storage_bytes = before.charged_storage_bytes + 1;
        }
        let repo = DirectoryArtifactRepository::open(root.path(), config).unwrap();
        let attempted = request(
            &repo,
            std::slice::from_ref(&publication),
            "over-budget",
            PublicationRetentionAction::Pin,
        );
        assert_eq!(
            mutate(&repo, attempted).unwrap_err().code,
            PlatformErrorCode::ResourceExhausted
        );
        assert!(!root.path().join("lifecycle/retention/HEAD").exists());
        assert_eq!(
            repo.publication_capacity_snapshot()
                .unwrap()
                .charged_storage_bytes,
            before.charged_storage_bytes
        );
    }
}

#[test]
fn retention_accounting_is_restored_without_refunding_publication_payloads() {
    let root = Root::new();
    let repo = root.open();
    let publication = publish(&repo, "accounting");
    let before = repo.publication_capacity_snapshot().unwrap();
    mutate(
        &repo,
        request(
            &repo,
            &[publication],
            "pin",
            PublicationRetentionAction::Pin,
        ),
    )
    .unwrap();
    let after = repo.publication_capacity_snapshot().unwrap();
    assert!(after.storage.retention_control_bytes > 0);
    assert_eq!(
        after.storage.publication_file_bytes,
        before.storage.publication_file_bytes
    );
    assert_eq!(
        after.storage.shared_blob_bytes,
        before.storage.shared_blob_bytes
    );
    assert_eq!(after.indexed_publications, before.indexed_publications);
    assert_eq!(
        after.charged_storage_bytes - before.charged_storage_bytes,
        after.storage.retention_control_bytes
    );
    drop(repo);
    let reopened = root.open();
    assert_eq!(reopened.publication_capacity_snapshot().unwrap(), after);
}

#[test]
fn elapsed_preflight_deadline_does_not_commit_or_refund_anything() {
    let root = Root::new();
    let repo = root.open();
    let publication = publish(&repo, "deadline");
    let attempted = request(
        &repo,
        &[publication],
        "expired",
        PublicationRetentionAction::Pin,
    );
    let before = repo.publication_capacity_snapshot().unwrap();
    let failure = repo
        .change_publication_retention(&attempted, Duration::from_millis(5), &mut |_| {
            std::thread::sleep(Duration::from_millis(10));
            Ok(())
        })
        .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::DeadlineExceeded);
    assert!(!root.path().join("lifecycle/retention/HEAD").exists());
    assert_eq!(repo.publication_capacity_snapshot().unwrap(), before);
}

#[path = "publication_retention/web.rs"]
mod web;

#[test]
fn componentless_web_pin_survives_retirement_and_native_reopen_without_serving_authority() {
    let root = Root::new();
    let repo = web::open(&root);
    let publication = web::publish(&repo);
    let held = repo.select_web_publication(&publication).unwrap();
    mutate(
        &repo,
        request(
            &repo,
            std::slice::from_ref(&publication),
            "pin-web",
            PublicationRetentionAction::Pin,
        ),
    )
    .unwrap();
    repo.read_web_asset(&publication, "/index.html").unwrap();
    repo.transition_web_publication(
        context("retire-web", 1),
        &publication,
        ReleaseLifecycleAction::Retire,
        ReleaseLifecycleReason::OperatorRetirement,
        &mut |_| Ok(()),
    )
    .unwrap();
    assert!(held
        .with_current(scope().tenant().unwrap(), &mut |_| Ok(()))
        .is_err());
    assert!(
        snapshot(&repo, std::slice::from_ref(&publication)).selections[0]
            .pin
            .is_some()
    );
    drop(held);
    drop(repo);
    let reopened = web::open(&root);
    assert!(
        snapshot(&reopened, std::slice::from_ref(&publication)).selections[0]
            .pin
            .is_some()
    );
    assert!(reopened
        .read_web_asset(&publication, "/index.html")
        .is_err());
    mutate(
        &reopened,
        request(
            &reopened,
            std::slice::from_ref(&publication),
            "unpin-web",
            PublicationRetentionAction::Unpin,
        ),
    )
    .unwrap();
    assert!(reopened.select_web_publication(&publication).is_err());
}

#[test]
fn stopped_full_backup_preserves_pins_receipts_hardlinks_and_terminal_authority() {
    use std::{
        collections::BTreeMap,
        os::unix::fs::MetadataExt,
        path::{Path, PathBuf},
    };
    fn copy(
        source: &Path,
        destination: &Path,
        links: &mut BTreeMap<(u64, u64), PathBuf>,
        count: &mut usize,
    ) {
        for entry in fs::read_dir(source).unwrap() {
            *count += 1;
            assert!(*count <= 10_000, "finite native backup fixture");
            let entry = entry.unwrap();
            let metadata = fs::symlink_metadata(entry.path()).unwrap();
            let target = destination.join(entry.file_name());
            if metadata.is_dir() {
                fs::create_dir(&target).unwrap();
                copy(&entry.path(), &target, links, count);
            } else {
                assert!(metadata.is_file() && !metadata.file_type().is_symlink());
                let identity = (metadata.dev(), metadata.ino());
                if let Some(original) = links.get(&identity) {
                    fs::hard_link(original, &target).unwrap();
                } else {
                    fs::copy(entry.path(), &target).unwrap();
                    links.insert(identity, target.clone());
                }
            }
            fs::set_permissions(&target, metadata.permissions()).unwrap();
        }
    }
    let source = Root::new();
    let repo = source.open();
    let publication = publish(&repo, "backup");
    let other = publish(&repo, "shared-backup");
    let original = request(
        &repo,
        std::slice::from_ref(&publication),
        "protect-backup",
        PublicationRetentionAction::Pin,
    );
    let receipt = mutate(&repo, original).unwrap().receipt;
    retire(&repo, &publication);
    let capacity = repo.publication_capacity_snapshot().unwrap();
    drop(repo);
    let destination = Root::new();
    let mut count = 0;
    copy(
        source.path(),
        destination.path(),
        &mut BTreeMap::new(),
        &mut count,
    );
    let first = destination
        .path()
        .join("publications")
        .join(publication.id.hex())
        .join("component.wasm");
    let second = destination
        .path()
        .join("publications")
        .join(other.id.hex())
        .join("component.wasm");
    assert_eq!(
        fs::metadata(first).unwrap().ino(),
        fs::metadata(second).unwrap().ino()
    );
    let restored = destination.open();
    assert_eq!(restored.publication_capacity_snapshot().unwrap(), capacity);
    assert!(
        snapshot(&restored, std::slice::from_ref(&publication)).selections[0]
            .pin
            .is_some()
    );
    assert_eq!(
        restored
            .publication_retention_operation(&scope(), "protect-backup")
            .unwrap(),
        PublicationRetentionLookup::Found(receipt)
    );
    assert!(restored
        .publication_execution_eligibility(&publication)
        .is_err());
    restored
        .publication_execution_eligibility(&other)
        .unwrap()
        .check_current()
        .unwrap();
}

#[path = "publication_retention/lexical.rs"]
mod lexical;
