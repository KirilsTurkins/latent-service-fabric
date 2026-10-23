//! Real row allocations, original ledger refusal and retained physical owners.
use super::*;
use crate::broker::session::{native_handle, HandleEntryOwner};
use latent_core::BudgetProfile;

pub(super) fn row_bytes() -> u64 {
    HandleEntryOwner::allocation_bytes().unwrap()
        + native_handle::payload_bytes("read", resource()).unwrap()
}

#[test]
fn original_handle_native_backing_is_distinct_from_logical_metadata_and_legacy() {
    for profile in [BudgetProfile::Phase1, BudgetProfile::Phase3] {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = super::resource_table_memory::selected(&fixture, profile);
        let session = fixture.session(&request, &control);
        let baseline = control.budget.host_memory_bytes();
        let guards = control.budget.outstanding_reservations();
        let metadata = fixture.broker.snapshot().metadata_bytes;
        let handle = session.bind(CAP, "read", resource()).unwrap();
        let row = session.row(handle).unwrap();
        assert_eq!(row.operation.capacity(), 4);
        let latent_policy::capability::ResourceRequest::Secrets { reference } = &row.resource
        else {
            panic!("actual sealed secret binding")
        };
        assert_eq!(reference.capacity(), 8);
        let actual = HandleEntryOwner::allocation_bytes().unwrap()
            + row.operation.capacity() as u64
            + 64
            + reference.capacity() as u64
            + 64;
        assert_eq!(actual, row_bytes());
        assert_ne!(actual, 8192);
        assert_eq!(fixture.broker.snapshot().metadata_bytes, metadata + 8192);
        let paid = if profile.supports_descendants() {
            actual
        } else {
            0
        };
        assert_eq!(control.budget.host_memory_bytes(), baseline + paid);
        assert_eq!(
            control.budget.outstanding_reservations(),
            guards + if paid > 0 { 2 } else { 0 }
        );
        session.close_handle(handle).unwrap();
        assert!(session.row(handle).is_err());
        assert_eq!(control.budget.host_memory_bytes(), baseline + paid);
        assert_eq!(fixture.broker.snapshot().handles, 1);
        std::thread::spawn(move || drop(row)).join().unwrap();
        assert_eq!(control.budget.host_memory_bytes(), baseline);
        assert_eq!(control.budget.outstanding_reservations(), guards);
        assert_eq!(fixture.broker.snapshot().metadata_bytes, metadata);
        assert_eq!(fixture.broker.snapshot().handles, 0);
        drop(session);
        drop(fixture);
        assert_eq!(control.budget.host_memory_bytes(), 0);
        assert_eq!(control.budget.outstanding_reservations(), 0);
    }
}

#[test]
fn original_handle_native_refusal_precedes_allocation_and_preserves_admission() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let session = fixture.session(&request, &control);
    let baseline = control.budget.host_memory_bytes();
    let guards = control.budget.outstanding_reservations();
    let held_bytes = request.budget.memory_bytes - baseline - row_bytes() + 1;
    let mut held = control.budget.reserve_host_memory(held_bytes).unwrap();
    let padding = vec![0u8; held_bytes as usize].into_boxed_slice();
    held.confirm();
    let before = fixture.broker.snapshot();
    let failure = session.bind(CAP, "read", resource()).unwrap_err();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(fixture.broker.snapshot(), before);
    assert!(session
        .core
        .state
        .lock()
        .unwrap()
        .slots
        .iter()
        .all(Option::is_none));
    assert_eq!(control.budget.host_memory_bytes(), baseline + held_bytes);
    assert_eq!(control.budget.outstanding_reservations(), guards + 1);
    assert_eq!(
        control
            .budget
            .snapshot_at(std::time::Instant::now())
            .peak_memory_bytes,
        baseline + held_bytes
    );
    drop(padding);
    drop(held);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    assert_eq!(control.budget.host_memory_bytes(), baseline + row_bytes());
    session.close_handle(handle).unwrap();
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(control.budget.outstanding_reservations(), guards);
    drop(session);
    drop(fixture);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}

#[test]
fn original_handle_last_shared_drops_keep_text_headers_and_stats_paid_after_session_close() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let (_, stats) = crate::broker::session::native_backing::payload_bytes(
        &request,
        &fixture.plan.target.tenant.0,
        fixture.broker.limits().maximum_handles_per_session,
    )
    .unwrap();
    let session = fixture.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let first = session.row(handle).unwrap();
    let second = first.clone();
    assert!(HandleEntryOwner::ptr_eq(&first, &second));
    drop(session);
    let headers = super::session_native_memory::header_bytes(BudgetProfile::Phase3);
    assert_eq!(
        control.budget.host_memory_bytes(),
        headers + stats + row_bytes()
    );
    assert_eq!(fixture.broker.snapshot().sessions, 0);
    assert_eq!(fixture.broker.snapshot().handles, 1);
    let barrier = Arc::new(std::sync::Barrier::new(3));
    std::thread::scope(|scope| {
        for row in [first, second] {
            let barrier = barrier.clone();
            scope.spawn(move || {
                barrier.wait();
                drop(row);
            });
        }
        barrier.wait();
    });
    assert_eq!(fixture.broker.snapshot().handles, 0);
    assert_eq!(control.budget.host_memory_bytes(), headers);
    assert_eq!(control.budget.outstanding_reservations(), 2);
    drop(fixture);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}
