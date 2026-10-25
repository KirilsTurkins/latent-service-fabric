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

#[test]
#[expect(
    clippy::too_many_lines,
    reason = "one original descendant ledger exercises actual post-Store registry retirement and its refusal fences"
)]
fn post_store_registry_retirement_releases_original_child_capacity_without_a_new_session() {
    use latent_core::{
        ActivationBudget, BudgetCancellationProbe, ChildBudgetOwner, ClockSample, DelegationLimits,
        EffectiveActivationBudget,
    };
    use latent_executor::{ExecutionCleanup, ExecutionRequest, GuestOutcome};
    use std::sync::{atomic::AtomicBool, Mutex};
    use std::task::{Poll, Waker};

    #[derive(Default)]
    struct Signal {
        closed: AtomicBool,
        waiter: Mutex<Option<Waker>>,
    }
    impl BudgetCancellationProbe for Signal {
        fn is_cancelled(&self) -> bool {
            self.closed.load(Ordering::Acquire)
        }
        fn cancelled(&self) -> latent_core::BoxFuture<'_, ()> {
            Box::pin(std::future::poll_fn(|context| {
                let mut waiter = self.waiter.lock().unwrap();
                if self.closed.load(Ordering::Acquire) {
                    Poll::Ready(())
                } else {
                    *waiter = Some(context.waker().clone());
                    Poll::Pending
                }
            }))
        }
        fn mark_terminal(&self) {
            self.closed.store(true, Ordering::Release);
            let waiter = self.waiter.lock().unwrap().take();
            if let Some(waiter) = waiter {
                waiter.wake();
            }
        }
    }
    fn selected_child(
        fixture: &Fixture,
    ) -> (
        ActivationBudget,
        ExecutionRequest,
        Control,
        ChildBudgetOwner,
    ) {
        let (mut request, mut control) = fixture.request("registry-child");
        let mut ceiling = request.budget.clone();
        ceiling.cpu_fuel *= 4;
        ceiling.memory_bytes *= 4;
        ceiling.child_calls = 4;
        let sample = ClockSample::system_now();
        let grant = EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &ceiling,
            &ceiling,
            &ceiling,
            None,
            sample,
        )
        .unwrap();
        let parent = ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap();
        parent
            .enable_descendants(
                DelegationLimits {
                    maximum_depth: 2,
                    maximum_live_children: 1,
                    maximum_live_descendants: 2,
                },
                Arc::new(Signal::default()),
            )
            .unwrap();
        let delegation = parent
            .delegate_at(&request.budget, &request.budget, &ceiling, None, sample)
            .unwrap();
        let grant = delegation.grant();
        let child = delegation
            .accept(&grant, Arc::new(Signal::default()), sample.monotonic())
            .unwrap();
        control.budget = child.accounting().clone();
        request.activation.deadline_unix_millis = control.budget.deadline().unix_millis();
        (parent, request, control, child)
    }
    fn report(observer: &CapabilitySessionObserver, reusable: bool) {
        let original: Result<GuestOutcome, PlatformError> = Err(denied());
        let report = observer.after_store_dropped(original.clone());
        assert_eq!(report.outcome, original);
        assert_eq!(
            matches!(report.cleanup, ExecutionCleanup::Reusable),
            reusable
        );
    }
    let fixture = Fixture::new(CapabilityBrokerLimits {
        maximum_sessions: 1,
        ..Default::default()
    });

    // A closed scalar snapshot alone does not prove the actual Core has died.
    let (parent, request, control, child) = selected_child(&fixture);
    let session = fixture.session(&request, &control);
    let stats = session.core.stats.clone();
    let still_owned_core = session.core.clone();
    let observer = session.observer();
    drop(session);
    assert!(observer.is_quiescent());
    report(&observer, false);
    assert!(fixture.broker.inner.sessions.lock().unwrap()[0]
        .stats
        .ptr_eq_shared(&stats));
    drop(still_owned_core);
    assert!(child
        .finish(None, std::time::Instant::now())
        .violation()
        .is_none());
    drop(control);
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 1);
    // The old implementation returns Reusable but leaves both paid Weak headers.
    assert!(parent
        .delegate_at(
            &request.budget,
            &request.budget,
            parent.granted(),
            None,
            ClockSample::system_now()
        )
        .is_err());
    {
        let _busy = fixture.broker.inner.sessions.lock().unwrap();
        report(&observer, false);
    }
    report(&observer, true);
    assert!(fixture.broker.inner.sessions.lock().unwrap()[0]
        .stats
        .upgrade()
        .is_none());
    // An actual observer/Stats owner still owns its backing after registry removal.
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 1);
    report(&observer, true);
    drop(observer);
    drop(stats);
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 0);
    assert_eq!(
        parent.descendant_snapshot().unwrap().reserved_memory_bytes,
        0
    );
    let next = parent
        .delegate_at(
            &request.budget,
            &request.budget,
            parent.granted(),
            None,
            ClockSample::system_now(),
        )
        .unwrap();
    drop(next);
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 0);

    // Real detached work/results keep registry diagnostics and original charge.
    let (parent, request, control, child) = selected_child(&fixture);
    let session = fixture.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let call = session
        .dispatch(handle, "read", resource(), b"input", output(), |call| call)
        .unwrap();
    let observer = session.observer();
    drop(session);
    report(&observer, false);
    assert_eq!(
        fixture
            .broker
            .inspect_tenant_usage(&request.activation.target.tenant)
            .unwrap()
            .calls,
        1
    );
    drop(call);
    report(&observer, true);
    drop(observer);
    assert!(child
        .finish(None, std::time::Instant::now())
        .violation()
        .is_none());
    drop(control);
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 0);

    let (parent, request, control, child) = selected_child(&fixture);
    let session = fixture.session(&request, &control);
    let handle = session.bind(CAP, "read", resource()).unwrap();
    let response = session
        .dispatch(handle, "read", resource(), b"input", output(), |call| {
            call.complete(b"retained")
        })
        .unwrap()
        .unwrap();
    let observer = session.observer();
    drop(session);
    report(&observer, false);
    let usage = fixture
        .broker
        .inspect_tenant_usage(&request.activation.target.tenant)
        .unwrap();
    assert_eq!(
        (usage.results, usage.retired_sessions_with_resources),
        (1, 1)
    );
    assert_eq!(response.bytes(), b"retained");
    drop(response);
    report(&observer, true);
    drop(observer);
    assert!(child
        .finish(None, std::time::Instant::now())
        .violation()
        .is_none());
    drop(control);
    assert_eq!(parent.descendant_snapshot().unwrap().live_children, 0);

    // Slot reuse cannot let an old observer remove another original session.
    let (old_request, old_control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let old = fixture.session(&old_request, &old_control);
    let observer = old.observer();
    drop(old);
    let (fresh_request, fresh_control) =
        super::resource_table_memory::selected(&fixture, BudgetProfile::Phase3);
    let fresh = fixture.session(&fresh_request, &fresh_control);
    let fresh_bytes = fresh_control.budget.host_memory_bytes();
    report(&observer, true);
    assert!(fixture.broker.inner.sessions.lock().unwrap()[0]
        .stats
        .ptr_eq_shared(&fresh.core.stats));
    assert_eq!(fresh_control.budget.host_memory_bytes(), fresh_bytes);
    assert!(!fresh.observer().is_closed());
    drop(observer);
    assert_eq!(old_control.budget.host_memory_bytes(), 0);
    let fresh_observer = fresh.observer();
    drop(fresh);
    report(&fresh_observer, true);
    drop(fresh_observer);
    assert_eq!(fresh_control.budget.host_memory_bytes(), 0);

    // An unavailable original broker cannot supply a new retirement proof.
    let isolated = Fixture::new(CapabilityBrokerLimits::default());
    let (request, control) =
        super::resource_table_memory::selected(&isolated, BudgetProfile::Phase3);
    let session = isolated.session(&request, &control);
    let observer = session.observer();
    drop(session);
    drop(isolated);
    assert!(observer.is_quiescent());
    report(&observer, false);
    drop(observer);
    assert_eq!(control.budget.host_memory_bytes(), 0);
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
    assert_eq!(control.budget.host_memory_bytes(), native_bytes + 5 + 64);
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
    assert_eq!(control.budget.host_memory_bytes(), native_bytes + 8 + 64);
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
