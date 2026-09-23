//! Small real directory transactions; no guest execution or load campaign.
#[cfg(unix)]
#[path = "lifecycle_tests/audit.rs"]
mod audit;
use super::*;
use crate::{
    LifecycleScope, ManagedPublicationUpload, ReleaseActor, ReleaseActorKind,
    ReleaseLifecycleAction, ReleaseLifecycleReason, ReleaseLifecycleState, ReleaseLiveEligibility,
    ReleaseMutationContext, ReleaseOperationDisposition, ReleaseOperationLookup,
    ReleaseOperationPrecondition, ReleaseOperationPreview,
};
use latent_core::{PlatformError, TenantId};

fn scoped_artifact(label: &str) -> CapsuleArtifact {
    artifact(label, label.as_bytes())
}
pub(super) fn scope() -> LifecycleScope {
    LifecycleScope::Tenant(TenantId("examples".to_owned()))
}
pub(super) fn context(id: &str, generation: u64) -> ReleaseMutationContext {
    ReleaseMutationContext {
        scope: scope(),
        actor: ReleaseActor {
            subject: "authenticated-test-admin".to_owned(),
            kind: ReleaseActorKind::Administrator,
        },
        operation: Some(ReleaseOperationPrecondition {
            operation_id: id.to_owned(),
            expected_generation: generation,
        }),
    }
}
pub(super) fn accept(_: ReleaseOperationPreview<'_>) -> Result<(), PlatformError> {
    Ok(())
}
fn reject(_: ReleaseOperationPreview<'_>) -> Result<(), PlatformError> {
    Err(super::super::resource_exhausted("test-response-budget"))
}

#[test]
fn managed_publication_exact_replay_and_cas_rejection_have_distinct_outcomes() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let value = scoped_artifact("managed");
    let publication = repo.local_publication_ref(&value).unwrap();
    let release = value.descriptor.release_digest.clone();
    let first = block_on(repo.publish_managed(
        context("create", 0),
        ManagedPublicationUpload::Local(value.clone()),
        &mut accept,
    ))
    .unwrap();
    assert_eq!(
        first.operation.disposition,
        ReleaseOperationDisposition::Committed
    );
    assert_eq!(first.operation.record.as_ref().unwrap().generation, 1);
    let replay = block_on(repo.publish_managed(
        context("create", 0),
        ManagedPublicationUpload::Local(value.clone()),
        &mut accept,
    ))
    .unwrap();
    assert_eq!(replay, first);
    let failure = block_on(repo.publish_managed(
        context("wrong-cas", 0),
        ManagedPublicationUpload::Local(value),
        &mut accept,
    ))
    .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::StateConflict);
    let ReleaseOperationLookup::Found(rejected) =
        block_on(repo.get_selected_operation(&scope(), "wrong-cas"))
            .unwrap()
            .1
    else {
        panic!("rejected CAS receipt")
    };
    assert_eq!(rejected.disposition, ReleaseOperationDisposition::Rejected);
    assert_eq!(rejected.reason, ReleaseLifecycleReason::GenerationConflict);
    let status = block_on(repo.get_selected_lifecycle(&scope(), &publication))
        .unwrap()
        .unwrap();
    assert_eq!(status.record.generation, 1);
    assert_eq!(status.eligibility, ReleaseLiveEligibility::Eligible);
    assert!(repo.execution_eligibility(&release).unwrap().is_some());
}
#[test]
fn operation_identity_conflict_does_not_publish_different_content() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let first = scoped_artifact("first");
    let second = scoped_artifact("second");
    let second_digest = second.descriptor.release_digest.clone();
    let second_publication = repo.local_publication_ref(&second).unwrap();
    block_on(repo.publish_managed(
        context("shared-id", 0),
        ManagedPublicationUpload::Local(first),
        &mut accept,
    ))
    .unwrap();
    assert_eq!(
        block_on(repo.publish_managed(
            context("shared-id", 0),
            ManagedPublicationUpload::Local(second),
            &mut accept
        ))
        .unwrap_err()
        .code,
        PlatformErrorCode::StateConflict
    );
    assert!(
        block_on(repo.get_selected_lifecycle(&scope(), &second_publication))
            .unwrap()
            .is_none()
    );
    assert!(!release_dir(temp.path(), &second_digest).exists());
}
#[test]
fn new_metadata_cannot_reuse_another_publications_generation() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let first = scoped_artifact("content-conflict");
    let digest = first.descriptor.release_digest.clone();
    block_on(repo.publish_managed(
        context("original", 0),
        ManagedPublicationUpload::Local(first.clone()),
        &mut accept,
    ))
    .unwrap();
    let mut changed = first.clone();
    changed.contracts[0].digest = "changed-exact-metadata".to_owned();
    let failure = block_on(repo.publish_managed(
        context("conflict", 1),
        ManagedPublicationUpload::Local(changed),
        &mut accept,
    ))
    .unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::StateConflict);
    let ReleaseOperationLookup::Found(receipt) =
        block_on(repo.get_selected_operation(&scope(), "conflict"))
            .unwrap()
            .1
    else {
        panic!("retained rejection")
    };
    assert_eq!(receipt.reason, ReleaseLifecycleReason::GenerationConflict);
    assert!(
        receipt.record.is_none(),
        "new publication has no committed generation"
    );
    assert_eq!(block_on(repo.fetch(&digest)).unwrap(), first);
    let other = LifecycleScope::Tenant(TenantId("other-tenant".to_owned()));
    assert!(matches!(
        block_on(repo.get_selected_operation(&other, "conflict"))
            .unwrap()
            .1,
        ReleaseOperationLookup::Unknown
    ));
    let mut foreign = repo.local_publication_ref(&first).unwrap();
    foreign.scope = other.clone();
    assert!(block_on(repo.get_selected_lifecycle(&other, &foreign))
        .unwrap()
        .is_none());
}
#[test]
fn revoke_then_retire_survives_reopen_and_old_success_receipt_remains_history() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let value = scoped_artifact("retirement");
    let publication = repo.local_publication_ref(&value).unwrap();
    let release = value.descriptor.release_digest.clone();
    let original = block_on(repo.publish_managed(
        context("create", 0),
        ManagedPublicationUpload::Local(value.clone()),
        &mut accept,
    ))
    .unwrap();
    let held = repo.execution_eligibility(&release).unwrap().unwrap();
    repo.change_publication_lifecycle(
        context("revoke", 1),
        &publication,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::SecurityIncident,
        &mut accept,
    )
    .unwrap();
    assert!(held.check_current().is_err());
    assert!(block_on(repo.fetch(&release)).is_err());
    let retired = repo
        .change_publication_lifecycle(
            context("retire", 2),
            &publication,
            ReleaseLifecycleAction::Retire,
            ReleaseLifecycleReason::EndOfSupport,
            &mut accept,
        )
        .unwrap();
    assert_eq!(retired.record.as_ref().unwrap().generation, 3);
    drop(repo);
    let reopened = repository(temp.path());
    let status = block_on(reopened.get_selected_lifecycle(&scope(), &publication))
        .unwrap()
        .unwrap();
    assert_eq!(status.record.state, ReleaseLifecycleState::Retired);
    assert_eq!(status.eligibility, ReleaseLiveEligibility::Denied);
    assert!(block_on(reopened.fetch(&release)).is_err());
    assert!(held.check_current().is_err());
    let replay = block_on(reopened.publish_managed(
        context("create", 0),
        ManagedPublicationUpload::Local(value),
        &mut accept,
    ))
    .unwrap();
    assert_eq!(replay.operation, original.operation);
    assert!(reopened.execution_eligibility(&release).is_err());
}
#[test]
fn response_budget_preflight_prevents_success_and_rejection_side_effects() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    for invalid in [false, true] {
        let mut value = scoped_artifact(if invalid {
            "invalid-budget"
        } else {
            "valid-budget"
        });
        let release = value.descriptor.release_digest.clone();
        let publication = repo.local_publication_ref(&value).unwrap();
        let id = if invalid {
            "invalid-budget"
        } else {
            "valid-budget"
        };
        if invalid {
            value.descriptor.release_digest = release_digest(b"wrong-declared-content");
        }
        assert_eq!(
            block_on(repo.publish_managed(
                context(id, 0),
                ManagedPublicationUpload::Local(value),
                &mut reject
            ))
            .unwrap_err()
            .code,
            PlatformErrorCode::ResourceExhausted
        );
        assert!(!release_dir(temp.path(), &release).exists());
        assert!(
            block_on(repo.get_selected_lifecycle(&scope(), &publication))
                .unwrap()
                .is_none()
        );
        assert!(matches!(
            block_on(repo.get_selected_operation(&scope(), id))
                .unwrap()
                .1,
            ReleaseOperationLookup::Unknown
        ));
    }
    assert!(block_on(repo.list(None, 10)).unwrap().entries.is_empty());
}
#[test]
fn renamed_complete_without_lifecycle_membership_stays_hidden_on_reopen() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let value = scoped_artifact("orphan");
    let publication = repo.local_publication_ref(&value).unwrap();
    let release = value.descriptor.release_digest.clone();
    repo.inject_parent_sync_failure_once();
    assert!(block_on(repo.publish_managed(
        context("recoverable", 0),
        ManagedPublicationUpload::Local(value.clone()),
        &mut accept
    ))
    .is_err());
    assert!(release_dir(temp.path(), &release).join("COMPLETE").exists());
    drop(repo);
    let reopened = repository(temp.path());
    assert!(block_on(reopened.list(None, 10))
        .unwrap()
        .entries
        .is_empty());
    assert!(
        block_on(reopened.get_selected_lifecycle(&scope(), &publication))
            .unwrap()
            .is_none()
    );
    assert!(block_on(reopened.fetch(&release)).is_err());
    let admitted = block_on(reopened.publish_managed(
        context("recoverable", 0),
        ManagedPublicationUpload::Local(value.clone()),
        &mut accept,
    ))
    .unwrap();
    assert_eq!(admitted.operation.record.as_ref().unwrap().generation, 1);
    assert_eq!(block_on(reopened.fetch(&release)).unwrap(), value);
}

#[test]
fn orphan_stays_hidden_while_an_independent_publication_can_commit() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let first = scoped_artifact("reserved-orphan");
    let release = first.descriptor.release_digest.clone();
    repo.inject_parent_sync_failure_once();
    assert!(block_on(repo.publish_managed(
        context("orphan-create", 0),
        ManagedPublicationUpload::Local(first.clone()),
        &mut accept
    ))
    .is_err());
    drop(repo);
    let reopened = repository(temp.path());
    let mut second = scoped_artifact("different-content");
    let second_release = second.descriptor.release_digest.clone();
    second.descriptor.reference = first.descriptor.reference.clone();
    block_on(reopened.publish_managed(
        context("independent-publication", 0),
        ManagedPublicationUpload::Local(second),
        &mut accept,
    ))
    .unwrap();
    assert!(release_dir(temp.path(), &second_release).exists());
    assert_eq!(
        block_on(reopened.fetch(&release)).unwrap_err().code,
        PlatformErrorCode::NotFound
    );
    assert_eq!(block_on(reopened.list(None, 10)).unwrap().entries.len(), 1);
    drop(reopened);
    let reopened = repository(temp.path());
    block_on(reopened.publish_managed(
        context("orphan-create", 0),
        ManagedPublicationUpload::Local(first.clone()),
        &mut accept,
    ))
    .unwrap();
    assert_eq!(block_on(reopened.fetch(&release)).unwrap(), first);
    drop(reopened);
    assert_eq!(
        block_on(repository(temp.path()).list(None, 10))
            .unwrap()
            .entries
            .len(),
        2
    );
}

#[test]
fn interrupted_root_marker_temporary_does_not_reset_verified_lifecycle_history() {
    let temp = TempRoot::new();
    let repo = repository(temp.path());
    let value = scoped_artifact("marker-history");
    let publication = repo.local_publication_ref(&value).unwrap();
    let release = value.descriptor.release_digest.clone();
    block_on(repo.publish_managed(
        context("create", 0),
        ManagedPublicationUpload::Local(value),
        &mut accept,
    ))
    .unwrap();
    repo.change_publication_lifecycle(
        context("revoke", 1),
        &publication,
        ReleaseLifecycleAction::Revoke,
        ReleaseLifecycleReason::OperatorRevocation,
        &mut accept,
    )
    .unwrap();
    drop(repo);
    // Model an absent final root marker plus the partial bounded staging file.
    // Existing MODE/INITIALIZED/HEAD must still govern recovery and membership.
    fs::remove_file(temp.path().join("LIFECYCLE_MODE")).unwrap();
    fs::write(temp.path().join("LIFECYCLE_MODE.next"), b"lsf-release").unwrap();
    let reopened = repository(temp.path());
    let status = block_on(reopened.get_selected_lifecycle(&scope(), &publication))
        .unwrap()
        .unwrap();
    assert_eq!(status.record.state, ReleaseLifecycleState::Revoked);
    assert_eq!(status.record.generation, 2);
    assert_eq!(
        fs::read(temp.path().join("LIFECYCLE_MODE")).unwrap(),
        b"lsf-release-lifecycle-v1\n"
    );
    assert!(!temp.path().join("LIFECYCLE_MODE.next").exists());
    assert!(block_on(reopened.fetch(&release)).is_err());
}
