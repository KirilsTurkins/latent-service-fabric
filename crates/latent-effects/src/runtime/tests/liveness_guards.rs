use super::*;

async fn retire_original(fixture: Fixture, mut owner: DispatcherOwner, deadline: Instant) -> bool {
    let dispatcher = owner.shutdown(deadline).await.unwrap();
    drop(owner);
    fixture.store.close();
    let store = fixture
        .store
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    if store.snapshot.physically_retired() {
        fixture.store.reap_retired_threads().unwrap();
    }
    fixture.capacity.close();
    let capacity = fixture
        .capacity
        .drain_async(deadline, tokio::time::sleep_until(deadline.into()))
        .unwrap()
        .await;
    dispatcher.physically_retired
        && dispatcher.scheduling_owner_retired
        && dispatcher.worker_threads_remaining == 0
        && store.snapshot.physically_retired()
        && capacity.snapshot.physically_retired()
}

#[tokio::test]
async fn unchanged_command_floor_rejects_rewound_time_before_any_writer_callback() {
    let deadline = Instant::now() + WATCHDOG;
    let fixture = Fixture::new().await;
    let owner = fixture.start(config(), vec![], None).await.unwrap();
    let source = owner.command_admission_source();
    let original = source.capture().unwrap();
    fixture.clock.millis.store(101, Ordering::SeqCst);
    let advanced = source.command_time().unwrap();
    fixture.clock.millis.store(100, Ordering::SeqCst);
    let entered = AtomicUsize::new(0);
    let time = source.command_time();
    let captured = source.capture();
    let current = original.with_current(|_, _| entered.fetch_add(1, Ordering::SeqCst));
    let floor = owner.snapshot().unwrap().command_clock_floor;
    let denied = |result| {
        matches!(
            result,
            Err(DispatcherError::Authority(
                AuthorityError::ClockDiscontinuity
            ))
        )
    };
    let time_denied = denied(time.map(|_| ()));
    let capture_denied = denied(captured.map(|guard| guard.retire()));
    let current_denied = denied(current.map(|_| ()));
    fixture.clock.millis.store(101, Ordering::SeqCst);
    original.retire();
    drop(source);
    let retired = retire_original(fixture, owner, deadline).await;
    assert!(retired);
    assert_eq!(advanced.unix_millis, 101);
    assert_eq!(floor, 101);
    assert!(time_denied && capture_denied && current_denied);
    assert_eq!(entered.load(Ordering::SeqCst), 0);
}

#[tokio::test]
async fn unchanged_original_role_rejects_an_inconsistent_owner_epoch_without_callback() {
    let deadline = Instant::now() + WATCHDOG;
    let fixture = Fixture::new().await;
    let owner = fixture.start(config(), vec![], None).await.unwrap();
    let source = owner.command_admission_source();
    let original = source.capture().unwrap();
    let saved = owner
        .services
        .shared
        .state
        .lock()
        .unwrap()
        .control_generation;
    owner
        .services
        .shared
        .state
        .lock()
        .unwrap()
        .control_generation =
        DispatcherControlGeneration::new(saved.owner_epoch() + 1, saved.revision()).unwrap();
    let entered = AtomicUsize::new(0);
    let time_denied = source.command_time().is_err();
    let capture_denied = source.capture().is_err();
    let current_denied = original
        .with_current(|_, _| entered.fetch_add(1, Ordering::SeqCst))
        .is_err();
    owner
        .services
        .shared
        .state
        .lock()
        .unwrap()
        .control_generation = saved;
    original.retire();
    drop(source);
    let retired = retire_original(fixture, owner, deadline).await;
    assert!(retired);
    assert!(time_denied && capture_denied && current_denied);
    assert_eq!(entered.load(Ordering::SeqCst), 0);
}
