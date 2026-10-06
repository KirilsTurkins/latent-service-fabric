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
