//! Physical adoption schedules with controlled current authority owners.
//! These exercise real ext4 startup/custody, not authenticated RPC or a provider.
use super::*;
use crate::protected_store::{
    RestoreAdoptionFence, RestoreAdoptionOwners, RestoreAdoptionPlan, RestoreAdoptionRequest,
    RestoreStageReceipt,
};
use fixture::StageOwners;
use sha2::{Digest, Sha256};
use std::sync::atomic::AtomicBool;

struct AdoptionOwners {
    stage: Arc<StageOwners>,
    revoked: AtomicBool,
    ignored_fence: AtomicBool,
}

impl RestoreAdoptionOwners for AdoptionOwners {
    fn review(
        &self,
        view: &crate::embedded::ReadView,
        stage: &RestoreStageReceipt,
        _: &RestoreAdoptionRequest,
    ) -> Result<(), StoreError> {
        self.stage
            .review_reopened(view, stage.input(), stage.request())
    }
    fn current_role(&self) -> Result<(), StoreError> {
        if self.revoked.load(Ordering::SeqCst) {
            return Err(StoreError::Unavailable);
        }
        self.stage.current_role()
    }
    fn current_audit(&self) -> Result<(), StoreError> {
        self.stage.current_audit()
    }
    fn current_publication(&self) -> Result<(), StoreError> {
        self.stage.current_controls()
    }
    fn current_clock(&self) -> Result<(), StoreError> {
        self.stage.current_clock()
    }
    fn accept(&self, fence: RestoreAdoptionFence<'_>) -> Result<(), StoreError> {
        if self.ignored_fence.load(Ordering::SeqCst) {
            return Ok(());
        }
        fence.accept()
    }
}

struct Staged {
    setup: Setup,
    root: tempfile::TempDir,
    checkpoint: tempfile::TempDir,
    snapshot: ProtectedSnapshot,
    receipt: RestoreStageReceipt,
    owners: Arc<AdoptionOwners>,
}

struct Prepared {
    setup: Setup,
    root: tempfile::TempDir,
    checkpoint: tempfile::TempDir,
    snapshot: ProtectedSnapshot,
    plan: RestoreAdoptionPlan,
    owners: Arc<AdoptionOwners>,
}

fn stage(setup: Setup) -> Staged {
    let (root, _) = super::super::fixture();
    let (checkpoint, _) = super::super::fixture();
    let config = super::restore_stage::destination(root.path(), checkpoint.path(), 4 * 1024 * 1024);
    let (snapshot, input, stage_owners, request) = super::restore_stage::prepare(&setup, config);
    let job = super::restore_stage::job(&setup, snapshot, input, &stage_owners, request);
    let (snapshot, result) = wait(job).unwrap();
    Staged {
        setup,
        root,
        checkpoint,
        snapshot,
        receipt: result.unwrap().unwrap(),
        owners: Arc::new(AdoptionOwners {
            stage: stage_owners,
            revoked: AtomicBool::new(false),
            ignored_fence: AtomicBool::new(false),
        }),
    }
}

fn prepare() -> Prepared {
    let staged = stage(Setup::with_restore_adoption());
    let Staged {
        setup,
        root,
        checkpoint,
        snapshot,
        receipt,
        owners,
    } = staged;
    let request = RestoreAdoptionRequest {
        operator_id: receipt.request().operator_id.clone(),
        operation_digest: receipt.operation_digest(),
        checkpoint_digest: Sha256::digest(receipt.checkpoint().encode()).into(),
        loss_window_acknowledgement: receipt.request().loss_window_acknowledgement,
    };
    let (snapshot, result) = wait(
        setup
            .owner
            .prepare_restore_adoption(
                snapshot,
                receipt,
                request,
                Arc::clone(&owners) as Arc<dyn RestoreAdoptionOwners>,
            )
            .unwrap(),
    )
    .unwrap();
    Prepared {
        setup,
        root,
        checkpoint,
        snapshot,
        plan: result.unwrap().unwrap(),
        owners,
    }
}

fn failed_adoption(plan: RestoreAdoptionPlan) -> ProtectedStoreError {
    let mut startup = Box::pin(
        plan.start(Arc::new(latent_core::SystemActivationClock))
            .unwrap(),
    );
    let reason = wait(startup.as_mut()).err().unwrap();
    let report = wait(
        startup
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(report.snapshot.physically_retired());
    reason
}

#[test]
fn restored_root_adoption_waits_for_both_physical_owners_and_publishes_only_paused_state() {
    let Prepared {
        setup,
        root,
        checkpoint,
        snapshot,
        plan,
        owners: _,
    } = prepare();
    let operation = plan.request().operation_digest;
    let refused = plan
        .start(Arc::new(latent_core::SystemActivationClock))
        .err()
        .unwrap();
    assert_eq!(
        refused.reason,
        ProtectedStoreError::Store(StoreError::Unavailable)
    );
    let plan = refused.plan.unwrap();
    wait(snapshot.retire());
    setup
        .owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert_eq!(
        plan.check_retired(),
        Err(ProtectedStoreError::Store(StoreError::Unavailable))
    );
    assert!(finish(&setup.owner).clean);
    plan.check_retired().unwrap();
    let adopted = wait(
        plan.start(Arc::new(latent_core::SystemActivationClock))
            .unwrap(),
    )
    .unwrap();
    adopted.bind_native_capacity(&setup.native).unwrap();
    assert!(adopted.uses_native_capacity(&setup.native));
    assert!(wait(adopted.take_initialization_witness().unwrap())
        .unwrap()
        .unwrap()
        .is_none());
    wait(
        adopted
            .with_store(StoreIoKind::RecoveryRead, 64 * 1024, move |store| {
                let view = store.snapshot()?;
                let guard = crate::recovery::RecoveryGuard::capture(&view)?.unwrap();
                assert_eq!(
                    guard.status(),
                    crate::recovery::RecoveryStatus::ReconciliationRequired
                );
                assert_eq!(guard.operation_digest(), operation);
                assert!(crate::recovery::require_ready(&view).is_err());
                let rows = view.scan_after(Family::State, b"state-v1\0", None, 2, 4096)?;
                assert_eq!(rows.rows.len(), 1);
                let (key, bytes) = &rows.rows[0];
                assert_eq!(
                    crate::session::inspect_cell(&view, key, bytes)?
                        .value
                        .unwrap()
                        .bytes,
                    u64::MAX.to_le_bytes()
                );
                Ok(())
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert!(finish(&adopted).clean);
    drop((root, checkpoint));
}

#[test]
fn restored_root_adoption_ignored_original_gate_refuses_without_poisoning_current_store() {
    let Staged {
        setup,
        root,
        checkpoint,
        snapshot,
        receipt,
        owners,
    } = stage(Setup::with_restore_adoption());
    owners.ignored_fence.store(true, Ordering::SeqCst);
    let request = RestoreAdoptionRequest {
        operator_id: receipt.request().operator_id.clone(),
        operation_digest: receipt.operation_digest(),
        checkpoint_digest: Sha256::digest(receipt.checkpoint().encode()).into(),
        loss_window_acknowledgement: receipt.request().loss_window_acknowledgement,
    };
    let (snapshot, result) = wait(
        setup
            .owner
            .prepare_restore_adoption(snapshot, receipt, request, owners)
            .unwrap(),
    )
    .unwrap();
    assert!(matches!(result.unwrap(), Err(StoreError::Invalid)));
    assert_eq!(setup.owner.failure(), None);
    wait(snapshot.retire());
    setup
        .owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert_eq!(setup.observe().value, u64::MAX.to_le_bytes());
    assert!(finish(&setup.owner).clean);
    drop((root, checkpoint));
}

#[test]
fn restored_root_adoption_rechecks_revocation_after_retirement_without_replacing_original_plan() {
    let Prepared {
        setup,
        root,
        checkpoint,
        snapshot,
        plan,
        owners,
    } = prepare();
    wait(snapshot.retire());
    assert!(finish(&setup.owner).clean);
    let before = fs::read(root.path().join("transaction-state.redb")).unwrap();
    owners.revoked.store(true, Ordering::SeqCst);
    let error = plan
        .start(Arc::new(latent_core::SystemActivationClock))
        .err()
        .unwrap();
    assert_eq!(
        error.reason,
        ProtectedStoreError::Store(StoreError::Unavailable)
    );
    assert_eq!(
        fs::read(root.path().join("transaction-state.redb")).unwrap(),
        before
    );
    owners.revoked.store(false, Ordering::SeqCst);
    let adopted = wait(
        error
            .plan
            .unwrap()
            .start(Arc::new(latent_core::SystemActivationClock))
            .unwrap(),
    )
    .unwrap();
    assert!(finish(&adopted).clean);
    drop((root, checkpoint));
}

#[test]
fn restored_root_adoption_rejects_byte_identical_replacement_engine_and_checkpoint_files() {
    for replace_checkpoint in [false, true] {
        let Prepared {
            setup,
            root,
            checkpoint,
            snapshot,
            plan,
            owners: _,
        } = prepare();
        wait(snapshot.retire());
        assert!(finish(&setup.owner).clean);
        let source_before = fs::read(setup.source_path()).unwrap();
        let path = if replace_checkpoint {
            checkpoint.path().join("transaction-checkpoint.v1")
        } else {
            root.path().join("transaction-state.redb")
        };
        let held = path.with_extension("original");
        fs::rename(&path, &held).unwrap();
        fs::copy(&held, &path).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
        assert_eq!(fs::read(&path).unwrap(), fs::read(&held).unwrap());
        let refused = failed_adoption(plan);
        assert!(matches!(
            refused,
            ProtectedStoreError::UnsafeRoot | ProtectedStoreError::Store(StoreError::Conflict)
        ));
        assert_eq!(fs::read(setup.source_path()).unwrap(), source_before);
        assert_eq!(setup.owner.failure(), None);
    }
}

#[test]
fn restored_root_adoption_metadata_cannot_borrow_undeclared_original_response_capacity() {
    let Staged {
        setup,
        root,
        checkpoint,
        snapshot,
        receipt,
        owners,
    } = stage(Setup::with_restore_destination());
    let request = RestoreAdoptionRequest {
        operator_id: receipt.request().operator_id.clone(),
        operation_digest: receipt.operation_digest(),
        checkpoint_digest: Sha256::digest(receipt.checkpoint().encode()).into(),
        loss_window_acknowledgement: receipt.request().loss_window_acknowledgement,
    };
    let (snapshot, result) = wait(
        setup
            .owner
            .prepare_restore_adoption(snapshot, receipt, request, owners)
            .unwrap(),
    )
    .unwrap();
    assert!(matches!(result.unwrap(), Err(StoreError::Capacity)));
    assert_eq!(setup.owner.failure(), None);
    wait(snapshot.retire());
    setup
        .owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert_eq!(setup.observe().value, u64::MAX.to_le_bytes());
    assert!(finish(&setup.owner).clean);
    drop((root, checkpoint));
}
