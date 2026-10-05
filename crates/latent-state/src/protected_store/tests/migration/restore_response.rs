//! Real original-response ownership after independent native file retirement.
use super::*;
use latent_core::native_capacity::NativeBufferClass;

fn reviewed(
    setup: &Setup,
    snapshot: ProtectedSnapshot,
    expected: RestoreInputPrecondition,
    owners: Arc<Owners>,
) -> (
    ProtectedSnapshot,
    Result<ProtectedRestoreInput, SnapshotError>,
) {
    let (snapshot, result) = wait(
        setup
            .owner
            .review_restore_window(snapshot, expected, owners)
            .unwrap(),
    )
    .unwrap();
    (snapshot, result.unwrap())
}

#[test]
fn retained_input_and_window_frame_keep_original_capacity_after_positive_file_retirement() {
    let mut setup = Setup::with_restore_response();
    let (snapshot, owners, request) = setup.checkpoint();
    let weak_original = Arc::downgrade(setup.original());
    let weak_owners = Arc::downgrade(&owners);
    let (snapshot, input) = reviewed(&setup, snapshot, restore_input(&request), owners.clone());
    let input = input.unwrap();
    assert_eq!(input.response_bytes(), RESTORE_INPUT_RESPONSE_BYTES);
    assert!(setup
        .original()
        .reserve_buffer(NativeBufferClass::Response, 1)
        .is_err());
    assert_eq!(owners.read_acceptances.load(Ordering::SeqCst), 1);
    let encoded = input.window().canonical_bytes().unwrap();
    drop(owners);
    setup.release_original();
    setup.retire(snapshot);
    assert!(weak_original.upgrade().is_some());
    assert!(weak_owners.upgrade().is_some());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    input.check().unwrap();
    let frame = input.encode_window().unwrap();
    assert_eq!(frame.as_ref(), encoded.as_slice());
    assert_eq!(
        frame.input().snapshot().snapshot_digest,
        request.checkpoint_digest
    );
    assert_eq!(frame.input().window().namespaces().len(), 1);
    frame.check().unwrap();
    drop(encoded);
    drop(frame);
    assert!(weak_original.upgrade().is_none());
    assert!(weak_owners.upgrade().is_none());
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&setup.owner).clean);
}

#[test]
fn insufficient_original_response_capacity_refuses_before_archive_decoder_without_store_mutation() {
    // Keep the existing smaller request declaration; no producer ceiling grows.
    let setup = Setup::new();
    let (snapshot, owners, request) = setup.checkpoint();
    let before = fs::read(setup.checkpoint_path()).unwrap();
    let (snapshot, result) = reviewed(&setup, snapshot, restore_input(&request), owners.clone());
    assert_eq!(result.err(), Some(SnapshotError::Capacity));
    assert_eq!(owners.archive_reads.load(Ordering::SeqCst), 0);
    assert_eq!(owners.read_acceptances.load(Ordering::SeqCst), 0);
    assert_eq!(setup.owner.failure(), None);
    assert_eq!(fs::read(setup.checkpoint_path()).unwrap(), before);
    setup.retire(snapshot);
    assert!(setup.observe().progress.is_none());
    assert_eq!(setup.observe().value.len(), 8);
    setup.require_census();
    assert!(finish(&setup.owner).clean);
}

#[test]
fn current_read_refusal_precedes_decode_and_returns_prepaid_response_to_same_original() {
    let setup = Setup::with_restore_response();
    let (snapshot, owners, request) = setup.checkpoint();
    owners.accept_mode.store(1, Ordering::SeqCst);
    let (snapshot, result) = reviewed(&setup, snapshot, restore_input(&request), owners.clone());
    assert_eq!(
        result.err(),
        Some(SnapshotError::Review(StoreError::Unavailable))
    );
    assert_eq!(owners.archive_reads.load(Ordering::SeqCst), 0);
    assert_eq!(owners.read_acceptances.load(Ordering::SeqCst), 0);
    let returned = setup
        .original()
        .reserve_buffer(NativeBufferClass::Response, RESTORE_INPUT_RESPONSE_BYTES)
        .unwrap();
    drop(returned);
    assert_eq!(setup.owner.failure(), None);
    setup.retire(snapshot);
    assert!(finish(&setup.owner).clean);
}

#[test]
fn revocation_after_file_retirement_denies_input_encoding_and_still_holds_physical_response() {
    let mut setup = Setup::with_restore_response();
    let (snapshot, owners, request) = setup.checkpoint();
    let (snapshot, input) = reviewed(&setup, snapshot, restore_input(&request), owners.clone());
    let input = input.unwrap();
    setup.release_original();
    setup.retire(snapshot);
    owners.accept_mode.store(1, Ordering::SeqCst);
    assert_eq!(
        input.check(),
        Err(SnapshotError::Review(StoreError::Unavailable))
    );
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    assert!(matches!(
        input.encode_window(),
        Err(SnapshotError::Review(StoreError::Unavailable))
    ));
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
    assert_eq!(setup.owner.failure(), None);
    assert!(finish(&setup.owner).clean);
}

#[test]
fn revoked_encoded_frame_keeps_same_original_until_actual_frame_destruction() {
    let mut setup = Setup::with_restore_response();
    let (snapshot, owners, request) = setup.checkpoint();
    let (snapshot, input) = reviewed(&setup, snapshot, restore_input(&request), owners.clone());
    let frame = input.unwrap().encode_window().unwrap();
    setup.release_original();
    setup.retire(snapshot);
    owners.accept_mode.store(1, Ordering::SeqCst);
    assert_eq!(
        frame.check(),
        Err(SnapshotError::Review(StoreError::Unavailable))
    );
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    assert!(!frame.as_ref().is_empty());
    drop(frame);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
    assert!(finish(&setup.owner).clean);
}

#[test]
fn expired_original_frame_cannot_gain_time_from_a_current_replacement_request() {
    let clock = TestClock::new(1000, Instant::now(), 1);
    let mut setup = Setup::with_response(Arc::new(clock.clone()), RESTORE_INPUT_RESPONSE_BYTES);
    let (snapshot, owners, request) = setup.checkpoint();
    let deadline = setup.original().original_deadline();
    let (snapshot, input) = reviewed(&setup, snapshot, restore_input(&request), owners);
    let frame = input.unwrap().encode_window().unwrap();
    setup.release_original();
    setup.retire(snapshot);
    clock.advance(std::time::Duration::from_secs(31));
    assert_eq!(frame.check(), Err(SnapshotError::Deadline));
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 1);
    // An independently admitted current request can never replace the frame's
    // original owner or deadline; both slots remain observable until real drop.
    let replacement = setup
        .native
        .reserve(
            latent_core::native_capacity::NativeAdmissionClass::Recovery,
            latent_core::native_capacity::NativeReservationRequest {
                request_bytes: 16,
                work_bytes: 16,
                response_bytes: 16,
            },
            clock.monotonic_now() + std::time::Duration::from_secs(1),
        )
        .unwrap();
    assert!(replacement.original_deadline() > deadline);
    assert_eq!(frame.check(), Err(SnapshotError::Deadline));
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 2);
    drop(replacement);
    drop(frame);
    assert_eq!(setup.native.snapshot().unwrap().recovery.slots, 0);
    assert!(
        wait(
            setup
                .owner
                .drain_async(clock.monotonic_now() + WATCHDOG, std::future::pending())
                .unwrap(),
        )
        .clean
    );
}
