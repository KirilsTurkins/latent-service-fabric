use super::*;

#[test]
fn original_operator_policy_fence_is_inside_the_same_role_order_as_effect_management() {
    let fixture = Fixture::new(false, false);
    let request = fixture.request("ordered-operator", DispatcherControlAction::Pause);
    let prepared = fixture.prepare(request.clone());
    let policy = std::sync::Mutex::new(());
    let outcome = execute_guarded(
        &fixture.store,
        &prepared,
        |accept| {
            assert!(matches!(
                fixture.shared.state.try_lock(),
                Err(std::sync::TryLockError::WouldBlock)
            ));
            let _current_operator = policy.lock().unwrap();
            accept()
        },
        |accept| {
            assert!(matches!(
                policy.try_lock(),
                Err(std::sync::TryLockError::WouldBlock)
            ));
            assert!(matches!(
                fixture.shared.state.try_lock(),
                Err(std::sync::TryLockError::WouldBlock)
            ));
            accept()
        },
    )
    .unwrap();
    assert!(outcome.published && outcome.paused);
    assert_eq!(
        ControlCatalog::lookup(&fixture.store.snapshot().unwrap(), &request).unwrap(),
        Some(outcome.receipt)
    );
    assert!(policy.try_lock().is_ok() && fixture.shared.state.try_lock().is_ok());
}

struct CheckedClock {
    shared: Arc<Shared>,
    original: Arc<Clock>,
    calls: AtomicU64,
}
impl EffectTimeSource for CheckedClock {
    fn observe(&self) -> EffectTime {
        assert!(self.shared.state.try_lock().is_ok());
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.original.observe()
    }
}

#[test]
fn protected_clock_observation_never_enters_locked_control_acceptance_or_publication() {
    let fixture = Fixture::new(false, false);
    let request = fixture.request("clock-outside-role", DispatcherControlAction::Pause);
    let clock = Arc::new(CheckedClock {
        shared: Arc::clone(&fixture.shared),
        original: Arc::clone(&fixture.time),
        calls: AtomicU64::new(0),
    });
    let mut prepared = fixture.prepare(request.clone());
    prepared.time = clock.clone();
    let outcome = execute(&fixture.store, &prepared, |accept| accept()).unwrap();
    assert!(outcome.published && outcome.paused);
    assert_eq!(clock.calls.load(Ordering::SeqCst), 3);
    assert_eq!(
        ControlCatalog::lookup(&fixture.store.snapshot().unwrap(), &request).unwrap(),
        Some(outcome.receipt)
    );
}
