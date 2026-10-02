//! Real engine receipts; operator-authentication and protected-node wiring are
//! separately exercised by management and Linux dispatcher integration tests.
use super::*;
use std::fs::OpenOptions;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

use crate::dispatch_store::DispatchCatalog;
use latent_state::embedded::{EmbeddedStore, StoreLimits};

struct Clock {
    millis: AtomicU64,
    continuous: AtomicBool,
}
impl EffectTimeSource for Clock {
    fn observe(&self) -> EffectTime {
        EffectTime {
            unix_millis: self.millis.load(Ordering::SeqCst),
            continuity_proven: self.continuous.load(Ordering::SeqCst),
        }
    }
}
struct Fixture {
    _root: tempfile::TempDir,
    store: EmbeddedStore,
    shared: Arc<Shared>,
    time: Arc<Clock>,
}
impl Fixture {
    fn new(paused: bool, review: bool) -> Self {
        let root = tempfile::tempdir().unwrap();
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(root.path().join("control.redb"))
            .unwrap();
        let store = EmbeddedStore::open_file(file, StoreLimits::default()).unwrap();
        let time = Arc::new(Clock {
            millis: AtomicU64::new(100),
            continuous: AtomicBool::new(true),
        });
        let epoch = DispatchCatalog::begin_exclusive_epoch(&store, time.observe(), None).unwrap();
        Self {
            _root: root,
            store,
            shared: Arc::new(Shared::new(paused, epoch, review)),
            time,
        }
    }
    fn request(
        &self,
        operation: &str,
        action: DispatcherControlAction,
    ) -> DispatcherControlRequest {
        DispatcherControlRequest::new(
            "operator-tenant".into(),
            "operator-a".into(),
            operation.into(),
            self.shared.state.lock().unwrap().control_generation,
            action,
        )
        .unwrap()
    }
    fn prepare(&self, request: DispatcherControlRequest) -> PreparedDispatcherControl {
        let state = self.shared.state.lock().unwrap();
        check_request(&state, &request, self.time.observe()).unwrap();
        PreparedDispatcherControl {
            shared: Arc::clone(&self.shared),
            time: self.time.clone(),
            request,
            restore_review: state.restore_review.is_required(),
        }
    }
    fn apply(&self, request: DispatcherControlRequest) -> DispatcherControlOutcome {
        execute(&self.store, &self.prepare(request), |accept| accept()).unwrap()
    }
}

#[test]
fn pause_has_one_attributed_durable_receipt_and_preserves_original_precondition() {
    let fixture = Fixture::new(false, false);
    let request = fixture.request("pause-original", DispatcherControlAction::Pause);
    let outcome = fixture.apply(request.clone());
    assert!(!outcome.replayed);
    assert!(outcome.published && outcome.paused);
    assert_eq!(outcome.receipt.request(), &request);
    assert_eq!(
        outcome.receipt.generation().revision(),
        request.expected().revision() + 1
    );
    assert_eq!(
        ControlCatalog::lookup(&fixture.store.snapshot().unwrap(), &request).unwrap(),
        Some(outcome.receipt)
    );
    DispatchCatalog::validate_view(&fixture.store.snapshot().unwrap()).unwrap();
}

#[test]
fn resume_stays_paused_through_the_final_fence_until_actual_engine_durability() {
    let fixture = Fixture::new(true, false);
    let request = fixture.request("resume-original", DispatcherControlAction::Resume);
    let prepared = fixture.prepare(request);
    let outcome = execute(&fixture.store, &prepared, |accept| {
        accept()?;
        let state = fixture.shared.state.lock().unwrap();
        assert!(state.paused && state.pending_control.is_some());
        Ok(())
    })
    .unwrap();
    assert!(outcome.published && !outcome.paused);
    assert!(fixture
        .shared
        .state
        .lock()
        .unwrap()
        .pending_control
        .is_none());
}

#[test]
fn lost_response_lookup_and_historical_replay_do_not_reapply_resume() {
    let fixture = Fixture::new(true, false);
    let request = fixture.request("resume-lost", DispatcherControlAction::Resume);
    let old_preparation = fixture.prepare(request.clone());
    drop(fixture.apply(request.clone()));
    // A later trusted safety pause must survive receipt replay.
    fixture.shared.state.lock().unwrap().paused = true;
    let replay = execute(&fixture.store, &old_preparation, |check| check()).unwrap();
    assert!(replay.replayed && replay.paused && !replay.published);
    assert_eq!(replay.receipt.request(), &request);
    assert!(
        ControlCatalog::lookup(&fixture.store.snapshot().unwrap(), &request)
            .unwrap()
            .is_some()
    );
}

#[test]
fn original_operation_identity_cannot_change_action_precondition_or_actor() {
    let fixture = Fixture::new(false, false);
    let request = fixture.request("same-original-id", DispatcherControlAction::Pause);
    fixture.apply(request.clone());
    let view = fixture.store.snapshot().unwrap();
    let changed = DispatcherControlRequest::new(
        request.actor_tenant().into(),
        request.actor_subject().into(),
        request.operation_id().into(),
        request.expected(),
        DispatcherControlAction::Resume,
    )
    .unwrap();
    assert_eq!(
        ControlCatalog::lookup(&view, &changed),
        Err(StoreError::Conflict)
    );
    let changed = DispatcherControlRequest::new(
        request.actor_tenant().into(),
        request.actor_subject().into(),
        request.operation_id().into(),
        request.expected().next().unwrap(),
        request.action(),
    )
    .unwrap();
    assert_eq!(
        ControlCatalog::lookup(&view, &changed),
        Err(StoreError::Conflict)
    );
    let other = DispatcherControlRequest::new(
        request.actor_tenant().into(),
        "operator-b".into(),
        request.operation_id().into(),
        request.expected(),
        request.action(),
    )
    .unwrap();
    assert_eq!(ControlCatalog::lookup(&view, &other), Ok(None));
}

#[test]
fn concurrent_stale_control_does_not_advance_generation_or_rewrite_receipt() {
    let fixture = Fixture::new(false, false);
    let first = fixture.request("first-pause", DispatcherControlAction::Pause);
    let second = fixture.request("second-resume", DispatcherControlAction::Resume);
    let stale = fixture.prepare(second.clone());
    let first = fixture.apply(first);
    assert!(matches!(
        execute(&fixture.store, &stale, |accept| accept()),
        Err(DispatcherControlError::Conflict)
    ));
    assert_eq!(
        fixture.shared.state.lock().unwrap().control_generation,
        first.receipt.generation()
    );
    assert_eq!(
        ControlCatalog::lookup(&fixture.store.snapshot().unwrap(), &second),
        Ok(None)
    );
}

#[test]
fn denied_or_missing_authorization_callback_prevents_receipt_and_acceptance() {
    let fixture = Fixture::new(false, false);
    let request = fixture.request("denied-control", DispatcherControlAction::Pause);
    let prepared = fixture.prepare(request.clone());
    assert!(matches!(
        execute(&fixture.store, &prepared, |_| Err(
            DispatcherControlError::InvalidAuthorizationFence
        )),
        Err(DispatcherControlError::InvalidAuthorizationFence)
    ));
    let prepared = fixture.prepare(request.clone());
    assert!(matches!(
        execute(&fixture.store, &prepared, |_| Ok(())),
        Err(DispatcherControlError::InvalidAuthorizationFence)
    ));
    let state = fixture.shared.state.lock().unwrap();
    assert_eq!(state.control_generation, request.expected());
    assert!(!state.paused && state.pending_control.is_none());
    drop(state);
    assert_eq!(
        ControlCatalog::lookup(&fixture.store.snapshot().unwrap(), &request),
        Ok(None)
    );
}

#[test]
fn malformed_double_acceptance_leaves_conservative_pending_pause_without_a_receipt() {
    let fixture = Fixture::new(false, false);
    let request = fixture.request("bad-double-fence", DispatcherControlAction::Pause);
    let prepared = fixture.prepare(request.clone());
    assert!(matches!(
        execute(&fixture.store, &prepared, |accept| {
            accept()?;
            accept()
        }),
        Err(DispatcherControlError::InvalidAuthorizationFence)
    ));
    let state = fixture.shared.state.lock().unwrap();
    assert!(state.paused && state.pending_control.is_some());
    assert_ne!(state.control_generation, request.expected());
    drop(state);
    assert_eq!(
        ControlCatalog::lookup(&fixture.store.snapshot().unwrap(), &request),
        Ok(None)
    );
}

#[test]
fn discontinuous_clock_still_allows_pause_but_never_authorizes_resume() {
    let fixture = Fixture::new(false, false);
    fixture.time.continuous.store(false, Ordering::SeqCst);
    fixture.time.millis.store(1, Ordering::SeqCst);
    let outcome =
        fixture.apply(fixture.request("clock-safe-pause", DispatcherControlAction::Pause));
    assert!(outcome.paused && !outcome.receipt.clock_continuity_proven());
    let resume = fixture.request("clock-denied-resume", DispatcherControlAction::Resume);
    assert_eq!(
        check_request(
            &fixture.shared.state.lock().unwrap(),
            &resume,
            fixture.time.observe()
        ),
        Err(DispatcherControlError::ClockDiscontinuity)
    );
}

#[test]
fn persisted_pause_survives_new_exclusive_owner_epoch_and_restore_review_is_sticky() {
    let fixture = Fixture::new(false, true);
    let request = fixture.request("review-pause", DispatcherControlAction::Pause);
    fixture.apply(request);
    let epoch = DispatchCatalog::begin_exclusive_epoch(
        &fixture.store,
        fixture.time.observe(),
        Some((1, 100)),
    )
    .unwrap();
    let restored = ControlCatalog::startup(&fixture.store.snapshot().unwrap(), epoch.generation())
        .unwrap()
        .unwrap();
    assert_eq!(restored, (true, true));
    let shared = Shared::new(restored.0, epoch, restored.1);
    let state = shared.state.lock().unwrap();
    let request = DispatcherControlRequest::new(
        "operator-tenant".into(),
        "operator-a".into(),
        "generic-resume".into(),
        state.control_generation,
        DispatcherControlAction::Resume,
    )
    .unwrap();
    assert_eq!(
        check_request(&state, &request, fixture.time.observe()),
        Err(DispatcherControlError::RestoreReviewRequired)
    );
}

#[test]
fn request_bounds_and_generation_exhaustion_reject_before_staging() {
    assert!(DispatcherControlGeneration::new(0, 1).is_err());
    assert!(DispatcherControlGeneration::new(1, 0).is_err());
    assert!(DispatcherControlRequest::new(
        "tenant".into(),
        "subject".into(),
        "op".into(),
        DispatcherControlGeneration::new(1, u64::MAX).unwrap(),
        DispatcherControlAction::Pause
    )
    .is_err());
    assert!(DispatcherControlRequest::new(
        "tenant".into(),
        "subject".into(),
        "a".repeat(257),
        DispatcherControlGeneration::new(1, 1).unwrap(),
        DispatcherControlAction::Pause
    )
    .is_err());
    let mut sparse = String::with_capacity(1025);
    sparse.push_str("op");
    assert!(DispatcherControlRequest::new(
        "tenant".into(),
        "subject".into(),
        sparse,
        DispatcherControlGeneration::new(1, 1).unwrap(),
        DispatcherControlAction::Pause
    )
    .is_err());
}
