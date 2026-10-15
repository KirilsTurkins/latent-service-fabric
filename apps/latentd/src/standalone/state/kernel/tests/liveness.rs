use super::*;
use latent_core::{ErrorDetail, PlatformErrorCode};
use latent_effects::runtime::{CommandAdmissionSource, DispatcherError};

mod clock;
mod failures;

use clock::{ControlledClock, Schedule};

struct Owned {
    kernel: StateKernel,
    effects: EffectRuntime,
    clock: Arc<ControlledClock>,
    authority: Arc<SupplyChainAuthority>,
    deadline: Instant,
    _root: tempfile::TempDir,
}

impl Owned {
    async fn start() -> Self {
        let root = tempfile::tempdir().unwrap();
        let mut settings = crate::standalone::state::bootstrap::tests::settings(root.path());
        settings.startup_timeout = Duration::from_secs(20);
        for path in [&settings.store.root, &settings.checkpoint_root] {
            std::fs::create_dir(path).unwrap();
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        let clock = ControlledClock::new();
        let authority = Arc::new(
            SupplyChainAuthority::open(
                &root.path().join("actual-liveness-authority"),
                policy(),
                clock.clone(),
                5,
            )
            .unwrap(),
        );
        let original: Arc<dyn ActivationClock> = clock.clone();
        let bootstrap = StateBootstrap::new_state(&settings, &original).unwrap();
        let deadline = bootstrap.deadline;
        let (kernel, effects) = StateKernel::start(
            bootstrap,
            &settings,
            Arc::clone(&authority),
            Vec::new(),
            &AdapterClock::default(),
            tokio::runtime::Handle::current(),
        )
        .await
        .unwrap();
        assert_eq!(kernel.original_deadline().unwrap(), deadline);
        Self {
            kernel,
            effects,
            clock,
            authority,
            deadline,
            _root: root,
        }
    }

    fn interleave<T>(&self, ordinal: usize, observe: impl FnOnce() -> T) -> (T, Schedule) {
        self.clock
            .interleave(&self.authority, ordinal, self.deadline, observe)
    }

    async fn retire(mut self) -> bool {
        let report = self.effects.shutdown(self.deadline).await.unwrap();
        let effects_retired = report.physically_retired
            && report.scheduling_owner_retired
            && report.worker_threads_remaining == 0;
        drop(self.effects);
        let report = self.kernel.shutdown(self.deadline).await.unwrap();
        effects_retired
            && report.store.snapshot.physically_retired()
            && report.native.snapshot.physically_retired()
            && report.namespace_owners == 0
    }
}

fn exact_busy(error: &PlatformError) -> bool {
    error.code == PlatformErrorCode::Unavailable
        && error.retryable
        && error.message == "admission-authority-busy"
        && error.details
            == [ErrorDetail {
                kind: "admission.currentness".into(),
                fields: [("reason".into(), "admission-authority-busy".into())].into(),
            }]
}

#[tokio::test]
async fn actual_first_clock_busy_keeps_kernel_live_without_granting_a_clock_sample() {
    let owned = Owned::start().await;
    let (proof, proof_schedule) = owned.interleave(1, || owned.kernel.clock.sample());
    let (running, schedule) = owned.interleave(1, || owned.kernel.is_running(&owned.effects));
    let recovered = owned.kernel.clock.sample().is_ok();
    let retired = owned.retire().await;
    assert!(
        retired,
        "original owners must physically retire before the result"
    );
    assert!(proof_schedule.completed && proof_schedule.triggered && proof_schedule.owner_advanced);
    assert!(proof.as_ref().is_err_and(|error| exact_busy(error)));
    assert!(schedule.completed && schedule.triggered && schedule.owner_advanced);
    assert_eq!(schedule.calls, 1);
    assert!(
        recovered,
        "transient busy must not poison the admitted clock"
    );
    assert!(
        running,
        "one genuine bounded busy observation is not server death"
    );
}

#[tokio::test]
async fn actual_old_second_clock_busy_is_removed_without_a_second_time_observation() {
    let owned = Owned::start().await;
    let (proof, proof_schedule) = owned.interleave(1, || owned.kernel.clock.sample());
    let (running, schedule) = owned.interleave(2, || owned.kernel.is_running(&owned.effects));
    let retired = owned.retire().await;
    assert!(
        retired,
        "original owners must physically retire before the result"
    );
    assert!(proof_schedule.completed && proof_schedule.triggered && proof_schedule.owner_advanced);
    assert!(proof.as_ref().is_err_and(|error| exact_busy(error)));
    assert!(schedule.completed);
    if schedule.triggered {
        assert!(
            schedule.owner_advanced,
            "the old second probe must meet the real original owner"
        );
    }
    assert!(
        running,
        "the old second probe must not convert transient busy to death"
    );
    assert!(
        !schedule.triggered,
        "liveness must have only one time observation"
    );
    assert_eq!(schedule.calls, 1);
}

#[tokio::test]
async fn actual_busy_command_admission_and_writer_fence_still_deny_without_entry() {
    use std::sync::atomic::{AtomicUsize, Ordering};

    let owned = Owned::start().await;
    let source: CommandAdmissionSource = owned.effects.command_admission_source();
    let original = source.capture().unwrap();
    let entered = AtomicUsize::new(0);
    let before = owned.effects.snapshot().unwrap().command_owners;
    let native_before = owned.kernel.native.snapshot().unwrap().ordinary.slots;
    let (captured, capture_schedule) = owned.interleave(1, || source.capture());
    let (accepted, current_schedule) = owned.interleave(1, || {
        original.with_current(|_, _| entered.fetch_add(1, Ordering::SeqCst))
    });
    let after = owned.effects.snapshot().unwrap().command_owners;
    let native_after = owned.kernel.native.snapshot().unwrap().ordinary.slots;
    let captured_denied = matches!(
        captured,
        Err(DispatcherError::Authority(
            latent_effects::authority::AuthorityError::ClockDiscontinuity
        ))
    );
    let current_denied = matches!(
        accepted,
        Err(DispatcherError::Authority(
            latent_effects::authority::AuthorityError::ClockDiscontinuity
        ))
    );
    original.retire();
    drop(source);
    let retired = owned.retire().await;
    assert!(retired);
    assert!(
        capture_schedule.completed && capture_schedule.triggered && capture_schedule.owner_advanced
    );
    assert!(
        current_schedule.completed && current_schedule.triggered && current_schedule.owner_advanced
    );
    assert!(captured_denied && current_denied);
    assert_eq!(entered.load(Ordering::SeqCst), 0);
    assert_eq!(after, before);
    assert_eq!(native_after, native_before);
}
