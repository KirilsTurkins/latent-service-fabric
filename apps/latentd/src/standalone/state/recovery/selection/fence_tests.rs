//! Actual Codecs final acceptance on real signed sources, policy and native writer.
mod fixture;
mod joint;
use fixture::Fixture;
use latent_state::embedded::StoreError;

#[tokio::test]
async fn actual_signed_codec_writer_fence_commits_once_without_reentering_publication_owner() {
    let fixture = Fixture::new(false).await;
    let outcome = fixture.write("namespace-resume", false).await;
    fixture.finish().await;
    assert_eq!(
        outcome.result,
        Ok(()),
        "actual signed Codecs acceptance after physical owner retirement"
    );
    assert!(outcome.action_entered && outcome.metadata_changed);
}

#[tokio::test]
async fn actual_nested_signed_publication_policy_entry_stays_busy_without_accepting_work() {
    let fixture = Fixture::new(false).await;
    let captured = fixture.captured("native", "namespace-resume");
    let dependencies = fixture
        .codecs
        .catalog
        .schemas
        .iter()
        .map(|row| row.operation.publication().clone())
        .collect::<Vec<_>>();
    let mut called = false;
    let result =
        latent_artifacts::ReleaseUseEligibility::with_all_current(&dependencies, &mut |_| {
            fixture
                .policy
                .with_retained_decisions(&[&captured], &mut |_| {
                    called = true;
                    Ok(())
                })
        });
    drop((captured, dependencies));
    fixture.finish().await;
    assert!(!called);
    let failure = result.unwrap_err();
    assert_eq!(failure.message, "admission-authority-busy");
}

#[tokio::test]
async fn actual_signed_restore_fence_retains_both_original_purposes() {
    for purpose in ["namespace-inspect-restore", "namespace-restore"] {
        let fixture = Fixture::new(true).await;
        let outcome = fixture.write(purpose, false).await;
        fixture.finish().await;
        assert_eq!(outcome.result, Ok(()));
        assert!(outcome.action_entered && outcome.metadata_changed);
    }
}

#[tokio::test]
async fn revoked_primary_or_secondary_signed_publication_refuses_actual_metadata_acceptance() {
    for secondary in [false, true] {
        let fixture = Fixture::new(false).await;
        fixture.codecs.check().unwrap();
        fixture.revoke_publication(secondary);
        let outcome = fixture.write("namespace-resume", false).await;
        fixture.finish().await;
        assert!(outcome.result.is_err());
        assert!(!outcome.action_entered && !outcome.metadata_changed);
    }
}

#[tokio::test]
async fn changed_original_policy_or_binding_refuses_actual_metadata_acceptance() {
    for binding in [false, true] {
        let fixture = Fixture::new(false).await;
        fixture.codecs.check().unwrap();
        fixture.revoke_policy(false, binding);
        let outcome = fixture.write("namespace-resume", false).await;
        fixture.finish().await;
        assert_eq!(outcome.result, Err(StoreError::Unavailable));
        assert!(!outcome.action_entered && !outcome.metadata_changed);
    }
}

#[tokio::test]
async fn original_clock_regression_or_foreign_purpose_refuses_actual_metadata_acceptance() {
    for wrong_purpose in [false, true] {
        let fixture = Fixture::new(false).await;
        if !wrong_purpose {
            fixture.clock.regress();
        }
        let purpose = if wrong_purpose {
            "namespace-restore"
        } else {
            "namespace-resume"
        };
        let outcome = fixture.write(purpose, false).await;
        fixture.finish().await;
        assert_eq!(outcome.result, Err(StoreError::Unavailable));
        assert!(!outcome.action_entered && !outcome.metadata_changed);
    }
}

#[tokio::test]
async fn original_native_close_refuses_accepted_writer_until_real_keeper_and_store_retire() {
    let fixture = Fixture::new(false).await;
    let outcome = fixture.write("namespace-resume", true).await;
    assert!(outcome.result.is_err());
    assert!(!outcome.action_entered && !outcome.metadata_changed);
    assert_eq!(fixture.native.snapshot().unwrap().recovery.slots, 1);
    fixture.finish().await;
}

#[tokio::test]
async fn actual_original_policy_cutoff_refuses_writer_without_renewing_native_admission() {
    let fixture = Fixture::expiring().await;
    let cutoff = fixture.codecs.authority.deadline;
    assert!(cutoff < fixture.codecs.original.original_deadline());
    tokio::time::sleep_until(cutoff.into()).await;
    let outcome = fixture.write("namespace-resume", false).await;
    fixture.finish().await;
    assert_eq!(outcome.result, Err(StoreError::Unavailable));
    assert!(!outcome.action_entered && !outcome.metadata_changed);
}
