use super::*;

#[test]
fn dropped_result_waiter_retains_paused_io_bytes_and_permit() {
    let (store, writes, closed) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let buffer = Arc::new(vec![8_u8; 32]);
    let weak = Arc::downgrade(&buffer);
    let job = owner
        .submit(StoreIoKind::Write, 32, move |store| {
            pause(&worker, &notice, buffer);
            store.writes.fetch_add(1, Ordering::SeqCst);
        })
        .unwrap();
    let (registration, ticket) = ready(&receiver);
    let charge = owner.snapshot().unwrap().retained_bytes;
    assert_eq!(owner.snapshot().unwrap().active_writes, 1);
    drop(job);
    assert!(weak.upgrade().is_some());
    assert_eq!(owner.snapshot().unwrap().accepted, 1);
    assert_eq!(owner.snapshot().unwrap().retained_bytes, charge);
    assert_eq!(writes.load(Ordering::SeqCst), 0);
    assert!(!closed.load(Ordering::SeqCst));
    rendezvous.release(ticket).unwrap();
    let report = finish(&owner);
    assert!(report.clean);
    rendezvous.require_retired(registration).unwrap();
    assert!(weak.upgrade().is_none());
    assert_eq!(writes.load(Ordering::SeqCst), 1);
    assert_eq!(report.snapshot.accepted, 0);
    assert_eq!(report.snapshot.retained_bytes, 0);
    assert!(closed.load(Ordering::SeqCst));
}

#[test]
fn detached_queued_write_still_executes_once_after_active_owner() {
    let (store, writes, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let first = owner
        .submit(StoreIoKind::Write, 32, move |store| {
            pause(&worker, &notice, vec![7_u8; 32]);
            store.writes.fetch_add(1, Ordering::SeqCst);
        })
        .unwrap();
    let (_, ticket) = ready(&receiver);
    let buffer = Arc::new(vec![3_u8; 32]);
    let weak = Arc::downgrade(&buffer);
    let queued = owner
        .submit(StoreIoKind::Write, 32, move |store| {
            assert_eq!(buffer.len(), 32);
            store.writes.fetch_add(1, Ordering::SeqCst);
        })
        .unwrap();
    drop(queued);
    assert_eq!(owner.snapshot().unwrap().queued, 1);
    assert_eq!(owner.snapshot().unwrap().accepted, 2);
    assert!(weak.upgrade().is_some());
    rendezvous.release(ticket).unwrap();
    wait(first).unwrap();
    assert!(finish(&owner).clean);
    assert_eq!(writes.load(Ordering::SeqCst), 2);
    assert!(weak.upgrade().is_none());
    assert_eq!(owner.snapshot().unwrap().retained_bytes, 0);
}

#[test]
fn blocked_writer_backlog_does_not_stall_independent_reads() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let first = owner
        .submit(StoreIoKind::Write, 32, move |_| {
            pause(&worker, &notice, vec![0_u8; 32]);
        })
        .unwrap();
    let (_, ticket) = ready(&receiver);
    let queued = owner.submit(StoreIoKind::Write, 0, |_| 10).unwrap();
    let read = owner
        .submit(StoreIoKind::Read, 0, |_| {
            std::thread::current().name().unwrap().to_owned()
        })
        .unwrap();
    assert!(wait(read).unwrap().starts_with("latent-store-io-"));
    assert_eq!(owner.snapshot().unwrap().queued, 1);
    assert_eq!(owner.snapshot().unwrap().active_writes, 1);
    rendezvous.release(ticket).unwrap();
    wait(first).unwrap();
    assert_eq!(wait(queued).unwrap(), 10);
    assert!(finish(&owner).clean);
}

#[test]
fn queue_accepted_and_retained_byte_limits_reject_before_submission() {
    for kind in [
        StoreIoError::QueueFull,
        StoreIoError::AcceptedFull,
        StoreIoError::ByteBudget,
    ] {
        let (store, _, _) = store();
        let mut config = limits();
        match kind {
            StoreIoError::QueueFull => config.queued_jobs = 1,
            StoreIoError::AcceptedFull => {
                config.accepted_jobs = 2;
                config.queued_jobs = 2;
            }
            StoreIoError::ByteBudget => {
                config.retained_bytes = 1_200;
                config.job_bytes = 1_200;
            }
            _ => unreachable!(),
        }
        let owner = StoreIoOwner::new(store, config, |_| Ok(())).unwrap();
        let rendezvous = Rendezvous::new(1);
        let worker = rendezvous.clone();
        let (notice, receiver) = mpsc::channel();
        let first = owner
            .submit(StoreIoKind::Write, 32, move |_| {
                pause(&worker, &notice, vec![0_u8; 32]);
            })
            .unwrap();
        let (_, ticket) = ready(&receiver);
        let queued = owner.submit(StoreIoKind::Write, 0, |_| ()).unwrap();
        let bytes = if kind == StoreIoError::ByteBudget {
            1100
        } else {
            0
        };
        let failure = owner
            .submit(StoreIoKind::Write, bytes, |_| {
                panic!("rejected operation executed")
            })
            .err()
            .unwrap();
        assert_eq!(failure.reason, kind);
        assert_eq!(owner.snapshot().unwrap().accepted, 2);
        assert_eq!(owner.snapshot().unwrap().queued, 1);
        rendezvous.release(ticket).unwrap();
        wait(first).unwrap();
        wait(queued).unwrap();
        assert!(finish(&owner).clean);
    }
}

#[test]
fn response_buffer_destruction_precedes_detached_reservation_refund() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .submit(StoreIoKind::Read, 64, move |_| {
            let result = Arc::new(vec![2_u8; 64]);
            notice.send(Arc::downgrade(&result)).unwrap();
            result
        })
        .unwrap();
    let weak = receiver.recv_timeout(WATCHDOG).unwrap();
    assert!(weak.upgrade().is_some());
    assert_eq!(owner.snapshot().unwrap().accepted, 1);
    drop(job);
    let report = finish(&owner);
    assert!(report.clean);
    assert_eq!(report.snapshot.accepted, 0);
    assert_eq!(report.snapshot.retained_bytes, 0);
    assert!(weak.upgrade().is_none());
}

#[test]
fn worker_panic_is_recovery_required_and_gates_queued_writes() {
    let (store, writes, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let first = owner
        .submit(StoreIoKind::Write, 32, move |_| {
            pause(&worker, &notice, vec![0_u8; 32]);
            panic!("engine completion is uncertain");
        })
        .unwrap();
    let (_, ticket) = ready(&receiver);
    let second = owner
        .submit(StoreIoKind::Write, 0, |store| {
            store.writes.fetch_add(1, Ordering::SeqCst)
        })
        .unwrap();
    rendezvous.release(ticket).unwrap();
    assert_eq!(wait(first), Err(StoreIoError::RecoveryRequired));
    assert_eq!(wait(second), Err(StoreIoError::NotStarted));
    assert_eq!(
        owner
            .submit(StoreIoKind::Read, 0, |_| ())
            .err()
            .unwrap()
            .reason,
        StoreIoError::AdmissionClosed
    );
    let report = finish(&owner);
    assert!(!report.clean);
    assert!(report.snapshot.quarantined);
    assert_eq!(writes.load(Ordering::SeqCst), 0);
    assert_eq!(report.snapshot.accepted, 0);
    assert!(report.snapshot.physically_retired());
}
