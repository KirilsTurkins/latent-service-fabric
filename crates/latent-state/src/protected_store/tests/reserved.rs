use super::*;
use crate::store_io::StoreIoKind;

#[test]
fn reserved_native_status_progresses_while_all_ordinary_workers_and_queue_are_full() {
    let (_root, mut config) = fixture();
    config.io.queued_jobs = 1;
    let owner = start(config);
    wait(owner.apply(batch(b"durable-before-pressure")).unwrap())
        .unwrap()
        .unwrap();
    let rendezvous = Rendezvous::new(3);
    let (notice, receiver) = mpsc::channel();
    let mut jobs = Vec::new();
    let mut tickets = Vec::new();
    for kind in [StoreIoKind::Read, StoreIoKind::Read, StoreIoKind::Write] {
        let worker = rendezvous.clone();
        let notice = notice.clone();
        jobs.push(
            owner
                .with_store(kind, 512, move |_engine| {
                    let (registration, mut retained) = worker.track(vec![0_u8; 512]).unwrap();
                    retained.commit(Stage::Entered).unwrap();
                    let mut pause = Box::pin(retained.pause());
                    PollProbe::default().pending(pause.as_mut());
                    notice
                        .send(worker.blocked(registration, Stage::Entered).unwrap())
                        .unwrap();
                    block_on(pause);
                    Ok(())
                })
                .unwrap(),
        );
        tickets.push(receiver.recv_timeout(WATCHDOG).unwrap());
    }
    let queued = owner.with_store(StoreIoKind::Write, 0, |_| Ok(())).unwrap();
    assert!(matches!(
        owner.with_store(StoreIoKind::Read, 0, |_| Ok(())),
        Err(ProtectedStoreError::Io(StoreIoError::QueueFull))
    ));
    let status = owner
        .with_store(StoreIoKind::RecoveryRead, 4_096, |engine| {
            engine.snapshot()?.get(&key(Family::State, "command"))
        })
        .unwrap();
    assert_eq!(
        wait(status).unwrap().unwrap().as_deref(),
        Some(b"durable-before-pressure".as_slice())
    );
    assert_eq!(owner.snapshot().unwrap().active_reads, 2);
    assert_eq!(owner.snapshot().unwrap().active_writes, 1);
    assert_eq!(owner.snapshot().unwrap().recovery_accepted, 0);
    for ticket in tickets {
        rendezvous.release(ticket).unwrap();
    }
    for job in jobs {
        wait(job).unwrap().unwrap();
    }
    wait(queued).unwrap().unwrap();
    assert!(finish(&owner).clean);
    owner.reap_retired_threads().unwrap();
}

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
    let (_root, mut config) = fixture();
    config.io.workers = 3;
    config.io.active_reads = 1;
    config.io.queued_jobs = 6;
    config.io.recovery = Some(crate::store_io::StoreIoRecoveryCapacity {
        workers: 1,
        queued_jobs: 2,
        accepted_jobs: 4,
        retained_bytes: 8 * 1024 * 1024,
        job_bytes: 4 * 1024 * 1024,
    });
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
