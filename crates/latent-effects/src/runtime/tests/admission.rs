use super::*;

#[tokio::test]
async fn zero_adapter_commands_use_actual_epoch_bounded_owners_and_nonrewinding_clock() {
    let fixture = Fixture::new().await;
    let mut limits = config();
    limits.maximum_command_owners = 2;
    let mut owner = fixture.start(limits, vec![], None).await.unwrap();
    let source = owner.command_admission_source();
    let clone = source.clone();
    assert!(source.uses_store(&fixture.store));
    assert!(source.uses_store(&fixture.store.as_ref().clone()));
    let foreign = Fixture::new().await;
    assert!(!source.uses_store(&foreign.store));
    foreign.finish().await;
    assert!(source.uses_effect_authority(&fixture.authority));
    assert!(source.uses_effect_authority(&clone.effect_authority()));
    assert!(!source.uses_effect_authority(&EffectAuthorityOwner::new(128, 16, 100).unwrap()));
    assert_eq!(clone.command_time().unwrap().unix_millis, 100);
    let first = source.capture().unwrap();
    let second = clone.capture().unwrap();
    assert_eq!(first.owner_epoch(), 1);
    assert_eq!(first.captured_time().unix_millis, 100);
    assert!(matches!(
        owner.command_admission(),
        Err(DispatcherError::Authority(AuthorityError::Capacity))
    ));
    assert_eq!(owner.command_owner_epoch().unwrap(), 1);
    assert_eq!(owner.snapshot().unwrap().command_owners, 2);
    first.retire();
    let third = owner.command_admission().unwrap();
    fixture.clock.millis.store(101, Ordering::SeqCst);
    assert_eq!(
        second
            .with_current(|epoch, time| (epoch, time.unix_millis))
            .unwrap(),
        (1, 101)
    );
    fixture.clock.millis.store(100, Ordering::SeqCst);
    assert!(matches!(
        third.with_current(|_, _| panic!("rewound clock accepted")),
        Err(DispatcherError::Authority(
            AuthorityError::ClockDiscontinuity
        ))
    ));
    fixture.clock.millis.store(101, Ordering::SeqCst);
    fixture.clock.continuous.store(false, Ordering::SeqCst);
    assert!(owner.command_time().is_err());
    assert!(source.command_time().is_err());
    assert_eq!(owner.snapshot().unwrap().command_owners, 2);
    fixture.clock.continuous.store(true, Ordering::SeqCst);
    second.retire();
    third.retire();
    let report = owner.shutdown(Instant::now() + WATCHDOG).await.unwrap();
    assert!(report.clean, "{report:?}");
    fixture.finish().await;
    assert!(source.capture().is_err());
    assert!(clone.capture().is_err());
    assert!(clone.command_time().is_err());
}

#[tokio::test]
async fn command_role_generation_restore_review_and_close_reject_final_writer_callback() {
    let fixture = Fixture::new().await;
    let mut owner = fixture.start(config(), vec![], None).await.unwrap();
    let old = owner.command_admission().unwrap();
    owner.pause();
    assert!(matches!(
        old.with_current(|_, _| panic!("stale generation accepted")),
        Err(DispatcherError::AdmissionClosed)
    ));
    // A deliberate effect pause does not invent a general command prohibition.
    let paused = owner.command_admission().unwrap();
    paused.with_current(|_, _| ()).unwrap();
    owner.require_restore_review().unwrap();
    assert!(owner.command_admission().is_err());
    assert!(paused
        .with_current(|_, _| panic!("restore review accepted"))
        .is_err());
    old.retire();
    paused.retire();
    owner.close();
    assert!(owner.command_owner_epoch().is_err());
    let report = owner.shutdown(Instant::now() + WATCHDOG).await.unwrap();
    assert!(report.clean, "{report:?}");
    fixture.finish().await;
}

#[tokio::test]
async fn original_command_guard_prevents_new_node_epoch_until_positive_retirement() {
    let fixture = Fixture::new().await;
    let mut owner = fixture.start(config(), vec![], None).await.unwrap();
    let command = owner.command_admission().unwrap();
    let report = owner.shutdown(Instant::now()).await.unwrap();
    assert!(!report.clean && !report.physically_retired);
    assert_eq!(report.snapshot.command_owners, 1);
    assert!(!report.scheduling_owner_retired);
    assert!(matches!(
        fixture.start(config(), vec![], Some((1, 100))).await,
        Err(DispatcherError::ProtectedStore(ProtectedStoreError::Store(
            latent_state::embedded::StoreError::Conflict
        )))
    ));
    assert!(command
        .with_current(|_, _| panic!("closed command accepted"))
        .is_err());
    command.retire();
    let late = owner.shutdown(Instant::now() + WATCHDOG).await.unwrap();
    assert!(!late.clean, "the original cutoff remains sticky");
    assert!(late.physically_retired, "{late:?}");
    let mut replacement = fixture
        .start(config(), vec![], Some((1, 100)))
        .await
        .unwrap();
    assert_eq!(replacement.command_owner_epoch().unwrap(), 2);
    assert!(
        replacement
            .shutdown(Instant::now() + WATCHDOG)
            .await
            .unwrap()
            .clean
    );
    fixture.finish().await;
}

#[tokio::test]
async fn detached_command_writer_keeps_role_until_actual_fence_rejection_and_buffer_drop() {
    use latent_state::embedded::{Family, FencedStoreError, RowKey, StoreError};
    let fixture = Fixture::new().await;
    let mut owner = fixture.start(config(), vec![], None).await.unwrap();
    let command = owner.command_admission().unwrap();
    let gates = Rendezvous::new(1);
    let worker_gates = gates.clone();
    let (entered, receiver) = tokio::sync::oneshot::channel();
    let runtime = tokio::runtime::Handle::current();
    let rejected = Arc::new(AtomicBool::new(false));
    let observed = Arc::clone(&rejected);
    let key = RowKey {
        family: Family::State,
        key: b"command-role-test".to_vec(),
    };
    let write_key = key.clone();
    let job = fixture
        .store
        .with_store(StoreIoKind::Write, 1024 * 1024, move |store| {
            let (registration, mut retained) = worker_gates.track(vec![0_u8; 1024]).unwrap();
            retained.commit(Stage::Entered).unwrap();
            runtime.block_on(async {
                let mut pause = Box::pin(retained.pause());
                PollProbe::default().pending(pause.as_mut());
                entered
                    .send(worker_gates.blocked(registration, Stage::Entered).unwrap())
                    .unwrap();
                pause.await;
            });
            let result = store.apply_fenced(
                AtomicBatch {
                    expectations: vec![],
                    mutations: vec![RowMutation {
                        key: write_key,
                        value: Some(b"forbidden".to_vec()),
                    }],
                },
                || command.with_current(|_, _| ()),
            );
            observed.store(
                matches!(
                    result,
                    Err(FencedStoreError::Fence(DispatcherError::AdmissionClosed))
                ),
                Ordering::SeqCst,
            );
            drop(retained); // Original input buffer actually retires before the role guard.
            command.retire();
            Ok::<_, StoreError>(())
        })
        .unwrap();
    let ticket = with_watchdog(WATCHDOG, receiver).await.unwrap();
    drop(job); // The accepted worker, guard and buffers retain their original owner.
    owner.close();
    assert_eq!(owner.snapshot().unwrap().command_owners, 1);
    assert!(matches!(
        fixture.start(config(), vec![], Some((1, 100))).await,
        Err(DispatcherError::ProtectedStore(ProtectedStoreError::Store(
            StoreError::Conflict
        )))
    ));
    gates.release(ticket).unwrap();
    let report = owner.shutdown(Instant::now() + WATCHDOG).await.unwrap();
    assert!(report.clean, "{report:?}");
    assert!(rejected.load(Ordering::SeqCst));
    let absent = fixture
        .store
        .with_store(StoreIoKind::Read, 1024, move |store| {
            store.snapshot()?.get(&key)
        })
        .unwrap()
        .await
        .unwrap()
        .unwrap();
    assert!(absent.is_none());
    fixture.finish().await;
}
