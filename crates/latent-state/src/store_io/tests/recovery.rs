use super::*;

fn capacity() -> StoreIoRecoveryCapacity {
    StoreIoRecoveryCapacity {
        workers: 1,
        queued_jobs: 2,
        accepted_jobs: 4,
        retained_bytes: 8_000,
        job_bytes: 4_000,
    }
}

#[test]
fn reserved_read_runs_with_ordinary_writer_and_queue_saturated() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    owner.install_recovery_capacity(capacity()).unwrap();
    let rendezvous = Rendezvous::new(1);
    let pause_owner = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let write = owner
        .submit(StoreIoKind::Write, 100, move |_| {
            pause(&pause_owner, &notice, ());
        })
        .unwrap();
    let (registration, ticket) = ready(&receiver);
    let ordinary: Vec<_> = (0..6)
        .map(|_| owner.submit(StoreIoKind::Read, 100, |_| 1).unwrap())
        .collect();
    assert_eq!(
        owner
            .submit(StoreIoKind::Read, 100, |_| ())
            .err()
            .unwrap()
            .reason,
        StoreIoError::QueueFull
    );
    // This uses an existing fixed worker and a separate original byte/response
    // reservation. It does not steal the paused writer or execute its callback.
    assert_eq!(
        wait(
            owner
                .submit_recovery(StoreIoKind::Read, 100, |_| 17)
                .unwrap()
        )
        .unwrap(),
        17
    );
    assert_eq!(owner.snapshot().unwrap().active_writes, 1);
    assert_eq!(owner.recovery_snapshot().unwrap().accepted, 0);
    rendezvous.release(ticket).unwrap();
    wait(write).unwrap();
    for job in ordinary {
        assert_eq!(wait(job).unwrap(), 1);
    }
    assert!(rendezvous.require_retired(registration).is_ok());
    assert!(finish(&owner).clean);
}

#[test]
fn reserved_status_read_runs_while_ordinary_read_slots_and_queue_are_saturated() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    owner.install_recovery_capacity(capacity()).unwrap();
    let rendezvous = Rendezvous::new(1);
    let pause_owner = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let read = owner
        .submit(StoreIoKind::Read, 100, move |_| {
            pause(&pause_owner, &notice, ());
        })
        .unwrap();
    let (registration, ticket) = ready(&receiver);
    let ordinary: Vec<_> = (0..6)
        .map(|_| owner.submit(StoreIoKind::Read, 100, |_| 1).unwrap())
        .collect();
    assert_eq!(
        owner
            .submit(StoreIoKind::Read, 100, |_| ())
            .err()
            .unwrap()
            .reason,
        StoreIoError::QueueFull
    );
    assert_eq!(
        wait(
            owner
                .submit_recovery(StoreIoKind::Read, 100, |_| 23)
                .unwrap()
        )
        .unwrap(),
        23
    );
    assert_eq!(owner.snapshot().unwrap().active_reads, 1);
    rendezvous.release(ticket).unwrap();
    wait(read).unwrap();
    for job in ordinary {
        assert_eq!(wait(job).unwrap(), 1);
    }
    assert!(rendezvous.require_retired(registration).is_ok());
    assert!(finish(&owner).clean);
}

#[test]
fn lost_recovery_waiter_retains_live_work_and_bytes_until_physical_retirement() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    owner.install_recovery_capacity(capacity()).unwrap();
    let rendezvous = Rendezvous::new(1);
    let pause_owner = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .submit_recovery(StoreIoKind::Read, 1_000, move |_| {
            pause(&pause_owner, &notice, vec![0; 1000]);
        })
        .unwrap();
    let (registration, ticket) = ready(&receiver);
    let before = owner.recovery_snapshot().unwrap();
    drop(job);
    assert_eq!(owner.recovery_snapshot().unwrap(), before);
    assert_eq!(before.accepted, 1);
    assert!(before.retained_bytes >= 1_000);
    rendezvous.release(ticket).unwrap();
    assert!(finish(&owner).clean);
    assert!(rendezvous.require_retired(registration).is_ok());
    assert_eq!(owner.recovery_snapshot().unwrap().retained_bytes, 0);
}

#[test]
fn recovery_capacity_is_finite_and_cannot_be_installed_over_live_owners() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    let retained = owner.reserve_retained::<u64>(100).unwrap();
    assert_eq!(
        owner.install_recovery_capacity(capacity()),
        Err(StoreIoError::InvalidLimits)
    );
    drop(retained);
    assert!(finish(&owner).clean);
    assert_eq!(
        owner.install_recovery_capacity(capacity()),
        Err(StoreIoError::AdmissionClosed)
    );
}

#[test]
fn recovery_reconfiguration_and_oversized_jobs_fail_without_new_work() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    owner.install_recovery_capacity(capacity()).unwrap();
    owner.install_recovery_capacity(capacity()).unwrap();
    let changed = StoreIoRecoveryCapacity {
        retained_bytes: 9_000,
        ..capacity()
    };
    assert_eq!(
        owner.install_recovery_capacity(changed),
        Err(StoreIoError::InvalidLimits)
    );
    assert_eq!(
        owner
            .submit_recovery(StoreIoKind::Read, 4_000, |_| ())
            .err()
            .unwrap()
            .reason,
        StoreIoError::JobTooLarge
    );
    assert_eq!(owner.recovery_snapshot().unwrap().accepted, 0);
    assert_eq!(owner.snapshot().unwrap().retained_bytes, 0);
    assert!(finish(&owner).clean);
}
