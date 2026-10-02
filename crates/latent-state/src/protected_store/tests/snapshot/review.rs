//! Real same-owner snapshot refusal, file cleanup and original permit custody.
//! Controlled review/fault callbacks do not establish production RPC authority.
use super::*;
use crate::embedded::ReadView;
use latent_core::test_support::coordination::PauseTicket;
use std::sync::atomic::{AtomicBool, Ordering};

fn reviewed(
    owner: &ProtectedStoreOwner,
    target: &std::path::Path,
    original: Arc<NativeReservation>,
    metadata: SnapshotMetadata,
    review: impl FnOnce(&ReadView) -> Result<SnapshotClosure, SnapshotError> + Send + 'static,
) -> ProtectedSnapshotJob {
    owner
        .create_reviewed_snapshot(
            ProtectedSnapshotConfig {
                root: target.to_path_buf(),
                file_name: "original-backup.v2".into(),
            },
            metadata,
            original,
            review,
            |_| Ok(()), // Immutable fixture artifact; no production approval claim.
            row,
            Arc::new(|| Ok(())),
        )
        .unwrap()
}

fn pause_review(gates: &Rendezvous, notice: mpsc::Sender<PauseTicket>) {
    let (registration, mut tracked) = gates.track(()).unwrap();
    tracked.commit(Stage::Entered).unwrap();
    let mut pause = Box::pin(tracked.pause());
    PollProbe::default().pending(pause.as_mut());
    notice
        .send(gates.blocked(registration, Stage::Entered).unwrap())
        .unwrap();
    block_on(pause);
}

#[test]
fn typed_catalog_authority_deadline_and_capacity_refusal_leave_source_reusable() {
    let (_source, owner, native, original, metadata) = source();
    for refusal in [
        SnapshotError::Review(StoreError::UnsupportedFormat),
        SnapshotError::Review(StoreError::Unavailable),
        SnapshotError::Deadline,
        SnapshotError::Capacity,
    ] {
        let target = output();
        let (mut snapshot, result) = wait(reviewed(
            &owner,
            target.path(),
            Arc::clone(&original),
            metadata.clone(),
            move |_| Err(refusal),
        ))
        .unwrap();
        assert_eq!(result.unwrap(), Err(refusal));
        assert_eq!(owner.failure(), None);
        assert_eq!(
            fs::metadata(target.path().join("original-backup.v2"))
                .unwrap()
                .len(),
            0
        );
        let witness = snapshot.retirement_witness().unwrap();
        assert!(owner.snapshot().unwrap().custody_active);
        assert!(!witness.has_retired());
        wait(snapshot.retire());
        owner
            .ready
            .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
        assert!(witness.has_retired());
        assert!(!owner.snapshot().unwrap().custody_active);
        assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    }
    let target = output();
    let (snapshot, success) = wait(
        create(
            &owner,
            target.path().to_path_buf(),
            Arc::clone(&original),
            metadata,
        )
        .unwrap(),
    )
    .unwrap();
    success.unwrap().unwrap();
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    drop(original);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&owner).clean);
}

#[test]
fn corrupt_actual_namespace_quarantines_source_and_requires_physical_cleanup() {
    let (_source, owner, native, original, metadata) = source();
    wait(
        owner
            .with_store_retaining(
                StoreIoKind::RecoveryWrite,
                4096,
                Arc::clone(&original) as Arc<dyn std::any::Any + Send + Sync>,
                |engine| {
                    engine.apply(AtomicBatch {
                        expectations: vec![],
                        mutations: vec![RowMutation {
                            key: RowKey {
                                family: Family::Namespace,
                                key: namespace_record_key(
                                    &TenantId("tenant".into()),
                                    &StateNamespaceId("business".into()),
                                )
                                .unwrap(),
                            },
                            value: Some(b"corrupt actual namespace codec".to_vec()),
                        }],
                    })
                },
            )
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    let target = output();
    let (mut snapshot, refused) = wait(reviewed(
        &owner,
        target.path(),
        Arc::clone(&original),
        metadata,
        |_| panic!("actual source decoding must fail before installed review"),
    ))
    .unwrap();
    assert_eq!(
        refused,
        Err(ProtectedStoreError::Store(StoreError::Corrupt))
    );
    assert_eq!(
        owner.failure(),
        Some(ProtectedStoreError::Store(StoreError::Corrupt))
    );
    let witness = snapshot.retirement_witness().unwrap();
    assert!(!witness.has_retired());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert!(witness.has_retired());
    drop(original);
    let report = finish(&owner);
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
}

#[test]
fn detached_uncertain_source_fault_retains_original_capacity_until_worker_returns() {
    let (_source, owner, native, original, metadata) = source();
    let target = output();
    let gates = Rendezvous::new(1);
    let worker_gates = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let returned = Arc::new(AtomicBool::new(false));
    let worker_returned = Arc::clone(&returned);
    let weak = Arc::downgrade(&original);
    let job = reviewed(&owner, target.path(), original, metadata, move |_| {
        pause_review(&worker_gates, notice);
        worker_returned.store(true, Ordering::SeqCst);
        // A controlled original source-I/O uncertainty injection. It does not
        // certify a real device fault, nonexecution, abort or safe retry.
        Err(SnapshotError::Source(StoreError::CommitUncertain))
    });
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    drop(job);
    assert!(!returned.load(Ordering::SeqCst));
    assert!(weak.upgrade().is_some());
    assert!(owner.snapshot().unwrap().custody_active);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    owner.close();
    let mut drain = Box::pin(
        owner
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    PollProbe::default().pending(drain.as_mut());
    assert!(weak.upgrade().is_some());
    gates.release(ticket).unwrap();
    let report = wait(drain);
    assert!(returned.load(Ordering::SeqCst));
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    assert_eq!(
        owner.failure(),
        Some(ProtectedStoreError::Store(StoreError::CommitUncertain))
    );
    assert!(weak.upgrade().is_none());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
}

#[test]
fn elapsed_original_deadline_during_held_review_is_healthy_and_never_reissued() {
    let clock = TestClock::new(1000, Instant::now(), 1);
    let (_source, owner, native, original, metadata) = source_with_clock(Arc::new(clock.clone()));
    let target = output();
    let artifacts = metadata.required_artifacts.clone();
    let gates = Rendezvous::new(1);
    let worker_gates = gates.clone();
    let (notice, receiver) = mpsc::channel();
    let captured_deadline = original.original_deadline();
    let job = reviewed(
        &owner,
        target.path(),
        Arc::clone(&original),
        metadata,
        move |_| {
            pause_review(&worker_gates, notice);
            Ok(SnapshotClosure {
                inventory: RetainedInventory::default(),
                required_artifacts: artifacts,
            })
        },
    );
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    clock.advance(std::time::Duration::from_secs(31));
    assert!(original.with_live(|| ()).is_err());
    assert_eq!(original.original_deadline(), captured_deadline);
    assert!(owner.snapshot().unwrap().custody_active);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    let (mut snapshot, refused) = wait(job).unwrap();
    // Actual original native expiry is checked before file writes. The partial
    // private output remains an output refusal, never source quarantine.
    assert_eq!(refused.unwrap(), Err(SnapshotError::Output));
    assert_eq!(owner.failure(), None);
    let witness = snapshot.retirement_witness().unwrap();
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert!(witness.has_retired());
    assert!(!owner.snapshot().unwrap().custody_active);
    drop(original);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    let status = wait(
        owner
            .with_store(StoreIoKind::RecoveryRead, 0, |store| {
                StoreIdentity::inspect(&store.snapshot()?)
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert!(status.is_some());
    assert!(
        wait(
            owner
                .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
                .unwrap()
        )
        .clean
    );
}
