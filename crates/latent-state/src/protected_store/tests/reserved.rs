use super::*;
use latent_core::test_support::coordination::{PauseTicket, Registration};

fn park<T>(rendezvous: &Rendezvous, notice: &mpsc::Sender<(Registration, PauseTicket)>, owned: T) {
    let (registration, mut physical) = rendezvous.track(owned).unwrap();
    physical.commit(Stage::Entered).unwrap();
    let mut paused = Box::pin(physical.pause());
    PollProbe::default().pending(paused.as_mut());
    notice
        .send((
            registration,
            rendezvous.blocked(registration, Stage::Entered).unwrap(),
        ))
        .unwrap();
    block_on(paused);
}

#[test]
fn protected_recovery_reads_use_reserved_worker_while_native_writer_reader_and_queue_are_full() {
    let (_root, config) = fixture();
    let owner = start(config);
    owner
        .install_recovery_capacity(crate::store_io::StoreIoRecoveryCapacity {
            workers: 1,
            queued_jobs: 2,
            accepted_jobs: 4,
            retained_bytes: 8 * 1024 * 1024,
            job_bytes: 4 * 1024 * 1024,
        })
        .unwrap();
    wait(owner.apply(batch(b"original")).unwrap())
        .unwrap()
        .unwrap();
    let rendezvous = Rendezvous::new(2);
    let writer_pause = rendezvous.clone();
    let (writer_notice, writer_ready) = mpsc::channel();
    let writer = owner
        .with_store(StoreIoKind::Write, 4096, move |engine| {
            engine
                .apply_fenced(batch(b"committed"), || {
                    // The real engine writer remains physically owned and abortable.
                    park(&writer_pause, &writer_notice, ());
                    Ok::<(), std::convert::Infallible>(())
                })
                .map_err(|error| match error {
                    crate::embedded::FencedStoreError::Store(error) => error,
                    crate::embedded::FencedStoreError::Fence(impossible) => match impossible {},
                })
        })
        .unwrap();
    let (writer_registration, writer_ticket) = writer_ready.recv_timeout(WATCHDOG).unwrap();
    let reader_pause = rendezvous.clone();
    let (reader_notice, reader_ready) = mpsc::channel();
    let reader = owner
        .with_store(StoreIoKind::Read, 4096, move |engine| {
            let view = engine.snapshot()?;
            assert_eq!(
                view.get(&key(Family::State, "command"))?,
                Some(b"original".to_vec())
            );
            park(&reader_pause, &reader_notice, view);
            Ok(())
        })
        .unwrap();
    let (reader_registration, reader_ticket) = reader_ready.recv_timeout(WATCHDOG).unwrap();
    let queued: Vec<_> = (0..6)
        .map(|_| {
            owner
                .with_store(StoreIoKind::Read, 4096, |engine| {
                    engine.snapshot()?.get(&key(Family::State, "command"))
                })
                .unwrap()
        })
        .collect();
    assert!(matches!(
        owner.with_store(StoreIoKind::Read, 4096, |_| Ok(())),
        Err(ProtectedStoreError::Io(StoreIoError::QueueFull))
    ));
    let status = wait(
        owner
            .with_recovery_store(StoreIoKind::Read, 4096, |engine| {
                engine.snapshot()?.get(&key(Family::State, "command"))
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(status, Some(b"original".to_vec()));
    let active = owner.snapshot().unwrap();
    assert_eq!((active.active_writes, active.active_reads), (1, 1));
    rendezvous.release(writer_ticket).unwrap();
    rendezvous.release(reader_ticket).unwrap();
    wait(writer).unwrap().unwrap();
    wait(reader).unwrap().unwrap();
    for job in queued {
        wait(job).unwrap().unwrap();
    }
    assert!(rendezvous.require_retired(writer_registration).is_ok());
    assert!(rendezvous.require_retired(reader_registration).is_ok());
    let final_state = wait(
        owner
            .with_recovery_store(StoreIoKind::Read, 4096, |engine| {
                engine.snapshot()?.get(&key(Family::State, "command"))
            })
            .unwrap(),
    )
    .unwrap()
    .unwrap();
    assert_eq!(final_state, Some(b"committed".to_vec()));
    assert!(finish(&owner).clean);
}
