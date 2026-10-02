use super::*;

fn recovery_limits() -> StoreIoLimits {
    let mut config = limits();
    config.workers = 3;
    config.active_reads = 1;
    config.recovery = Some(StoreIoRecoveryLimits {
        workers: 1,
        queued_jobs: 2,
        accepted_jobs: 4,
        retained_bytes: 4_000,
        job_bytes: 2_000,
    });
    config
}

#[test]
fn recovery_worker_and_admission_progress_with_all_ordinary_workers_and_quotas_full() {
    for pressure in [
        StoreIoError::QueueFull,
        StoreIoError::AcceptedFull,
        StoreIoError::ByteBudget,
    ] {
        let (store, _, _) = store();
        let mut config = recovery_limits();
        match pressure {
            StoreIoError::QueueFull => config.queued_jobs = 1,
            StoreIoError::AcceptedFull => {
                config.accepted_jobs = 2;
                config.queued_jobs = 2;
            }
            StoreIoError::ByteBudget => {
                config.retained_bytes = 9_000;
                config.job_bytes = 5_000;
            }
            _ => unreachable!(),
        }
        let owner = StoreIoOwner::new(store, config, |_| Ok(())).unwrap();
        let rendezvous = Rendezvous::new(2);
        let (notice, receiver) = mpsc::channel();
        let mut jobs = Vec::new();
        let mut tickets = Vec::new();
        for kind in [StoreIoKind::Read, StoreIoKind::Write] {
            let worker = rendezvous.clone();
            let notice = notice.clone();
            jobs.push(
                owner
                    .submit(kind, 2_000, move |_| {
                        pause(&worker, &notice, vec![0_u8; 2_000]);
                    })
                    .unwrap(),
            );
            tickets.push(ready(&receiver).1);
        }
        let queued = if pressure == StoreIoError::QueueFull {
            Some(owner.submit(StoreIoKind::Write, 0, |_| ()).unwrap())
        } else {
            None
        };
        assert_eq!(
            owner
                .submit(StoreIoKind::Read, 1_000, |_| ())
                .err()
                .unwrap()
                .reason,
            pressure
        );
        let status = owner
            .submit(StoreIoKind::RecoveryRead, 32, |_| {
                std::thread::current().name().unwrap().to_owned()
            })
            .unwrap();
        assert!(wait(status).unwrap().starts_with("latent-store-recovery-"));
        let held = owner.snapshot().unwrap();
        assert_eq!(held.active_reads, 1);
        assert_eq!(held.active_writes, 1);
        assert_eq!(held.recovery_accepted, 0);
        for ticket in tickets {
            rendezvous.release(ticket).unwrap();
        }
        for job in jobs {
            wait(job).unwrap();
        }
        if let Some(job) = queued {
            wait(job).unwrap();
        }
        assert!(finish(&owner).clean);
    }
}

#[test]
fn detached_recovery_owner_keeps_its_partition_until_physical_buffer_retirement() {
    let (store, _, _) = store();
    let mut config = recovery_limits();
    config.recovery.as_mut().unwrap().queued_jobs = 1;
    config.recovery.as_mut().unwrap().accepted_jobs = 2;
    let owner = StoreIoOwner::new(store, config, |_| Ok(())).unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let buffer = Arc::new(vec![0_u8; 512]);
    let weak = Arc::downgrade(&buffer);
    let live = owner
        .submit(StoreIoKind::RecoveryRead, 512, move |_| {
            pause(&worker, &notice, buffer);
        })
        .unwrap();
    let (_, ticket) = ready(&receiver);
    let queued = owner
        .submit(StoreIoKind::RecoveryWrite, 32, |_| 42)
        .unwrap();
    assert_eq!(
        owner
            .submit(StoreIoKind::RecoveryRead, 0, |_| ())
            .err()
            .unwrap()
            .reason,
        StoreIoError::QueueFull
    );
    drop(live);
    assert!(weak.upgrade().is_some());
    let held = owner.snapshot().unwrap();
    assert_eq!(held.recovery_accepted, 2);
    assert!(held.recovery_retained_bytes >= 544);
    assert_eq!(
        wait(owner.submit(StoreIoKind::Read, 0, |_| 7).unwrap()).unwrap(),
        7
    );
    rendezvous.release(ticket).unwrap();
    assert_eq!(wait(queued).unwrap(), 42);
    assert!(finish(&owner).clean);
    assert!(weak.upgrade().is_none());
    assert_eq!(owner.snapshot().unwrap().recovery_retained_bytes, 0);
}

#[test]
fn recovery_write_never_steals_a_live_writer_and_read_can_pass_its_backlog() {
    let (store, writes, _) = store();
    let owner = StoreIoOwner::new(store, recovery_limits(), |_| Ok(())).unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let write = owner
        .submit(StoreIoKind::Write, 32, move |store| {
            pause(&worker, &notice, vec![0_u8; 32]);
            store.writes.fetch_add(1, Ordering::SeqCst);
        })
        .unwrap();
    let (_, ticket) = ready(&receiver);
    let recovery = owner
        .submit(StoreIoKind::RecoveryWrite, 0, |store| {
            store.writes.fetch_add(1, Ordering::SeqCst);
        })
        .unwrap();
    assert_eq!(
        wait(
            owner
                .submit(StoreIoKind::RecoveryRead, 0, |store| store
                    .writes
                    .load(Ordering::SeqCst))
                .unwrap()
        )
        .unwrap(),
        0
    );
    assert_eq!(owner.snapshot().unwrap().active_writes, 1);
    assert_eq!(owner.snapshot().unwrap().recovery_queued, 1);
    drop(recovery);
    let report = wait(
        owner
            .drain_async(Instant::now(), std::future::ready(()))
            .unwrap(),
    );
    assert!(!report.clean && !report.snapshot.physically_retired());
    rendezvous.release(ticket).unwrap();
    wait(write).unwrap();
    let retired = finish(&owner);
    assert!(!retired.clean && retired.snapshot.physically_retired());
    assert_eq!(writes.load(Ordering::SeqCst), 1);
}

#[test]
fn absent_or_invalid_recovery_configuration_cannot_synthesize_reserved_admission() {
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, limits(), |_| Ok(())).unwrap();
    let rejected = owner
        .submit(StoreIoKind::RecoveryRead, 0, |_| {
            panic!("unconfigured recovery ran")
        })
        .err()
        .unwrap();
    assert_eq!(rejected.reason, StoreIoError::RecoveryUnavailable);
    assert_eq!(owner.snapshot().unwrap().accepted, 0);
    assert!(finish(&owner).clean);
    for mode in 0..4 {
        let mut config = recovery_limits();
        match mode {
            0 => config.recovery.as_mut().unwrap().workers = config.workers,
            1 => config.recovery.as_mut().unwrap().retained_bytes = config.retained_bytes,
            2 => config.recovery.as_mut().unwrap().accepted_jobs = 1,
            _ => config.recovery.as_mut().unwrap().job_bytes = 5_000,
        }
        assert_eq!(config.validate(), Err(StoreIoError::InvalidLimits));
    }
}

#[test]
fn blocked_ordinary_native_destructor_cannot_occupy_reserved_recovery_worker() {
    struct Native {
        pause: Rendezvous,
        notice: mpsc::Sender<(Registration, PauseTicket)>,
    }
    impl Drop for Native {
        fn drop(&mut self) {
            pause(&self.pause, &self.notice, vec![0_u8; 256]);
        }
    }
    let (store, _, _) = store();
    let owner = StoreIoOwner::new(store, recovery_limits(), |_| Ok(())).unwrap();
    let rendezvous = Rendezvous::new(2);
    let (notice, receiver) = mpsc::channel();
    let mut native = owner.reserve_retained::<Native>(256).unwrap();
    assert!(native
        .attach(Native {
            pause: rendezvous.clone(),
            notice: notice.clone()
        })
        .is_ok());
    let retired = native.retire();
    let (_, destructor) = ready(&receiver);
    let worker = rendezvous.clone();
    let write = owner
        .submit(StoreIoKind::Write, 32, move |_| {
            pause(&worker, &notice, vec![0_u8; 32]);
        })
        .unwrap();
    let (_, io) = ready(&receiver);
    let status = owner
        .submit(StoreIoKind::RecoveryRead, 0, |_| {
            std::thread::current().name().unwrap().to_owned()
        })
        .unwrap();
    assert!(wait(status).unwrap().starts_with("latent-store-recovery-"));
    assert_eq!(owner.snapshot().unwrap().physical_owners, 1);
    rendezvous.release(destructor).unwrap();
    rendezvous.release(io).unwrap();
    wait(retired);
    wait(write).unwrap();
    assert!(finish(&owner).clean);
}

fn legacy_recovery_limits() -> StoreIoLimits {
    let mut config = limits();
    config.workers = 2;
    config.active_reads = 1;
    config.queued_jobs = 6;
    config.recovery = Some(capacity());
    config
}

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
    let owner = StoreIoOwner::new(store, legacy_recovery_limits(), |_| Ok(())).unwrap();
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
    let owner = StoreIoOwner::new(store, legacy_recovery_limits(), |_| Ok(())).unwrap();
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
    let owner = StoreIoOwner::new(store, legacy_recovery_limits(), |_| Ok(())).unwrap();
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
    let owner = StoreIoOwner::new(store, legacy_recovery_limits(), |_| Ok(())).unwrap();
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
    let owner = StoreIoOwner::new(store, legacy_recovery_limits(), |_| Ok(())).unwrap();
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
