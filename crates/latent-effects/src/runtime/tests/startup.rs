//! Bootstrap suppression is separate from the actual durable operator latch.
use super::control::{apply, request};
use super::*;

async fn suppressed(
    fixture: &Fixture,
    config: DispatcherConfig,
    adapters: Vec<Arc<dyn DeferredEffectAdapter>>,
    checkpoint: Option<(u64, u64)>,
) -> DispatcherOwner {
    let owner = DispatcherOwner::start_with_startup_suppression(
        config,
        fixture.store.clone(),
        fixture.authority.clone(),
        adapters,
        fixture.clock.clone(),
        checkpoint,
        tokio::runtime::Handle::current(),
    )
    .await
    .unwrap();
    if !owner.snapshot().unwrap().control.restore_review_required {
        owner.bind_native_capacity(&fixture.capacity).unwrap();
    }
    owner
}

async fn stop(fixture: &Fixture, mut owner: DispatcherOwner) {
    let report = owner.shutdown(Instant::now() + WATCHDOG).await.unwrap();
    assert!(report.clean && report.physically_retired && report.scheduling_owner_retired);
    drop(owner);
    fixture.finish().await;
}

#[tokio::test]
async fn startup_release_keeps_saved_pause_and_literal_pending_effect_across_owner_restart() {
    let fixture = Fixture::new().await;
    let mut first = fixture.start(config(), vec![], None).await.unwrap();
    let original = request(
        &first,
        "saved-bootstrap-pause",
        DispatcherControlAction::Pause,
    );
    let receipt = apply(&first, original.clone()).await.receipt;
    assert!(
        first
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    drop(first);
    let effect = fixture
        .seed(8, "tenant-a", "publication", profile("test.v1"))
        .await;
    let pending = fixture.record(&effect).await.encode().unwrap();
    let (adapter, _events) = Adapter::new("test.v1", None);
    let owner = suppressed(
        &fixture,
        config(),
        vec![adapter.clone()],
        Some((receipt.generation().owner_epoch(), 100)),
    )
    .await;
    assert!(
        owner.snapshot().unwrap().control.generation.owner_epoch()
            > receipt.generation().owner_epoch()
    );
    owner.release_startup().unwrap();
    assert!(owner.snapshot().unwrap().paused);
    assert_eq!(
        fixture.record(&effect).await.disposition(),
        Disposition::Pending
    );
    assert_eq!(fixture.record(&effect).await.encode().unwrap(), pending);
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    assert_eq!(
        owner
            .lookup_control(original.clone())
            .unwrap()
            .await
            .unwrap()
            .unwrap(),
        Some(receipt.clone())
    );
    let generation = owner.snapshot().unwrap().control.generation;
    assert!(matches!(
        owner.prepare_control(original),
        Err(DispatcherControlError::Conflict)
    ));
    assert_eq!(owner.snapshot().unwrap().control.generation, generation);
    let resumed = apply(
        &owner,
        request(
            &owner,
            "explicit-after-bootstrap",
            DispatcherControlAction::Resume,
        ),
    )
    .await;
    assert!(resumed.published && !resumed.paused);
    wait_disposition(&fixture, &effect, Disposition::ProviderAcknowledged).await;
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    stop(&fixture, owner).await;
}

#[tokio::test]
async fn current_pause_winning_readiness_release_remains_the_original_operator_intent() {
    let fixture = Fixture::new().await;
    let owner = suppressed(&fixture, config(), vec![], None).await;
    let original = request(&owner, "pause-before-ready", DispatcherControlAction::Pause);
    let retained_replay = owner.prepare_control(original.clone()).unwrap();
    let receipt = apply(&owner, original.clone()).await.receipt;
    owner.release_startup().unwrap();
    let snapshot = owner.snapshot().unwrap();
    assert!(snapshot.paused && !snapshot.control.pending);
    assert_eq!(
        owner
            .lookup_control(original)
            .unwrap()
            .await
            .unwrap()
            .unwrap(),
        Some(receipt)
    );
    let generation = snapshot.control.generation;
    let replay = owner
        .submit_control(retained_replay, |accept| accept())
        .unwrap()
        .await
        .unwrap()
        .unwrap()
        .unwrap();
    assert!(replay.replayed && !replay.published && replay.paused);
    assert_eq!(owner.snapshot().unwrap().control.generation, generation);
    stop(&fixture, owner).await;
}

#[tokio::test]
async fn managed_resume_under_bootstrap_hold_waits_for_actual_readiness_release() {
    let fixture = Fixture::new().await;
    let effect = fixture
        .seed(9, "tenant-a", "publication", profile("test.v1"))
        .await;
    let pending = fixture.record(&effect).await.encode().unwrap();
    let (adapter, _events) = Adapter::new("test.v1", None);
    let owner = suppressed(
        &fixture,
        DispatcherConfig {
            start_paused: true,
            ..config()
        },
        vec![adapter.clone()],
        None,
    )
    .await;
    let result = apply(
        &owner,
        request(
            &owner,
            "resume-before-ready",
            DispatcherControlAction::Resume,
        ),
    )
    .await;
    assert!(result.paused && !result.published && !result.replayed);
    assert_eq!(
        result.receipt.request().action(),
        DispatcherControlAction::Resume
    );
    assert_eq!(fixture.record(&effect).await.encode().unwrap(), pending);
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    owner.release_startup().unwrap();
    assert!(!owner.snapshot().unwrap().paused);
    wait_disposition(&fixture, &effect, Disposition::ProviderAcknowledged).await;
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    stop(&fixture, owner).await;
}

#[tokio::test]
async fn ordinary_configured_pause_and_managed_resume_keep_original_no_hold_semantics() {
    let fixture = Fixture::new().await;
    let owner = fixture
        .start(
            DispatcherConfig {
                start_paused: true,
                ..config()
            },
            vec![],
            None,
        )
        .await
        .unwrap();
    let generation = owner.snapshot().unwrap().control.generation;
    owner.release_startup().unwrap();
    assert!(owner.snapshot().unwrap().paused);
    assert_eq!(owner.snapshot().unwrap().control.generation, generation);
    let outcome = apply(
        &owner,
        request(&owner, "ordinary-resume", DispatcherControlAction::Resume),
    )
    .await;
    assert!(outcome.published && !outcome.paused);
    stop(&fixture, owner).await;
}

#[tokio::test]
async fn startup_release_refuses_current_restore_review_closed_and_discontinuous_owners() {
    for cause in 0..3 {
        let fixture = Fixture::new().await;
        let owner = suppressed(
            &fixture,
            DispatcherConfig {
                start_in_restore_review: cause == 0,
                ..config()
            },
            vec![],
            None,
        )
        .await;
        let generation = owner.snapshot().unwrap().control.generation;
        if cause == 1 {
            owner.close();
        }
        if cause == 2 {
            fixture.clock.continuous.store(false, Ordering::SeqCst);
        }
        let result = owner.release_startup();
        let expected = match cause {
            0 => DispatcherError::CheckpointRequired,
            1 => DispatcherError::AdmissionClosed,
            _ => AuthorityError::ClockDiscontinuity.into(),
        };
        assert_eq!(result, Err(expected));
        let snapshot = owner.snapshot().unwrap();
        assert!(snapshot.paused);
        assert_eq!(snapshot.control.generation, generation);
        if cause == 0 {
            assert!(snapshot.control.restore_review_required);
        }
        fixture.clock.continuous.store(true, Ordering::SeqCst);
        stop(&fixture, owner).await;
    }
}

#[tokio::test]
async fn unknown_accepted_pause_cannot_be_cleared_by_startup_release() {
    let fixture = Fixture::new().await;
    let owner = suppressed(&fixture, config(), vec![], None).await;
    let original = request(&owner, "unresolved-pause", DispatcherControlAction::Pause);
    let prepared = owner.prepare_control(original.clone()).unwrap();
    let result = owner
        .submit_control(prepared, |accept| {
            accept()?;
            accept()
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(matches!(
        result,
        Err(DispatcherControlError::InvalidAuthorizationFence)
    ));
    assert_eq!(
        owner.release_startup(),
        Err(DispatcherError::AdmissionClosed)
    );
    let snapshot = owner.snapshot().unwrap();
    assert!(snapshot.paused && snapshot.control.pending);
    assert_eq!(
        owner
            .lookup_control(original)
            .unwrap()
            .await
            .unwrap()
            .unwrap(),
        None
    );
    stop(&fixture, owner).await;
}

#[tokio::test]
async fn non_http_readiness_keeps_historical_resume_paused_until_current_owner_resume() {
    let fixture = Fixture::new().await;
    let mut first = fixture
        .start(
            DispatcherConfig {
                start_paused: true,
                ..config()
            },
            vec![],
            None,
        )
        .await
        .unwrap();
    let original = request(
        &first,
        "historical-non-http-resume",
        DispatcherControlAction::Resume,
    );
    let receipt = apply(&first, original.clone()).await.receipt;
    assert!(!first.snapshot().unwrap().paused);
    assert!(
        first
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    drop(first);
    let effect = fixture
        .seed(10, "tenant-a", "publication", profile("test.v1"))
        .await;
    let pending = fixture.record(&effect).await.encode().unwrap();
    let (adapter, _events) = Adapter::new("test.v1", None);
    let owner = suppressed(
        &fixture,
        config(),
        vec![adapter.clone()],
        Some((receipt.generation().owner_epoch(), 100)),
    )
    .await;
    let generation = owner.snapshot().unwrap().control.generation;
    owner.finish_startup_paused().unwrap();
    assert!(owner.snapshot().unwrap().paused);
    assert_eq!(owner.snapshot().unwrap().control.generation, generation);
    assert_eq!(fixture.record(&effect).await.encode().unwrap(), pending);
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 0);
    assert_eq!(
        owner
            .lookup_control(original)
            .unwrap()
            .await
            .unwrap()
            .unwrap(),
        Some(receipt)
    );
    let resumed = apply(
        &owner,
        request(
            &owner,
            "current-non-http-resume",
            DispatcherControlAction::Resume,
        ),
    )
    .await;
    assert!(resumed.published && !resumed.paused);
    wait_disposition(&fixture, &effect, Disposition::ProviderAcknowledged).await;
    assert_eq!(adapter.sent.load(Ordering::SeqCst), 1);
    stop(&fixture, owner).await;
}
