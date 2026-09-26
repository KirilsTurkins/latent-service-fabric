use super::*;
use latent_core::{ErrorDetail, PlatformErrorCode};
use std::cell::Cell;
use std::sync::atomic::{AtomicUsize, Ordering};

fn failure(reason: &str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "original owned error".into(),
        retryable: true,
        details: vec![ErrorDetail {
            kind: "admission.currentness".into(),
            fields: [("reason".into(), reason.into())].into(),
        }],
    }
}

#[test]
fn worker_window_retries_only_exact_busy_and_preserves_other_error_allocations() {
    let control = JobControl::new();
    let window = WorkerWindow::new(control);
    let good = failure("admission-authority-busy");
    let mut errors = vec![
        failure("admission-clock-lease-uncovered"),
        failure("signature-stale-proof"),
        failure("compiler-stopping"),
    ];
    let mut changed = good.clone();
    changed.retryable = false;
    errors.push(changed);
    let mut changed = good.clone();
    changed.code = PlatformErrorCode::StateConflict;
    errors.push(changed);
    let mut changed = good.clone();
    changed.details.clear();
    errors.push(changed);
    let mut changed = good.clone();
    changed.details.push(changed.details[0].clone());
    errors.push(changed);
    let mut changed = good.clone();
    changed.details[0]
        .fields
        .insert("extra".into(), "value".into());
    errors.push(changed);
    for error in errors {
        let pointer = error.message.as_ptr();
        let mut original = Some(error);
        let actual = WorkerWindow::check(Some(&window), || Err::<(), _>(original.take().unwrap()))
            .unwrap_err();
        assert_eq!(actual.message.as_ptr(), pointer);
    }
    let calls = Cell::new(0);
    let result = WorkerWindow::check(Some(&window), || {
        calls.set(calls.get() + 1);
        if calls.get() == 1 {
            Err(good.clone())
        } else {
            Ok(7)
        }
    })
    .unwrap();
    assert_eq!((result, calls.get()), (7, 2));
}

#[test]
fn worker_window_is_shared_across_checks_and_never_refreshes_after_expiry() {
    let control = JobControl::new();
    let created = control.created();
    let mut window = WorkerWindow::new(control);
    assert_eq!(window.until, created.checked_add(Duration::from_secs(5)));
    let original_until = window.until;
    assert_eq!(
        WorkerWindow::check(Some(&window), || Ok::<_, PlatformError>(3)).unwrap(),
        3
    );
    assert_eq!(window.until, original_until);
    // Queue/compile elapsed time consumes the existing absolute window.
    window.until = Some(Instant::now() - Duration::from_secs(1));
    let calls = AtomicUsize::new(0);
    for _ in 0..2 {
        assert!(WorkerWindow::check(Some(&window), || {
            calls.fetch_add(1, Ordering::SeqCst);
            Err::<(), _>(failure("admission-authority-busy"))
        })
        .is_err());
    }
    assert_eq!(calls.load(Ordering::SeqCst), 2);
}

#[test]
fn stopped_or_legacy_worker_never_replays_a_failed_currentness_read() {
    let control = JobControl::new();
    let window = WorkerWindow::new(control.clone());
    control.stop();
    for option in [None, Some(&window)] {
        let error = failure("admission-authority-busy");
        let pointer = error.message.as_ptr();
        let mut original = Some(error);
        let actual =
            WorkerWindow::check(option, || Err::<(), _>(original.take().unwrap())).unwrap_err();
        assert_eq!(actual.message.as_ptr(), pointer);
    }
}
