//! Real sealed sessions/provider owners, not a replacement budget or mock Arc.
use super::*;
use crate::broker::session::{native_backing, RegistryEntry, SessionCoreOwner, StatsOwner};
use latent_core::BudgetProfile;

pub(super) fn header_bytes(profile: BudgetProfile) -> u64 {
    if profile.supports_descendants() {
        SessionCoreOwner::allocation_bytes().unwrap() + StatsOwner::allocation_bytes().unwrap()
    } else {
        0
    }
}
pub(super) fn drop_registry(fixture: &Fixture) {
    let mut entries = fixture.broker.inner.sessions.lock().unwrap();
    assert!(entries.iter().all(|entry| entry.core.strong_count() == 0));
    entries.fill_with(RegistryEntry::default);
}
fn amounts(fixture: &Fixture, request: &latent_executor::ExecutionRequest) -> (u64, u64, u64) {
    let (core, stats) = native_backing::payload_bytes(
        request,
        &fixture.plan.target.tenant.0,
        fixture.broker.limits().maximum_handles_per_session,
    )
    .unwrap();
    (header_bytes(BudgetProfile::Phase3), core, stats)
}

#[test]
fn original_session_native_owned_payloads_and_both_headers_share_exact_profile_budget() {
    for profile in [BudgetProfile::Phase1, BudgetProfile::Phase3] {
        let fixture = Fixture::new(CapabilityBrokerLimits::default());
        let (request, control) = super::resource_table_memory::selected(&fixture, profile);
        let (headers, core_payload, stats_payload) = amounts(&fixture, &request);
        let session = fixture.session(&request, &control);
        let expected = if profile == BudgetProfile::Phase3 {
            headers + core_payload + stats_payload
        } else {
            0
        };
        assert_eq!(control.budget.host_memory_bytes(), expected);
        assert_eq!(
            control.budget.outstanding_reservations(),
            if profile == BudgetProfile::Phase3 {
                4
            } else {
                0
            }
        );
        assert_eq!(
            session.core.state.lock().unwrap().slots.capacity(),
            fixture.broker.limits().maximum_handles_per_session
        );
        assert_eq!(
            session.core.activation_id.0.capacity(),
            request.activation.activation_id.0.len()
        );
        assert_eq!(
            session.core.principal.subject.capacity(),
            request.activation.principal.subject.len()
        );
        let observer = session.observer();
        drop(session);
        assert!(observer.is_quiescent());
        assert_eq!(fixture.broker.snapshot().sessions, 0);
        assert_eq!(
            control.budget.host_memory_bytes(),
            if profile == BudgetProfile::Phase3 {
                headers + stats_payload
            } else {
                0
            }
        );
        drop(observer);
        assert_eq!(control.budget.host_memory_bytes(), header_bytes(profile));
        drop_registry(&fixture);
        assert_eq!(control.budget.host_memory_bytes(), 0);
        assert_eq!(control.budget.outstanding_reservations(), 0);
    }
}

#[test]
fn original_session_native_refusal_rolls_back_unallocated_preparations_and_admission() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let (headers, core_payload, stats_payload) = amounts(&fixture, &request);
    let needed = headers + core_payload + stats_payload;
    let held_bytes = request.budget.memory_bytes - needed + 1;
    let mut held = control.budget.reserve_host_memory(held_bytes).unwrap();
    let padding = vec![0u8; held_bytes as usize].into_boxed_slice();
    held.confirm();
    let before = fixture.broker.snapshot();
    let failure = fixture
        .broker
        .open_session(
            fixture.plan.clone(),
            &request,
            &control,
            &fixture.publication,
        )
        .err()
        .unwrap();
    assert_eq!(failure.code, PlatformErrorCode::ResourceExhausted);
    assert_eq!(fixture.broker.snapshot(), before);
    assert_eq!(control.budget.host_memory_bytes(), held_bytes);
    assert_eq!(control.budget.outstanding_reservations(), 1);
    assert_eq!(
        control
            .budget
            .snapshot_at(std::time::Instant::now())
            .peak_memory_bytes,
        held_bytes
    );
    assert!(fixture
        .broker
        .inner
        .sessions
        .lock()
        .unwrap()
        .iter()
        .all(|entry| entry.core.upgrade().is_none() && entry.stats.upgrade().is_none()));
    drop(padding);
    drop(held);
    let session = fixture.session(&request, &control);
    assert_eq!(control.budget.host_memory_bytes(), needed);
    drop(session);
    assert_eq!(control.budget.host_memory_bytes(), headers);
    drop_registry(&fixture);
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}

#[test]
fn original_session_native_observer_and_reused_registry_never_credit_a_fresh_budget() {
    let fixture = Fixture::new(CapabilityBrokerLimits {
        maximum_sessions: 1,
        ..Default::default()
    });
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let (headers, _, stats_payload) = amounts(&fixture, &request);
    let session = fixture.session(&request, &control);
    let observer = session.observer();
    drop(session);
    assert!(observer.is_closed() && observer.is_quiescent());
    assert_eq!(control.budget.host_memory_bytes(), headers + stats_payload);
    let (fresh_request, fresh_control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    assert!(!control.budget.is_same_instance(&fresh_control.budget));
    let fresh = fixture.session(&fresh_request, &fresh_control);
    let fresh_bytes = fresh_control.budget.host_memory_bytes();
    assert!(fresh_bytes > 0);
    assert_eq!(
        control.budget.host_memory_bytes(),
        StatsOwner::allocation_bytes().unwrap() + stats_payload
    );
    std::thread::spawn(move || drop(observer)).join().unwrap();
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
    assert_eq!(fresh_control.budget.host_memory_bytes(), fresh_bytes);
    assert!(!fresh.observer().is_closed());
    drop(fresh);
    drop_registry(&fixture);
    assert_eq!(fresh_control.budget.host_memory_bytes(), 0);
}

#[test]
fn original_session_native_real_provider_call_keeps_closed_session_backing_until_drop() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let session = fixture.session(&request, &control);
    let native_before_handle = control.budget.host_memory_bytes();
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let native_bytes = control.budget.host_memory_bytes();
    assert_eq!(
        native_bytes,
        native_before_handle + super::handle_native_memory::row_bytes()
    );
    let mut call = session
        .dispatch(handle, "read", resource(), b"input", output(), |call| call)
        .unwrap();
    let observer = session.observer();
    drop(session);
    assert!(!observer.is_quiescent());
    assert_eq!(observer.live_calls(), 1);
    assert_eq!(fixture.broker.snapshot().sessions, 1);
    assert_eq!(control.budget.host_memory_bytes(), native_bytes);
    assert_eq!(
        call.recheck_authority().unwrap_err().code,
        PlatformErrorCode::Cancelled
    );
    drop(observer);
    drop(call);
    assert_eq!(fixture.broker.snapshot().sessions, 0);
    assert_eq!(fixture.broker.snapshot().calls, 0);
    assert_eq!(fixture.broker.snapshot().handles, 0);
    assert_eq!(
        control.budget.host_memory_bytes(),
        header_bytes(BudgetProfile::Phase3)
    );
    drop_registry(&fixture);
    assert_eq!(control.budget.host_memory_bytes(), 0);
}

#[test]
fn original_session_native_real_provider_result_keeps_original_owner_after_scope_close() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let session = fixture.session(&request, &control);
    let native_before_handle = control.budget.host_memory_bytes();
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let native_bytes = control.budget.host_memory_bytes();
    assert_eq!(
        native_bytes,
        native_before_handle + super::handle_native_memory::row_bytes()
    );
    let response = session
        .dispatch(handle, "read", resource(), b"input", output(), |call| {
            call.complete(b"retained")
        })
        .unwrap()
        .unwrap();
    let observer = session.observer();
    drop(session);
    assert_eq!(response.bytes(), b"retained");
    assert_eq!(observer.retained_results(), 1);
    assert!(!observer.is_quiescent());
    assert_eq!(control.budget.host_memory_bytes(), native_bytes);
    drop(observer);
    std::thread::spawn(move || drop(response)).join().unwrap();
    assert_eq!(fixture.broker.snapshot().sessions, 0);
    assert_eq!(fixture.broker.snapshot().results, 0);
    assert_eq!(fixture.broker.snapshot().buffer_bytes, 0);
    assert_eq!(
        control.budget.host_memory_bytes(),
        header_bytes(BudgetProfile::Phase3)
    );
    drop_registry(&fixture);
    assert_eq!(control.budget.host_memory_bytes(), 0);
}

#[test]
fn original_session_native_concurrent_final_core_drops_retire_the_real_registry_weak_graph() {
    let fixture = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let session = fixture.session(&request, &control);
    let first = session.core.clone();
    let second = session.core.clone();
    let native_bytes = control.budget.host_memory_bytes();
    drop(session);
    // The two real Core owners retain the broker/plan, whose registry retains
    // both Weak headers. Its final destruction happens inside Core teardown.
    drop(fixture);
    assert_eq!(control.budget.host_memory_bytes(), native_bytes);
    let barrier = Arc::new(std::sync::Barrier::new(3));
    std::thread::scope(|scope| {
        for core in [first, second] {
            let barrier = barrier.clone();
            scope.spawn(move || {
                barrier.wait();
                drop(core);
            });
        }
        barrier.wait();
    });
    assert_eq!(control.budget.host_memory_bytes(), 0);
    assert_eq!(control.budget.outstanding_reservations(), 0);
}
