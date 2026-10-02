use super::*;

fn validate_linked_command(view: &crate::embedded::ReadView) -> Result<(), StoreError> {
    let command = view
        .get(&key(Family::Command, "command"))?
        .ok_or(StoreError::Corrupt)?;
    for family in [Family::State, Family::Outbox] {
        if view.get(&key(family, "command"))?.as_ref() != Some(&command) {
            return Err(StoreError::Corrupt);
        }
    }
    Ok(())
}

#[test]
fn coherent_cross_family_validation_holds_readiness_and_exclusive_physical_owner() {
    let (_root, mut config) = fixture();
    config.engine.maximum_read_views = 1;
    let owner = start(config.clone());
    wait(owner.apply(batch(b"linked-command")).unwrap())
        .unwrap()
        .unwrap();
    assert!(finish(&owner).clean);

    let caller = std::thread::current().id();
    let pause = Rendezvous::new(1);
    let worker = pause.clone();
    let (notice, receiver) = mpsc::channel();
    let mut startup = Box::pin(
        ProtectedStoreOwner::start_validated_view(config.clone(), 512, move |view| {
            validate_linked_command(view)?;
            let identity = view.identity();
            let (registration, mut physical) = worker.track(()).unwrap();
            physical.commit(Stage::Entered).unwrap();
            let mut parked = Box::pin(physical.pause());
            PollProbe::default().pending(parked.as_mut());
            notice
                .send((
                    identity,
                    std::thread::current().id(),
                    worker.blocked(registration, Stage::Entered).unwrap(),
                ))
                .unwrap();
            block_on(parked);
            assert_eq!(identity, view.identity());
            validate_linked_command(view)
        })
        .unwrap(),
    );
    let (identity, validator_thread, ticket) = receiver.recv_timeout(WATCHDOG).unwrap();
    assert_ne!(identity, 0);
    assert_ne!(caller, validator_thread);
    PollProbe::default().pending(startup.as_mut());
    assert!(startup.snapshot().unwrap().retained_bytes >= config.io.resident_bytes);
    assert_eq!(
        failed_start(config),
        ProtectedStoreError::Store(StoreError::Unavailable)
    );
    pause.release(ticket).unwrap();
    let reopened = wait(startup).unwrap();
    // A cap of one proves the validator's native view actually retired before Ready.
    let view = wait(reopened.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&reopened, view);
    assert_eq!(values, vec![Some(b"linked-command".to_vec()); 3]);
    drop(view);
    assert!(finish(&reopened).clean);
}

#[test]
fn incoherent_logical_links_fail_before_ready_and_preserve_every_existing_row() {
    let (_root, config) = fixture();
    let owner = start(config.clone());
    wait(owner.apply(batch(b"original-command")).unwrap())
        .unwrap()
        .unwrap();
    wait(
        owner
            .apply(AtomicBatch {
                expectations: vec![],
                mutations: vec![RowMutation {
                    key: key(Family::Outbox, "command"),
                    value: Some(b"unrelated-effect".to_vec()),
                }],
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert!(finish(&owner).clean);
    let mut denied = Box::pin(
        ProtectedStoreOwner::start_validated_view(config.clone(), 0, validate_linked_command)
            .unwrap(),
    );
    assert!(matches!(
        wait(denied.as_mut()),
        Err(ProtectedStoreError::Store(StoreError::Corrupt))
    ));
    let report = wait(
        denied
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    let reopened = start(config);
    let view = wait(reopened.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&reopened, view);
    assert_eq!(
        values,
        vec![
            Some(b"original-command".to_vec()),
            Some(b"original-command".to_vec()),
            Some(b"unrelated-effect".to_vec()),
        ]
    );
    drop(view);
    assert!(finish(&reopened).clean);
}

#[test]
fn unsupported_nonempty_logical_families_fail_readiness_without_data_reset() {
    let (_root, config) = fixture();
    let owner = start(config.clone());
    wait(owner.apply(batch(b"unknown-logical-record")).unwrap())
        .unwrap()
        .unwrap();
    assert!(finish(&owner).clean);
    assert_eq!(
        failed_start(config.clone()),
        ProtectedStoreError::Store(StoreError::UnsupportedFormat)
    );
    let reopened = start(config);
    let view = wait(reopened.open_view().unwrap()).unwrap().unwrap();
    let (view, values) = read(&reopened, view);
    assert_eq!(values, vec![Some(b"unknown-logical-record".to_vec()); 3]);
    drop(view);
    assert!(finish(&reopened).clean);
}

#[test]
fn bounded_startup_codec_validation_visits_every_row_across_page_continuations() {
    use std::sync::atomic::{AtomicUsize, Ordering};
    let (_root, config) = fixture();
    let owner = start(config.clone());
    for range in [0..256, 256..300] {
        wait(
            owner
                .apply(AtomicBatch {
                    expectations: vec![],
                    mutations: range
                        .map(|index| RowMutation {
                            key: key(Family::State, &format!("row-{index:03}")),
                            value: Some(b"encoded".to_vec()),
                        })
                        .collect(),
                })
                .unwrap(),
        )
        .unwrap()
        .unwrap();
    }
    assert!(finish(&owner).clean);
    let seen = Arc::new(AtomicUsize::new(0));
    let validator_seen = Arc::clone(&seen);
    let startup = ProtectedStoreOwner::start_validated(config.clone(), 0, move |key, value| {
        assert_eq!(key.family, Family::State);
        assert_eq!(value, b"encoded");
        validator_seen.fetch_add(1, Ordering::SeqCst);
        Ok(())
    })
    .unwrap();
    let reopened = wait(startup).unwrap();
    assert_eq!(seen.load(Ordering::SeqCst), 300);
    assert!(finish(&reopened).clean);
    let mut denied = Box::pin(
        ProtectedStoreOwner::start_validated(config, 0, |_, _| Err(StoreError::Corrupt)).unwrap(),
    );
    assert!(matches!(
        wait(denied.as_mut()),
        Err(ProtectedStoreError::Store(StoreError::Corrupt))
    ));
    let report = wait(
        denied
            .drain_async(Instant::now() + WATCHDOG, std::future::pending())
            .unwrap(),
    );
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
}
