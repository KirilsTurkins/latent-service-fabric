//! Actual copied input/reply storage stays on its original physical ledger.
use super::*;
use crate::broker::work::native_buffer::NativeBuffer;
use latent_core::BudgetProfile;

#[test]
fn original_call_native_buffer_capacity_empty_legacy_and_budget_identity_are_closed() {
    for profile in [BudgetProfile::Phase1, BudgetProfile::Phase3] {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (_, first) = super::resource_table_memory::selected(&fixture, profile);
        let (_, second) = super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
        let empty = NativeBuffer::copy(&first.budget, &[]).unwrap();
        assert!(empty.is_empty());
        assert_eq!(empty.capacity(), 0);
        assert!(!empty.charged_to(&first.budget));
        assert_eq!(first.budget.host_memory_bytes(), 0);
        assert_eq!(first.budget.outstanding_reservations(), 0);
        let bytes = NativeBuffer::copy(&first.budget, b"copied").unwrap();
        assert_eq!(&*bytes, b"copied");
        assert_eq!(bytes.capacity(), 6);
        let paid = if profile.supports_descendants() {
            6 + 64
        } else {
            0
        };
        assert_eq!(first.budget.host_memory_bytes(), paid);
        assert_eq!(
            first.budget.outstanding_reservations(),
            u64::from(paid != 0)
        );
        assert_eq!(bytes.charged_to(&first.budget), paid != 0);
        assert!(!bytes.charged_to(&second.budget));
        assert_eq!(second.budget.host_memory_bytes(), 0);
        drop(bytes);
        drop(empty);
        assert_eq!(first.budget.host_memory_bytes(), 0);
        assert_eq!(first.budget.outstanding_reservations(), 0);
        assert_eq!(second.budget.host_memory_bytes(), 0);
    }
}

#[test]
fn original_call_native_input_refusal_precedes_dispatch_and_preserves_each_counter() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let session = fixture.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let baseline = control.budget.host_memory_bytes();
    let guards = control.budget.outstanding_reservations();
    let input = b"input";
    let held_bytes = request.budget.memory_bytes - baseline - (input.len() as u64 + 64) + 1;
    let mut held = control.budget.reserve_host_memory(held_bytes).unwrap();
    let padding = vec![0u8; held_bytes as usize].into_boxed_slice();
    held.confirm();
    let before = fixture.broker.snapshot();
    let mut dispatched = false;
    let failure = session
        .dispatch(handle, "read", resource(), input, output(), |call| {
            dispatched = true;
            call
        })
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert!(!dispatched);
    assert_eq!(fixture.broker.snapshot(), before);
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
    let call = session
        .dispatch(handle, "read", resource(), input, output(), |call| call)
        .unwrap();
    assert_eq!(call.input(), input);
    assert_eq!(
        control.budget.host_memory_bytes(),
        baseline + input.len() as u64 + 64
    );
    assert_eq!(control.budget.outstanding_reservations(), guards + 1);
    drop(call);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(fixture.broker.snapshot(), before);
    drop(session);
    drop(fixture);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}

#[test]
fn original_call_native_reply_refusal_requires_simultaneous_live_input_capacity() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let session = fixture.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let baseline = control.budget.host_memory_bytes();
    let guards = control.budget.outstanding_reservations();
    let before = fixture.broker.snapshot();
    let call = session
        .dispatch(handle, "read", resource(), b"input", output(), |call| call)
        .unwrap();
    let with_input = baseline + 5 + 64;
    assert_eq!(control.budget.host_memory_bytes(), with_input);
    let reply = b"response";
    let held_bytes = request.budget.memory_bytes - with_input - (reply.len() as u64 + 64) + 1;
    let mut held = control.budget.reserve_host_memory(held_bytes).unwrap();
    let padding = vec![0u8; held_bytes as usize].into_boxed_slice();
    held.confirm();
    // Refunding the input before the reply copy would incorrectly admit this.
    let failure = call.complete(reply).err().unwrap();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(control.budget.host_memory_bytes(), baseline + held_bytes);
    assert_eq!(control.budget.outstanding_reservations(), guards + 1);
    assert_eq!(fixture.broker.snapshot(), before);
    assert_eq!(
        control
            .budget
            .snapshot_at(std::time::Instant::now())
            .peak_memory_bytes,
        with_input + held_bytes
    );
    drop(padding);
    drop(held);
    let response = session
        .dispatch(handle, "read", resource(), b"input", output(), |call| {
            call.complete(reply)
        })
        .unwrap()
        .unwrap();
    assert_eq!(response.bytes(), reply);
    assert_eq!(
        control.budget.host_memory_bytes(),
        baseline + reply.len() as u64 + 64
    );
    assert_eq!(control.budget.outstanding_reservations(), guards + 1);
    drop(response);
    assert_eq!(control.budget.host_memory_bytes(), baseline);
    assert_eq!(fixture.broker.snapshot(), before);
    drop(session);
    drop(fixture);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}

#[test]
fn original_call_native_reply_stays_on_original_budget_after_close_and_cross_thread_drop() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let session = fixture.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let baseline = control.budget.host_memory_bytes();
    let response = session
        .dispatch(handle, "read", resource(), b"input", output(), |call| {
            call.complete(b"retained")
        })
        .unwrap()
        .unwrap();
    assert_eq!(response.bytes(), b"retained");
    assert_eq!(control.budget.host_memory_bytes(), baseline + 8 + 64);
    assert!(
        control
            .budget
            .snapshot_at(std::time::Instant::now())
            .peak_memory_bytes
            >= baseline + 5 + 64 + 8 + 64
    );
    drop(session);
    let (fresh_request, fresh_control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let fresh = fixture.session(&fresh_request, &fresh_control);
    let fresh_bytes = fresh_control.budget.host_memory_bytes();
    assert_eq!(control.budget.host_memory_bytes(), baseline + 8 + 64);
    assert_eq!(response.bytes(), b"retained");
    std::thread::spawn(move || drop(response)).join().unwrap();
    assert_eq!(
        control.budget.host_memory_bytes(),
        super::session_native_memory::header_bytes(BudgetProfile::Phase3)
    );
    assert_eq!(control.budget.outstanding_reservations(), 2);
    assert_eq!(fresh_control.budget.host_memory_bytes(), fresh_bytes);
    assert!(!fresh.observer().is_closed());
    drop(fresh);
    drop(fixture);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    assert_eq!(fresh_control.budget.host_memory_bytes(), 0);
    assert_eq!(fresh_control.budget.outstanding_reservations(), 0);
}

#[test]
fn original_call_native_buffer_unwind_returns_only_its_original_physical_charge() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (_, control) = super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let (_, foreign) = super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let bytes = NativeBuffer::copy(&control.budget, b"private").unwrap();
        assert_eq!(bytes.capacity(), 7);
        assert_eq!(control.budget.host_memory_bytes(), 7 + 64);
        assert_eq!(foreign.budget.host_memory_bytes(), 0);
        panic!("original native buffer unwind");
    }));
    assert!(result.is_err());
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    assert_eq!(foreign.budget.host_memory_bytes(), 0);
    assert_eq!(foreign.budget.outstanding_reservations(), 0);
}
