//! Real fixed Recovery worker/file/result custody with controlled read owners.
//! These fixtures do not qualify authenticated RPC or Fresh restore approval.

use super::*;
use crate::recovery::snapshot::{SnapshotManifest, SnapshotReceipt};
use latent_core::{native_capacity::NativeBufferClass, test_support::coordination::PauseTicket};
use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Mutex,
};

struct Owners {
    artifacts: Vec<RequiredArtifact>,
    current: AtomicBool,
    artifact_refusal: AtomicBool,
    ignore_gate: AtomicBool,
    rows: AtomicUsize,
    acceptances: AtomicUsize,
    gate: Mutex<Option<(Rendezvous, mpsc::Sender<PauseTicket>)>>,
}
impl Owners {
    fn new(metadata: &SnapshotMetadata) -> Arc<Self> {
        Arc::new(Self {
            artifacts: metadata.required_artifacts.clone(),
            current: AtomicBool::new(true),
            artifact_refusal: AtomicBool::new(false),
            ignore_gate: AtomicBool::new(false),
            rows: AtomicUsize::new(0),
            acceptances: AtomicUsize::new(0),
            gate: Mutex::new(None),
        })
    }

    fn pause(&self) -> (Rendezvous, mpsc::Receiver<PauseTicket>) {
        let gates = Rendezvous::new(1);
        let (notice, receiver) = mpsc::channel();
        *self.gate.lock().unwrap() = Some((gates.clone(), notice));
        (gates, receiver)
    }
}
impl SnapshotReceiptOwners for Owners {
    fn row(&self, key: &RowKey, bytes: &[u8]) -> Result<(), StoreError> {
        self.rows.fetch_add(1, Ordering::SeqCst);
        row(key, bytes)
    }

    fn artifact(&self, artifact: &RequiredArtifact) -> Result<(), StoreError> {
        if self.artifact_refusal.load(Ordering::SeqCst) || !self.artifacts.contains(artifact) {
            Err(StoreError::UnsupportedFormat)
        } else {
            Ok(())
        }
    }

    fn review(&self, receipt: &SnapshotReceipt) -> Result<(), StoreError> {
        if let Some((gates, notice)) = self.gate.lock().unwrap().take() {
            let (registration, mut tracked) = gates.track(()).unwrap();
            tracked.commit(Stage::Entered).unwrap();
            let mut pause = Box::pin(tracked.pause());
            PollProbe::default().pending(pause.as_mut());
            notice
                .send(gates.blocked(registration, Stage::Entered).unwrap())
                .unwrap();
            block_on(pause);
        }
        receipt.manifest.validate()?;
        self.current()
    }

    fn current(&self) -> Result<(), StoreError> {
        if self.current.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(StoreError::Unavailable)
        }
    }

    fn accept_read(&self, native: SnapshotReceiptReadFence<'_>) -> Result<(), StoreError> {
        self.current()?;
        self.acceptances.fetch_add(1, Ordering::SeqCst);
        if self.ignore_gate.load(Ordering::SeqCst) {
            Ok(())
        } else {
            native.accept()
        }
    }
}

fn expected(receipt: &SnapshotReceipt) -> RestoreInputPrecondition {
    RestoreInputPrecondition {
        snapshot_digest: receipt.snapshot_digest,
        manifest_digest: receipt.manifest_digest,
    }
}

fn checkpoint(
    owner: &ProtectedStoreOwner,
    target: &std::path::Path,
    original: Arc<NativeReservation>,
    metadata: SnapshotMetadata,
) -> (ProtectedSnapshot, RestoreInputPrecondition) {
    let (snapshot, receipt) =
        wait(create(owner, target.to_path_buf(), original, metadata).unwrap()).unwrap();
    let receipt = receipt.unwrap().unwrap();
    (snapshot, expected(&receipt))
}

fn retained(
    owner: &ProtectedStoreOwner,
    snapshot: ProtectedSnapshot,
    expected: RestoreInputPrecondition,
    owners: Arc<Owners>,
) -> (
    ProtectedSnapshot,
    Result<ProtectedSnapshotReceipt, SnapshotError>,
) {
    let (snapshot, result) = wait(
        owner
            .inspect_retained_snapshot(snapshot, expected, owners)
            .unwrap(),
    )
    .unwrap();
    (snapshot, result.unwrap())
}

#[test]
fn receipt_and_manifest_frame_keep_original_response_after_positive_file_retirement() {
    let (_source, owner, native, original, metadata) = source_with_response(
        Arc::new(SystemActivationClock),
        SNAPSHOT_RECEIPT_RESPONSE_BYTES,
    );
    let owners = Owners::new(&metadata);
    let weak = Arc::downgrade(&owners);
    let target = output();
    let (snapshot, expected) = checkpoint(&owner, target.path(), Arc::clone(&original), metadata);
    let (mut snapshot, result) = retained(&owner, snapshot, expected, owners.clone());
    let result = result.unwrap();
    assert_eq!(result.response_bytes(), SNAPSHOT_RECEIPT_RESPONSE_BYTES);
    assert!(original
        .reserve_buffer(NativeBufferClass::Response, 1)
        .is_err());
    assert_eq!(owners.acceptances.load(Ordering::SeqCst), 1);
    let frame = result.encode_manifest().unwrap();
    assert_eq!(
        SnapshotManifest::decode(frame.as_ref()).unwrap(),
        frame.receipt().manifest
    );
    assert_eq!(
        <[u8; 32]>::from(Sha256::digest(frame.as_ref())),
        frame.receipt().manifest_digest
    );
    let witness = snapshot.retirement_witness().unwrap();
    drop(owners);
    drop(original);
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert!(witness.has_retired());
    assert!(!owner.snapshot().unwrap().custody_active);
    assert!(weak.upgrade().is_some());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    frame.check().unwrap();
    drop(frame);
    assert!(weak.upgrade().is_none());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&owner).clean);
}

#[test]
fn finite_response_pressure_refuses_before_decoder_and_leaves_healthy_source_reusable() {
    let (_source, owner, native, original, metadata) = source();
    let owners = Owners::new(&metadata);
    let target = output();
    let (snapshot, expected) = checkpoint(&owner, target.path(), Arc::clone(&original), metadata);
    let (snapshot, result) = retained(&owner, snapshot, expected, owners.clone());
    assert_eq!(result.err(), Some(SnapshotError::Capacity));
    assert_eq!(owners.rows.load(Ordering::SeqCst), 0);
    assert_eq!(owners.acceptances.load(Ordering::SeqCst), 0);
    assert_eq!(owner.failure(), None);
    let (snapshot, receipt) = wait(owner.inspect_created_snapshot(snapshot, row).unwrap()).unwrap();
    receipt.unwrap().unwrap();
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    drop(original);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&owner).clean);
}

#[test]
fn exact_digest_artifact_owner_and_affine_gate_refuse_without_read_authority_refresh() {
    let (_source, owner, native, original, metadata) = source_with_response(
        Arc::new(SystemActivationClock),
        SNAPSHOT_RECEIPT_RESPONSE_BYTES,
    );
    let owners = Owners::new(&metadata);
    let target = output();
    let (snapshot, input) = checkpoint(
        &owner,
        target.path(),
        Arc::clone(&original),
        metadata.clone(),
    );
    let (snapshot, result) = retained(
        &owner,
        snapshot,
        RestoreInputPrecondition {
            snapshot_digest: [1; 32],
            manifest_digest: input.manifest_digest,
        },
        owners.clone(),
    );
    assert_eq!(
        result.err(),
        Some(SnapshotError::Review(StoreError::Conflict))
    );
    owners.artifact_refusal.store(true, Ordering::SeqCst);
    let (snapshot, result) = retained(
        &owner,
        snapshot,
        RestoreInputPrecondition {
            snapshot_digest: input.snapshot_digest,
            manifest_digest: input.manifest_digest,
        },
        owners.clone(),
    );
    assert_eq!(
        result.err(),
        Some(SnapshotError::Review(StoreError::UnsupportedFormat))
    );
    let replacement = Owners::new(&metadata);
    let (snapshot, result) = retained(
        &owner,
        snapshot,
        RestoreInputPrecondition {
            snapshot_digest: input.snapshot_digest,
            manifest_digest: input.manifest_digest,
        },
        replacement.clone(),
    );
    assert_eq!(
        result.err(),
        Some(SnapshotError::Review(StoreError::Conflict))
    );
    assert_eq!(replacement.rows.load(Ordering::SeqCst), 0);
    owners.artifact_refusal.store(false, Ordering::SeqCst);
    owners.ignore_gate.store(true, Ordering::SeqCst);
    let (snapshot, result) = retained(&owner, snapshot, input, owners.clone());
    assert_eq!(
        result.err(),
        Some(SnapshotError::Review(StoreError::Invalid))
    );
    assert_eq!(owner.failure(), None);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    let buffer = original
        .reserve_buffer(NativeBufferClass::Response, SNAPSHOT_RECEIPT_RESPONSE_BYTES)
        .unwrap();
    drop(buffer);
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    drop(original);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&owner).clean);
}

#[test]
fn detached_receipt_waiter_retains_original_response_and_file_until_worker_cleanup() {
    let (_source, owner, native, original, metadata) = source_with_response(
        Arc::new(SystemActivationClock),
        SNAPSHOT_RECEIPT_RESPONSE_BYTES,
    );
    let owners = Owners::new(&metadata);
    let weak = Arc::downgrade(&owners);
    let (gates, receiver) = owners.pause();
    let target = output();
    let (mut snapshot, expected) =
        checkpoint(&owner, target.path(), Arc::clone(&original), metadata);
    let witness = snapshot.retirement_witness().unwrap();
    let job = owner
        .inspect_retained_snapshot(snapshot, expected, owners.clone())
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    drop(job);
    drop(owners);
    drop(original);
    assert!(!witness.has_retired());
    assert!(weak.upgrade().is_some());
    assert!(owner.snapshot().unwrap().custody_active);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert!(witness.has_retired());
    assert!(weak.upgrade().is_none());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert_eq!(owner.failure(), None);
    assert!(finish(&owner).clean);
}

#[test]
fn original_expiry_during_held_receipt_review_cannot_reissue_current_native_owner() {
    let clock = TestClock::new(1000, Instant::now(), 1);
    let (_source, owner, native, original, metadata) =
        source_with_response(Arc::new(clock.clone()), SNAPSHOT_RECEIPT_RESPONSE_BYTES);
    let owners = Owners::new(&metadata);
    let (gates, receiver) = owners.pause();
    let target = output();
    let deadline = original.original_deadline();
    let (snapshot, expected) = checkpoint(&owner, target.path(), Arc::clone(&original), metadata);
    let job = owner
        .inspect_retained_snapshot(snapshot, expected, owners)
        .unwrap();
    let ticket = receiver.recv_timeout(WATCHDOG).unwrap();
    clock.advance(std::time::Duration::from_secs(31));
    assert_eq!(original.original_deadline(), deadline);
    assert!(original.with_live(|| ()).is_err());
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    gates.release(ticket).unwrap();
    let (snapshot, result) = wait(job).unwrap();
    assert_eq!(result.unwrap().err(), Some(SnapshotError::Deadline));
    assert_eq!(owner.failure(), None);
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    drop(original);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert!(
        wait(
            owner
                .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
                .unwrap()
        )
        .clean
    );
}

#[test]
fn revoked_receipt_and_encoded_frame_keep_capacity_until_actual_response_destruction() {
    let (_source, owner, native, original, metadata) = source_with_response(
        Arc::new(SystemActivationClock),
        SNAPSHOT_RECEIPT_RESPONSE_BYTES,
    );
    let owners = Owners::new(&metadata);
    let target = output();
    let (snapshot, expected) = checkpoint(&owner, target.path(), Arc::clone(&original), metadata);
    let (snapshot, result) = retained(&owner, snapshot, expected, owners.clone());
    let frame = result.unwrap().encode_manifest().unwrap();
    owners.current.store(false, Ordering::SeqCst);
    assert_eq!(
        frame.check(),
        Err(SnapshotError::Review(StoreError::Unavailable))
    );
    assert!(!frame.as_ref().is_empty());
    assert!(original
        .reserve_buffer(NativeBufferClass::Response, 1)
        .is_err());
    wait(snapshot.retire());
    owner
        .ready
        .wait_test_metadata_retirement(Instant::now() + WATCHDOG);
    assert_eq!(owner.failure(), None);
    drop(original);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 1);
    drop(frame);
    assert_eq!(native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&owner).clean);
}
