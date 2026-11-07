use super::super::tests::runtime;
use super::*;
use std::sync::mpsc;

#[test]
fn cancelled_runtime_does_not_complete_or_advance_an_admitted_timer() {
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, Some(Duration::from_millis(1)), None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    let before = runtime.snapshot();
    let (checked_tx, checked_rx) = mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let result = wait.complete_with_after_live_check(first, || {
            checked_tx.send(()).unwrap();
            resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        });
        (result, wait)
    });
    checked_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    runtime.cancel();
    resume_tx.send(()).unwrap();
    let (result, wait) = worker.join().unwrap();
    assert_eq!(result.unwrap_err().code, PlatformErrorCode::Cancelled);
    let after = runtime.snapshot();
    assert_eq!(after.phase, super::super::RuntimePhase::Cancelling);
    assert_eq!(after.owners, before.owners);
    assert_eq!(after.host_memory_bytes, before.host_memory_bytes);
    let schedule = timer.inner.schedule.lock().unwrap();
    assert_eq!(schedule.next, Some(first));
    assert!(schedule.waiting);
    drop(schedule);
    drop(wait);
    drop(timer);
    runtime.retire().unwrap();
}

#[test]
fn admitted_timer_can_complete_while_closing_and_draining() {
    for draining in [false, true] {
        let runtime = runtime();
        let first = Instant::now();
        let timer =
            RuntimeTimer::new(&runtime, first, Some(Duration::from_millis(1)), None).unwrap();
        let mut wait = timer.begin_wait().unwrap();
        runtime.close();
        if draining {
            runtime.begin_drain();
        }
        assert_eq!(wait.complete(first).unwrap(), 0);
        let schedule = timer.inner.schedule.lock().unwrap();
        assert_eq!(schedule.next, first.checked_add(Duration::from_millis(1)));
        drop(schedule);
        assert_eq!(
            runtime.snapshot().phase,
            if draining {
                super::super::RuntimePhase::Draining
            } else {
                super::super::RuntimePhase::Closing
            }
        );
        drop(wait);
        drop(timer);
        runtime.retire().unwrap();
    }
}

#[test]
fn closed_timer_retains_its_existing_error_when_close_and_cancel_win() {
    let runtime = runtime();
    let first = Instant::now();
    let timer = RuntimeTimer::new(&runtime, first, None, None).unwrap();
    let mut wait = timer.begin_wait().unwrap();
    let (checked_tx, checked_rx) = mpsc::sync_channel(0);
    let (resume_tx, resume_rx) = mpsc::sync_channel(0);
    let worker = std::thread::spawn(move || {
        let result = wait.complete_with_after_live_check(first, || {
            checked_tx.send(()).unwrap();
            resume_rx.recv_timeout(Duration::from_secs(5)).unwrap();
        });
        (result, wait)
    });
    checked_rx.recv_timeout(Duration::from_secs(5)).unwrap();
    timer.close();
    runtime.cancel();
    resume_tx.send(()).unwrap();
    let (result, wait) = worker.join().unwrap();
    let error = result.unwrap_err();
    assert_eq!(error.code, PlatformErrorCode::Cancelled);
    assert_eq!(error.message, "runtime-timer-closed");
    drop(wait);
    drop(timer);
    runtime.retire().unwrap();
}
