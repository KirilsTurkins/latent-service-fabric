use super::*;
use latent_core::{
    ActivationClock, ActivationPhase, ActivationTerminalState, BudgetConsumption, ClockSample,
};
use latent_telemetry::phase2_canary::{
    BoundedPhase2CanaryOutcomeWindow, CanaryWindow, Phase2CanaryOutcomeWindowConfig,
    SealedCanaryWindow, SelectedOutcomeRevision,
};
use latent_telemetry::{
    ActivationObservationToken, ActivationOutcomeClass, ActivationTerminalObservation,
};
use sha2::{Digest, Sha256};
use std::{
    sync::atomic::AtomicU64,
    time::{Duration, Instant},
};

struct Clock {
    base: Instant,
    millis: AtomicU64,
}
impl Clock {
    fn new() -> Self {
        Self {
            base: Instant::now(),
            millis: AtomicU64::new(0),
        }
    }
}
impl ActivationClock for Clock {
    fn sample(&self) -> ClockSample {
        ClockSample::new(1, self.monotonic_now())
    }
    fn monotonic_now(&self) -> Instant {
        self.base + Duration::from_millis(self.millis.load(Ordering::Acquire))
    }
}
fn policy() -> RolloutCanaryPolicy {
    RolloutCanaryPolicy {
        format_version: 1,
        observation_millis: 100,
        minimum_candidate_samples: 1,
        maximum_failure_basis_points: 0,
        latency_threshold_micros: 1000,
        maximum_slow_basis_points: 0,
    }
}
fn hub(clock: &Arc<Clock>) -> BoundedPhase2CanaryOutcomeWindow {
    BoundedPhase2CanaryOutcomeWindow::with_clock(
        Phase2CanaryOutcomeWindowConfig::default(),
        clock.clone(),
    )
    .unwrap()
}
fn start(store: &Store, releases: &Releases) {
    let mut request = setup(store, releases);
    if let RolloutRequest::Start { spec, .. } = &mut request {
        spec.canary_policy = Some(policy());
    }
    execute(store, request);
}
fn window(store: &Store, hub: &BoundedPhase2CanaryOutcomeWindow) -> CanaryWindow {
    let cohort = store.rollout_canary_cohort(&alice(), &id(), 1).unwrap();
    hub.register(cohort.window_spec()).unwrap()
}
fn record(store: &Store, hub: &BoundedPhase2CanaryOutcomeWindow, success: bool) {
    let cohort = store.rollout_canary_cohort(&alice(), &id(), 1).unwrap();
    let spec = cohort.window_spec();
    let mut sample = hub
        .capture_handle()
        .try_begin(
            ActivationObservationToken {
                manager: 1,
                sequence: 1,
            },
            &spec.identity.tenant,
            &spec.identity.service,
        )
        .into_sample()
        .unwrap();
    sample.bind_selected(SelectedOutcomeRevision {
        tenant: &spec.identity.tenant,
        service: &spec.identity.service,
        revision: cohort.candidate_revision(),
        component: &spec.revisions[1].component,
        generation: spec.identity.generation,
    });
    sample.admitted();
    sample.finish(
        &ActivationTerminalObservation {
            class: if success {
                ActivationOutcomeClass::GuestSuccess
            } else {
                ActivationOutcomeClass::GuestDomainError
            },
            terminal_state: ActivationTerminalState::Completed,
            platform_code: None,
            consumption: BudgetConsumption::default(),
            last_phase: ActivationPhase::Running,
            sequence: 1,
        },
        Duration::from_micros(500),
    );
}
fn promote(
    store: &Store,
    proof: Option<SealedCanaryWindow>,
) -> std::result::Result<PreparedRolloutMutation, latent_core::PlatformError> {
    run(store.prepare_canary_promotion(
        change("promote", 1, RolloutCommand::Promote { next_step: 1 }),
        proof,
    ))
}

#[test]
fn healthy_promotion_is_exact_replayable_and_preserves_old_pin() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let clock = Arc::new(Clock::new());
    let hub = hub(&clock);
    let store = open(&root, &releases).with_canary(hub.clone()).unwrap();
    start(&store, &releases);
    let pin = store.pin().unwrap();
    let selected = pin.resolve(&target("alice", None), Some("pin")).unwrap();
    let window = window(&store, &hub);
    record(&store, &hub, true);
    clock.millis.store(100, Ordering::Release);
    let prepared = promote(&store, Some(window.try_seal().unwrap())).unwrap();
    let decision = prepared.preview().canary_decision.as_ref().unwrap();
    assert_eq!(decision.candidate.success, 1);
    assert!(prepared.preview().canonical_bytes().unwrap().len() <= MAX_RECEIPT_BYTES);
    let result = store.commit_rollout(prepared).unwrap();
    result.durability.unwrap();
    assert_eq!(result.receipt.action, RolloutAction::Promote);
    assert_eq!(
        pin.resolve(&target("alice", None), Some("pin")).unwrap(),
        selected
    );
    assert!(
        store
            .get_rollout(&alice(), &id())
            .unwrap()
            .unwrap()
            .route_generation
            > selected.route_generation
    );
    let replay = store
        .commit_rollout(promote(&store, None).unwrap())
        .unwrap();
    assert!(replay.replayed);
    assert_eq!(replay.receipt, result.receipt);
    drop(store);
    let reopened = open(&root, &releases);
    let replay = reopened
        .commit_rollout(promote(&reopened, None).unwrap())
        .unwrap();
    assert_eq!(replay.receipt, result.receipt);
}

#[test]
fn manual_advance_and_missing_failed_empty_or_foreign_proof_cannot_move_policy_row() {
    for scenario in 0..4 {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let clock = Arc::new(Clock::new());
        let trusted = hub(&clock);
        let store = open(&root, &releases).with_canary(trusted.clone()).unwrap();
        start(&store, &releases);
        let before = std::fs::read(root.0.join("catalog.json")).unwrap();
        assert!(run(store.prepare_rollout(change(
            "manual",
            1,
            RolloutCommand::Advance { next_step: 1 }
        )))
        .is_err());
        let observed = if scenario == 3 {
            hub(&clock)
        } else {
            trusted.clone()
        };
        let window = window(&store, &observed);
        if scenario == 1 || scenario == 3 {
            record(&store, &observed, scenario == 3);
        }
        clock.millis.store(100, Ordering::Release);
        let proof = if scenario == 0 {
            None
        } else {
            Some(window.try_seal().unwrap())
        };
        assert!(promote(&store, proof).is_err());
        assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
        assert_eq!(
            store
                .get_rollout(&alice(), &id())
                .unwrap()
                .unwrap()
                .revision,
            1
        );
    }
}

#[test]
fn pause_restart_and_unrelated_route_generation_invalidate_old_window() {
    for scenario in 0..3 {
        let root = TempRoot::new();
        let releases = Arc::new(Releases::default());
        let clock = Arc::new(Clock::new());
        let hub = hub(&clock);
        let mut store = open(&root, &releases).with_canary(hub.clone()).unwrap();
        start(&store, &releases);
        let window = window(&store, &hub);
        record(&store, &hub, true);
        clock.millis.store(100, Ordering::Release);
        let proof = window.try_seal().unwrap();
        if scenario == 0 {
            execute(&store, change("pause", 1, RolloutCommand::Pause));
        } else if scenario == 1 {
            drop(store);
            store = open(&root, &releases).with_canary(hub.clone()).unwrap();
        } else {
            let release = releases.add("other");
            run(store.apply(deployment("unrelated", "bob", &release))).unwrap();
        }
        let before = std::fs::read(root.0.join("catalog.json")).unwrap();
        assert!(promote(&store, Some(proof)).is_err());
        assert_eq!(std::fs::read(root.0.join("catalog.json")).unwrap(), before);
    }
}

#[test]
fn prepared_promotion_loses_final_cas_after_ordinary_write() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let clock = Arc::new(Clock::new());
    let hub = hub(&clock);
    let store = open(&root, &releases).with_canary(hub.clone()).unwrap();
    start(&store, &releases);
    let window = window(&store, &hub);
    record(&store, &hub, true);
    clock.millis.store(100, Ordering::Release);
    let prepared = promote(&store, Some(window.try_seal().unwrap())).unwrap();
    // Ordinary deployment writers share the transaction CAS but not the rollout preparation slot.
    let release = releases.add("other");
    run(store.apply(deployment("unrelated", "bob", &release))).unwrap();
    assert!(store.commit_rollout(prepared).is_err());
    assert_eq!(
        store
            .get_rollout(&alice(), &id())
            .unwrap()
            .unwrap()
            .revision,
        1
    );
}

#[test]
fn policy_is_optional_closed_and_plan_bound_on_recovery() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let mut request = setup(&store, &releases);
    let manual = request.request_digest(RolloutLimits::default()).unwrap();
    if let RolloutRequest::Start { spec, .. } = &mut request {
        spec.canary_policy = Some(policy());
    }
    assert_ne!(
        manual,
        request.request_digest(RolloutLimits::default()).unwrap()
    );
    assert!(run(store.prepare_rollout(request.clone())).is_err());
    let raw = json::to_value(policy()).unwrap();
    let mut bad = raw.clone();
    bad["extra"] = json::json!(1);
    assert!(json::from_value::<RolloutCanaryPolicy>(bad).is_err());
    let mut zero = policy();
    zero.minimum_candidate_samples = 0;
    assert!(zero.validate().is_err());
    let clock = Arc::new(Clock::new());
    let store = store.with_canary(hub(&clock)).unwrap();
    execute(&store, request);
    let mut status = json::to_value(store.get_rollout(&alice(), &id()).unwrap().unwrap()).unwrap();
    status["canaryPolicy"] = json::Value::Null;
    assert!(json::from_value::<RolloutStatus>(status).is_err());
    drop(store);
    let path = root.0.join("catalog.json");
    let mut persisted: super::super::super::persistence::Record =
        json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    persisted.payload.control.as_mut().unwrap().rollouts.rows[0]
        .status
        .canary_policy
        .as_mut()
        .unwrap()
        .observation_millis = 101;
    persisted.checksum = format!(
        "sha256:{:x}",
        Sha256::digest(json::to_vec(&persisted.payload).unwrap())
    );
    std::fs::write(path, json::to_vec(&persisted).unwrap()).unwrap();
    assert_code(
        run(Store::open(&root.0, releases, Limits::default())),
        Code::CorruptArtifact,
    );
}

#[test]
fn manual_records_omit_new_fields_and_optional_null_decision_is_rejected() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let store = open(&root, &releases);
    let request = setup(&store, &releases);
    let result = execute(&store, request);
    let status = json::to_value(store.get_rollout(&alice(), &id()).unwrap().unwrap()).unwrap();
    assert!(status.get("canaryPolicy").is_none());
    let mut receipt = json::to_value(result.receipt).unwrap();
    assert!(receipt.get("canaryDecision").is_none());
    receipt["canaryDecision"] = json::Value::Null;
    assert!(json::from_value::<RolloutOperationReceipt>(receipt).is_err());
}

#[test]
fn pause_resume_without_hub_preserves_policy_and_never_accepts_an_old_window() {
    let root = TempRoot::new();
    let releases = Arc::new(Releases::default());
    let clock = Arc::new(Clock::new());
    let hub = hub(&clock);
    let store = open(&root, &releases).with_canary(hub.clone()).unwrap();
    start(&store, &releases);
    let before = store.get_rollout(&alice(), &id()).unwrap().unwrap();
    execute(&store, change("pause", 1, RolloutCommand::Pause));
    drop(store);
    let store = open(&root, &releases);
    let resumed = execute(&store, change("resume", 2, RolloutCommand::Resume));
    let status = store.get_rollout(&alice(), &id()).unwrap().unwrap();
    assert_eq!(status.canary_policy, before.canary_policy);
    assert_eq!(status.current_step, before.current_step);
    assert!(resumed.receipt.route_generation > before.route_generation);
    assert!(run(store.prepare_canary_promotion(
        change("missing", 3, RolloutCommand::Promote { next_step: 1 }),
        None
    ))
    .is_err());
    execute(&store, change("abort", 3, RolloutCommand::Abort));
}
