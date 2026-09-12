use super::super::*;
use latent_control_store::rollouts::{
    RolloutCanaryPolicy, RolloutCommand, RolloutId, RolloutRequest,
};
use latent_core::{
    ActivationClock, ActivationPhase, ActivationTerminalState, BudgetConsumption, ClockSample,
    TenantId,
};
use latent_telemetry::{
    ActivationObservationToken, ActivationOutcomeClass, ActivationTerminalObservation,
    BoundedPhase2CanaryOutcomeWindow, CanarySample, Phase2CanaryOutcomeWindowConfig,
    SelectedOutcomeRevision,
};
use std::sync::atomic::{AtomicU64, Ordering};

pub(super) struct Clock {
    base: Instant,
    millis: AtomicU64,
}
impl Clock {
    pub(super) fn new() -> Self {
        Self {
            base: Instant::now(),
            millis: AtomicU64::new(0),
        }
    }
    pub(super) fn set_millis(&self, value: u64) {
        self.millis.store(value, Ordering::Release);
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
pub(super) async fn fixture(clock: Arc<Clock>, maximum_series: usize) -> Fixture {
    let root = tempfile::tempdir().unwrap();
    let repository = super::super::support::repository(&root.path().join("catalog")).await;
    let Ok(repository) = Arc::try_unwrap(repository) else {
        panic!("exclusive fixture catalog");
    };
    let hub = BoundedPhase2CanaryOutcomeWindow::with_clock(
        Phase2CanaryOutcomeWindowConfig {
            maximum_series,
            ..Phase2CanaryOutcomeWindowConfig::default()
        },
        clock,
    )
    .unwrap();
    let repository = Arc::new(repository.with_canary(hub).unwrap());
    let (audit, audit_worker) =
        DirectoryPhase2AuditJournal::open(root.path().join("audit"), AuditLimits::default())
            .unwrap();
    let (handle, mut worker) = RolloutCoordinator::start(
        repository.clone(),
        audit.clone(),
        CoordinatorLimits::default(),
        &tokio::runtime::Handle::current(),
    )
    .unwrap();
    worker.wait_started(expires()).await.unwrap();
    Fixture {
        worker,
        handle,
        audit_worker,
        audit,
        repository,
        root,
    }
}
pub(super) fn start() -> RolloutRequest {
    let mut request = super::super::support::start();
    let RolloutRequest::Start { spec, .. } = &mut request else {
        unreachable!()
    };
    spec.canary_policy = Some(RolloutCanaryPolicy {
        format_version: 1,
        observation_millis: 10,
        minimum_candidate_samples: 2,
        maximum_failure_basis_points: 0,
        latency_threshold_micros: 100,
        maximum_slow_basis_points: 0,
    });
    request
}
pub(super) fn change(operation: &str, revision: u64, command: RolloutCommand) -> RolloutRequest {
    RolloutRequest::Change {
        context: super::super::support::context(operation, revision),
        id: RolloutId("rollout".into()),
        command,
    }
}
pub(super) fn evaluation(revision: u64) -> CanaryEvaluationRequest {
    CanaryEvaluationRequest {
        tenant: TenantId("alice".into()),
        actor: super::super::support::context("evaluate", revision).actor,
        id: RolloutId("rollout".into()),
        expected_revision: revision,
    }
}
pub(super) fn sample(fixture: &Fixture, sequence: u64) -> CanarySample {
    let cohort = fixture
        .repository
        .rollout_canary_cohort(&TenantId("alice".into()), &RolloutId("rollout".into()), 1)
        .unwrap();
    let spec = cohort.window_spec();
    let mut sample = fixture
        .handle
        .canary_capture()
        .unwrap()
        .try_begin(
            ActivationObservationToken {
                manager: 1,
                sequence,
            },
            &spec.identity.tenant,
            &spec.identity.service,
        )
        .into_sample()
        .unwrap();
    let candidate = &spec.revisions[1];
    sample.bind_selected(SelectedOutcomeRevision {
        tenant: &spec.identity.tenant,
        service: &spec.identity.service,
        revision: &candidate.revision,
        component: &candidate.component,
        generation: spec.identity.generation,
    });
    sample.admitted();
    sample
}
pub(super) fn successes(fixture: &Fixture, count: u64) {
    for sequence in 1..=count {
        sample(fixture, sequence).finish(
            &ActivationTerminalObservation {
                class: ActivationOutcomeClass::GuestSuccess,
                terminal_state: ActivationTerminalState::Completed,
                platform_code: None,
                consumption: BudgetConsumption::default(),
                last_phase: ActivationPhase::Running,
                sequence,
            },
            Duration::from_micros(100),
        );
    }
}

pub(super) async fn summaries(fixture: &Fixture) -> Vec<latent_audit::AuditCanaryDecision> {
    let page = fixture
        .audit
        .query(
            latent_audit::AuditQueryRequest {
                scope: latent_audit::AuditScope::Tenant(TenantId("alice".into())),
                filter: latent_audit::AuditFilter::default(),
                cursor: None,
                limit: 32,
                maximum_bytes: 32768,
            },
            expires(),
        )
        .unwrap()
        .wait()
        .await
        .unwrap();
    page.records()
        .iter()
        .filter_map(|record| match &record.data {
            latent_audit::AuditRecordData::Outcome { conclusion, .. } => conclusion.canary_decision,
            _ => None,
        })
        .collect()
}

pub(super) async fn assert_healthy_audit(fixture: &Fixture) {
    let summaries = summaries(fixture).await;
    let summary = summaries
        .iter()
        .find(|value| value.verdict == latent_audit::AuditCanaryVerdict::Healthy)
        .unwrap();
    assert_eq!(
        (
            summary.selected,
            summary.successes,
            summary.failures,
            summary.maximum_failure_basis_points
        ),
        (2, 2, 0, 0)
    );
}
