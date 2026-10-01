use super::*;

#[test]
fn deadline_quarantine_retains_live_io_and_late_retirement_is_distinct() {
    let clock = clock();
    let now = clock.monotonic_now();
    let (store, writes, closed) = store();
    let owner =
        StoreIoOwner::with_clock(store, limits(), |_| Ok(()), Arc::new(clock.clone())).unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .submit(StoreIoKind::Write, 32, move |store| {
            pause(&worker, &notice, vec![1_u8; 32]);
            store.writes.fetch_add(1, Ordering::SeqCst);
        })
        .unwrap();
    let (registration, ticket) = ready(&receiver);
    let charge = owner.snapshot().unwrap().retained_bytes;
    let deadline = now + Duration::from_secs(1);
    let mut drain = Box::pin(
        owner
            .drain_async(deadline, clock.sleep_until(deadline))
            .unwrap(),
    );
    let probe = PollProbe::default();
    probe.pending(drain.as_mut());
    assert_eq!(clock.pending_waiters(), 1);
    clock.set_wall_unix_millis(u64::MAX);
    assert!(owner.snapshot().unwrap().admission_closed);
    clock.advance(Duration::from_secs(1));
    let report = probe.ready(drain.as_mut());
    assert!(!report.clean);
    assert!(report.snapshot.quarantined);
    assert_eq!(report.snapshot.retained_bytes, charge);
    assert_eq!(report.snapshot.active_writes, 1);
    assert!(!report.snapshot.physically_retired());
    assert!(!closed.load(Ordering::SeqCst));
    assert_eq!(writes.load(Ordering::SeqCst), 0);
    rendezvous.release(ticket).unwrap();
    wait(job).unwrap();
    let late_deadline = clock.monotonic_now() + Duration::from_secs(1);
    let late = wait(
        owner
            .drain_async(late_deadline, clock.sleep_until(late_deadline))
            .unwrap(),
    );
    assert!(!late.clean);
    assert!(late.snapshot.physically_retired());
    assert!(late.snapshot.quarantined);
    assert_eq!(late.snapshot.retained_bytes, 0);
    assert_eq!(writes.load(Ordering::SeqCst), 1);
    rendezvous.require_retired(registration).unwrap();
    assert!(closed.load(Ordering::SeqCst));
}

#[test]
fn finalizer_is_once_owned_and_engine_stays_open_while_it_is_paused() {
    let clock = clock();
    let now = clock.monotonic_now();
    let (store, _, closed) = store();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let calls = Arc::new(AtomicUsize::new(0));
    let counted = Arc::clone(&calls);
    let (notice, receiver) = mpsc::channel();
    let buffer = Arc::new(vec![5_u8; 32]);
    let weak = Arc::downgrade(&buffer);
    let owner = StoreIoOwner::with_clock(
        store,
        limits(),
        move |_| {
            counted.fetch_add(1, Ordering::SeqCst);
            pause(&worker, &notice, buffer);
            Ok(())
        },
        Arc::new(clock.clone()),
    )
    .unwrap();
    owner.close();
    let (registration, ticket) = ready(&receiver);
    let deadline = now;
    let report = wait(
        owner
            .drain_async(deadline, clock.sleep_until(deadline))
            .unwrap(),
    );
    assert!(!report.clean);
    assert!(report.snapshot.finalizing());
    assert!(!report.snapshot.engine_closed());
    assert!(weak.upgrade().is_some());
    assert!(!closed.load(Ordering::SeqCst));
    rendezvous.release(ticket).unwrap();
    let later = now + Duration::from_secs(1);
    let report = wait(owner.drain_async(later, clock.sleep_until(later)).unwrap());
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    assert!(!report.snapshot.finalizing());
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(weak.upgrade().is_none());
    assert!(closed.load(Ordering::SeqCst));
    rendezvous.require_retired(registration).unwrap();
}

#[test]
fn only_one_drain_waiter_and_dropped_registration_cannot_refund_work() {
    let clock = clock();
    let now = clock.monotonic_now();
    let (store, _, _) = store();
    let owner =
        StoreIoOwner::with_clock(store, limits(), |_| Ok(()), Arc::new(clock.clone())).unwrap();
    let rendezvous = Rendezvous::new(1);
    let worker = rendezvous.clone();
    let (notice, receiver) = mpsc::channel();
    let job = owner
        .submit(StoreIoKind::Write, 32, move |_| {
            pause(&worker, &notice, vec![0_u8; 32]);
        })
        .unwrap();
    let (_, ticket) = ready(&receiver);
    let deadline = now + Duration::from_secs(1);
    let mut first = Box::pin(
        owner
            .drain_async(deadline, clock.sleep_until(deadline))
            .unwrap(),
    );
    PollProbe::default().pending(first.as_mut());
    assert!(matches!(
        owner.drain_async(deadline, clock.sleep_until(deadline)),
        Err(StoreIoError::DrainWaiterBusy)
    ));
    drop(first);
    assert_eq!(clock.pending_waiters(), 0);
    assert_eq!(owner.snapshot().unwrap().active_writes, 1);
    let mut second = Box::pin(
        owner
            .drain_async(deadline, clock.sleep_until(deadline))
            .unwrap(),
    );
    PollProbe::default().pending(second.as_mut());
    rendezvous.release(ticket).unwrap();
    wait(job).unwrap();
    let report = wait(second);
    assert!(report.clean);
    assert_eq!(clock.pending_waiters(), 0);
}

#[test]
fn failed_finalization_is_quarantined_after_physical_engine_close() {
    let (store, _, closed) = store();
    let owner =
        StoreIoOwner::new(store, limits(), |_| Err(StoreIoError::FinalizationFailed)).unwrap();
    let report = finish(&owner);
    assert!(!report.clean);
    assert!(report.snapshot.physically_retired());
    assert!(report.snapshot.quarantined);
    assert_eq!(
        report.snapshot.failure,
        Some(StoreIoError::FinalizationFailed)
    );
    assert!(closed.load(Ordering::SeqCst));
}

#[test]
fn completed_before_deadline_is_clean_even_if_waiter_polls_later() {
    let clock = clock();
    let now = clock.monotonic_now();
    let (store, _, _) = store();
    let owner =
        StoreIoOwner::with_clock(store, limits(), |_| Ok(()), Arc::new(clock.clone())).unwrap();
    let deadline = now + Duration::from_secs(1);
    let drain = owner
        .drain_async(deadline, clock.sleep_until(deadline))
        .unwrap();
    // An independent drain observation establishes actual retirement, without
    // a wall-clock sleep or interpreting a timer as ownership proof.
    let control = Arc::clone(&owner.inner.control);
    let observer = std::future::poll_fn(|cx| {
        let mut state = control.state.lock().unwrap();
        if state.live_workers == 0 {
            return std::task::Poll::Ready(());
        }
        state.drain_waiter.as_mut().unwrap().1 = Some(cx.waker().clone());
        std::task::Poll::Pending
    });
    wait(observer);
    clock.advance(Duration::from_secs(2));
    let report = wait(drain);
    assert!(report.clean);
    assert!(report.snapshot.physically_retired());
}
