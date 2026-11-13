use super::*;
use crate::{
    local::{LocalBlobLimits, OWNER_BYTES},
    BlobReference,
};
use latent_core::TenantId;
use latent_state::{
    embedded::{AtomicBatch, EmbeddedStore, StoreLimits},
    payload_references::{
        PayloadOwner, PayloadOwnerKind, PayloadReference, PreparedPayloadReferences,
    },
};
use std::{
    cell::Cell,
    os::unix::fs::PermissionsExt,
    panic::{catch_unwind, AssertUnwindSafe},
};

struct Fixture {
    owner: Arc<LocalBlobStore>,
    state: EmbeddedStore,
    blob_root: tempfile::TempDir,
    _state_root: tempfile::TempDir,
}
fn fixture(extra_metadata: usize, maximum_work: usize) -> Fixture {
    let blob_root = tempfile::Builder::new()
        .permissions(std::fs::Permissions::from_mode(0o700))
        .tempdir()
        .unwrap();
    let state_root = tempfile::tempdir().unwrap();
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(state_root.path().join("state.redb"))
        .unwrap();
    let state = EmbeddedStore::open_file(
        file,
        StoreLimits {
            cache_bytes: 1024 * 1024,
            ..StoreLimits::default()
        },
    )
    .unwrap();
    let view = state.snapshot().unwrap();
    let initialization = StoreIdentity::new("required-inventory".into())
        .unwrap()
        .prepare_initialization(&view)
        .unwrap()
        .unwrap();
    drop(view);
    state.apply(initialization).unwrap();
    let limits = LocalBlobLimits {
        maximum_objects: 4,
        maximum_object_bytes: 16,
        maximum_disk_bytes: 65536,
        maximum_stages: 4,
        maximum_stage_bytes: 32,
        maximum_handles: 4,
        maximum_chunk_bytes: 8,
        maximum_metadata_bytes: OWNER_BYTES + extra_metadata,
        maximum_work,
    };
    let owner = LocalBlobStore::open_durable(blob_root.path(), "private", limits, &state).unwrap();
    Fixture {
        owner,
        state,
        blob_root,
        _state_root: state_root,
    }
}
fn tenant() -> TenantId {
    TenantId("alice".into())
}
fn put(owner: &LocalBlobStore, bytes: &[u8]) -> BlobReference {
    let mut writer = owner
        .create(
            &tenant(),
            "text/plain",
            Some(bytes.len() as u64),
            &|| Ok(()),
        )
        .unwrap();
    writer.write(0, bytes, &|| Ok(())).unwrap();
    writer.seal(&|| Ok(())).unwrap()
}
fn retain(fixture: &Fixture) -> BlobReference {
    let blob = put(&fixture.owner, b"data");
    let pin = fixture
        .owner
        .capture_durable_reference(&tenant(), &blob, &|| Ok(()))
        .unwrap();
    // Distinct real owner rows share one physical object; no guest count is used.
    let changes = [PayloadOwnerKind::Result, PayloadOwnerKind::Effect]
        .into_iter()
        .enumerate()
        .map(|(index, kind)| {
            (
                None,
                Some(PayloadReference {
                    owner: PayloadOwner {
                        tenant: tenant().0,
                        namespace: "business".into(),
                        incarnation: 1,
                        kind,
                        identity: [u8::try_from(index + 1).unwrap(); 32],
                        generation: 1,
                        format: "application-v1".into(),
                    },
                    payload: pin.identity("local-a", 1).unwrap(),
                }),
            )
        })
        .collect::<Vec<_>>();
    let view = fixture.state.snapshot().unwrap();
    let plan = PreparedPayloadReferences::prepare(&view, &changes).unwrap();
    let mut batch = AtomicBatch::default();
    plan.append_to(&mut batch).unwrap();
    drop(view);
    fixture.state.apply(batch).unwrap();
    drop(pin);
    blob
}
fn next(
    cursor: &mut RequiredBlobInventory,
    fixture: &Fixture,
    view: &ReadView,
) -> Result<(usize, bool)> {
    cursor.next_page(&fixture.owner, view, 1, MAX_REFERENCE_BYTES, &|| Ok(()))
}

fn minimum_metadata() -> usize {
    CURSOR_BYTES + page_bytes(1, MAX_REFERENCE_BYTES).unwrap() + HANDLE_BYTES
}

#[test]
fn cursor_admission_charges_metadata_and_refuses_unusable_work_or_memory_limits() {
    for (bytes, work) in [(minimum_metadata(), 1), (minimum_metadata() - 1, 2)] {
        let fixture = fixture(bytes, work);
        let view = fixture.state.snapshot().unwrap();
        let before = fixture.owner.snapshot().unwrap();
        assert!(matches!(
            RequiredBlobInventory::begin(&fixture.owner, &view),
            Err(LocalBlobError::Capacity)
        ));
        assert_eq!(fixture.owner.snapshot().unwrap(), before);
    }
    let fixture = fixture(minimum_metadata(), 2);
    let view = fixture.state.snapshot().unwrap();
    let before = fixture.owner.snapshot().unwrap();
    let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
    assert_eq!(
        fixture.owner.snapshot().unwrap().metadata_bytes,
        before.metadata_bytes + CURSOR_BYTES
    );
    assert_eq!(fixture.owner.snapshot().unwrap().active_work, 1);
    assert_eq!(next(&mut cursor, &fixture, &view), Ok((0, true)));
    drop(cursor);
    assert_eq!(fixture.owner.snapshot().unwrap(), before);
}

#[test]
fn page_capacity_refusal_is_terminal_and_refunds_only_its_own_reservation() {
    let fixture = fixture(minimum_metadata(), 2);
    let view = fixture.state.snapshot().unwrap();
    let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
    let before = fixture.owner.snapshot().unwrap();
    assert_eq!(
        cursor.next_page(
            &fixture.owner,
            &view,
            MAX_REFERENCE_UPDATES,
            MAX_REFERENCE_UPDATES * MAX_REFERENCE_BYTES,
            &|| Ok(()),
        ),
        Err(LocalBlobError::Capacity)
    );
    assert_eq!(fixture.owner.snapshot().unwrap(), before);
    assert_eq!(
        next(&mut cursor, &fixture, &view),
        Err(LocalBlobError::PermissionDenied)
    );
    drop(cursor);
    let mut fresh = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
    assert_eq!(next(&mut fresh, &fixture, &view), Ok((0, true)));
}

#[test]
fn required_rows_and_native_verification_fit_two_work_slots_and_remain_prepaid() {
    let fixture = fixture(512 * 1024, 2);
    retain(&fixture);
    let view = fixture.state.snapshot().unwrap();
    let base = fixture.owner.snapshot().unwrap();
    let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
    let page_charge = page_bytes(1, MAX_REFERENCE_BYTES).unwrap();
    let saw_native_reader = Cell::new(false);
    let checkpoint = || {
        let snapshot = fixture.owner.snapshot().unwrap();
        if snapshot.handles != 0 {
            saw_native_reader.set(true);
            assert_eq!(snapshot.active_work, 2);
            assert_eq!(
                snapshot.metadata_bytes,
                base.metadata_bytes + CURSOR_BYTES + page_charge + HANDLE_BYTES
            );
        }
        Ok(())
    };
    let mut observed = 0;
    loop {
        let (count, complete) = cursor
            .next_page(&fixture.owner, &view, 1, MAX_REFERENCE_BYTES, &checkpoint)
            .unwrap();
        observed += count;
        assert_eq!(
            fixture.owner.snapshot().unwrap().metadata_bytes,
            base.metadata_bytes + CURSOR_BYTES
        );
        assert_eq!(fixture.owner.snapshot().unwrap().handles, 0);
        if complete {
            break;
        }
        assert!(observed <= 2);
    }
    assert_eq!(observed, 2);
    assert!(saw_native_reader.get());
    drop(cursor);
    assert_eq!(fixture.owner.snapshot().unwrap(), base);
}

#[test]
fn cancellation_or_unwind_during_admission_refunds_all_cursor_ownership() {
    let fixture = fixture(512 * 1024, 2);
    let view = fixture.state.snapshot().unwrap();
    let before = fixture.owner.snapshot().unwrap();
    for unwind in [false, true] {
        let calls = Cell::new(0);
        let result = catch_unwind(AssertUnwindSafe(|| {
            RequiredBlobInventory::begin_with_checkpoint(&fixture.owner, &view, &|| {
                calls.set(calls.get() + 1);
                if calls.get() == 2 {
                    assert_eq!(
                        fixture.owner.snapshot().unwrap().metadata_bytes,
                        before.metadata_bytes + CURSOR_BYTES,
                    );
                    assert!(!unwind, "injected admission unwind");
                    return Err(LocalBlobError::Cancelled);
                }
                Ok(())
            })
        }));
        if unwind {
            assert!(result.is_err());
        } else {
            assert!(matches!(result.unwrap(), Err(LocalBlobError::Cancelled)));
        }
        assert_eq!(calls.get(), 2);
        assert_eq!(fixture.owner.snapshot().unwrap(), before);
    }
}

#[test]
fn failed_or_panicking_empty_completion_refunds_scratch_but_cannot_resume() {
    let fixture = fixture(512 * 1024, 2);
    let view = fixture.state.snapshot().unwrap();
    let base = fixture.owner.snapshot().unwrap();
    for unwind in [false, true] {
        let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
        let calls = Cell::new(0);
        let result = catch_unwind(AssertUnwindSafe(|| {
            cursor.next_page(&fixture.owner, &view, 1, MAX_REFERENCE_BYTES, &|| {
                calls.set(calls.get() + 1);
                if calls.get() == 2 {
                    let expected = base.metadata_bytes
                        + CURSOR_BYTES
                        + page_bytes(1, MAX_REFERENCE_BYTES).unwrap();
                    assert_eq!(fixture.owner.snapshot().unwrap().metadata_bytes, expected);
                    assert!(!unwind, "injected completion unwind");
                    return Err(LocalBlobError::DeadlineExceeded);
                }
                Ok(())
            })
        }));
        if unwind {
            assert!(result.is_err());
        } else {
            assert_eq!(result.unwrap(), Err(LocalBlobError::DeadlineExceeded));
        }
        assert_eq!(calls.get(), 2);
        assert_eq!(
            fixture.owner.snapshot().unwrap().metadata_bytes,
            base.metadata_bytes + CURSOR_BYTES
        );
        assert_eq!(
            next(&mut cursor, &fixture, &view),
            Err(LocalBlobError::PermissionDenied),
        );
        drop(cursor);
        assert_eq!(fixture.owner.snapshot().unwrap(), base);
    }
}

#[test]
fn publication_between_pages_invalidates_the_original_physical_observation() {
    let fixture = fixture(512 * 1024, 2);
    retain(&fixture);
    let view = fixture.state.snapshot().unwrap();
    let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
    assert_eq!(next(&mut cursor, &fixture, &view), Ok((1, false)));
    put(&fixture.owner, b"other");
    assert_eq!(
        next(&mut cursor, &fixture, &view),
        Err(LocalBlobError::Busy)
    );
    assert_eq!(
        next(&mut cursor, &fixture, &view),
        Err(LocalBlobError::PermissionDenied)
    );
}

#[test]
fn empty_completion_cannot_ignore_a_publication_from_its_final_checkpoint() {
    let fixture = fixture(512 * 1024, 2);
    let view = fixture.state.snapshot().unwrap();
    let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
    let calls = Cell::new(0);
    assert_eq!(
        cursor.next_page(&fixture.owner, &view, 1, MAX_REFERENCE_BYTES, &|| {
            calls.set(calls.get() + 1);
            if calls.get() == 2 {
                put(&fixture.owner, b"other");
            }
            Ok(())
        }),
        Err(LocalBlobError::Busy)
    );
    assert_eq!(calls.get(), 2);
    assert_eq!(fixture.owner.snapshot().unwrap().objects, 1);
    assert_eq!(
        next(&mut cursor, &fixture, &view),
        Err(LocalBlobError::PermissionDenied)
    );
}

#[test]
fn substituting_a_view_or_owner_invalidates_the_original_cursor() {
    let fixture = fixture(512 * 1024, 2);
    let other = self::fixture(512 * 1024, 2);
    let view = fixture.state.snapshot().unwrap();
    let newer = fixture.state.snapshot().unwrap();
    for (store, snapshot) in [(&fixture.owner, &newer), (&other.owner, &view)] {
        let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
        assert_eq!(
            cursor.next_page(store, snapshot, 1, MAX_REFERENCE_BYTES, &|| Ok(())),
            Err(LocalBlobError::PermissionDenied),
        );
        assert_eq!(
            next(&mut cursor, &fixture, &view),
            Err(LocalBlobError::PermissionDenied),
        );
    }
}

#[test]
fn required_file_failure_never_completes_or_refunds_the_cursor_early() {
    let fixture = fixture(512 * 1024, 2);
    let blob = retain(&fixture);
    let record = crate::local::ReferenceRecord::requested("private", &tenant(), &blob, 16).unwrap();
    let view = fixture.state.snapshot().unwrap();
    let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
    let before = fixture.owner.snapshot().unwrap();
    std::fs::remove_file(
        fixture
            .blob_root
            .path()
            .join("objects")
            .join(record.key())
            .join("data"),
    )
    .unwrap();
    assert_eq!(
        next(&mut cursor, &fixture, &view),
        Err(LocalBlobError::Corrupt)
    );
    assert_eq!(fixture.owner.snapshot().unwrap(), before);
    assert_eq!(
        next(&mut cursor, &fixture, &view),
        Err(LocalBlobError::PermissionDenied)
    );
    drop(cursor);
    assert_eq!(fixture.owner.snapshot().unwrap().active_work, 0);
    assert_eq!(
        fixture.owner.snapshot().unwrap().metadata_bytes,
        before.metadata_bytes - CURSOR_BYTES,
    );
}

#[test]
fn invalid_page_bounds_and_owner_close_cannot_publish_empty_completion() {
    let fixture = fixture(512 * 1024, 2);
    let view = fixture.state.snapshot().unwrap();
    for (rows, bytes) in [(0, 1), (1, 0), (usize::MAX, 1), (1, usize::MAX)] {
        let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
        let before = fixture.owner.snapshot().unwrap();
        assert_eq!(
            cursor.next_page(&fixture.owner, &view, rows, bytes, &|| Ok(())),
            Err(LocalBlobError::Capacity)
        );
        assert_eq!(fixture.owner.snapshot().unwrap(), before);
        assert_eq!(
            next(&mut cursor, &fixture, &view),
            Err(LocalBlobError::PermissionDenied)
        );
    }
    let mut cursor = RequiredBlobInventory::begin(&fixture.owner, &view).unwrap();
    let calls = Cell::new(0);
    assert_eq!(
        cursor.next_page(&fixture.owner, &view, 1, MAX_REFERENCE_BYTES, &|| {
            calls.set(calls.get() + 1);
            if calls.get() == 2 {
                fixture.owner.close();
            }
            Ok(())
        }),
        Err(LocalBlobError::Closed)
    );
    assert_eq!(calls.get(), 2);
    assert_eq!(
        next(&mut cursor, &fixture, &view),
        Err(LocalBlobError::PermissionDenied)
    );
    assert_eq!(fixture.owner.snapshot().unwrap().active_work, 1);
    drop(cursor);
    assert_eq!(fixture.owner.snapshot().unwrap().active_work, 0);
}
