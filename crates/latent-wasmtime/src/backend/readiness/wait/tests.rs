use std::cell::Cell;
use std::future::Future;
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use std::task::{Context, Waker};

use latent_core::ErrorDetail;

use super::*;

struct Timer;
impl PreparationReadWait for Timer {
    fn now(&self) -> Instant {
        tokio::time::Instant::now().into_std()
    }
    fn wait_until(&self, deadline: Instant) -> latent_core::BoxFuture<'_, ()> {
        Box::pin(tokio::time::sleep_until(deadline.into()))
    }
}

fn failure(reason: &str) -> PlatformError {
    PlatformError {
        code: PlatformErrorCode::Unavailable,
        message: "unchanged original error allocation".into(),
        retryable: true,
        details: vec![ErrorDetail {
            kind: "admission.currentness".into(),
            fields: [("reason".into(), reason.into())].into(),
        }],
    }
}

#[tokio::test(start_paused = true)]
async fn only_exact_busy_reads_wait_and_other_failures_forward_unchanged() {
    let good = failure("admission-authority-busy");
    assert!(busy(&good));
    let mut errors = vec![];
    for reason in [
        "admission-authority-poisoned",
        "admission-clock-lease-uncovered",
        "admission-clock-regression",
        "admission-verification-busy",
        "signature-stale-proof",
        "compiler-job-capacity",
        "admission-authority-busy ",
    ] {
        errors.push(failure(reason));
    }
    let mut changed = good.clone();
    changed.code = PlatformErrorCode::StateConflict;
    errors.push(changed);
    let mut changed = good.clone();
    changed.retryable = false;
    errors.push(changed);
    let mut changed = good.clone();
    changed.details.clear();
    changed.message = "admission-authority-busy".into();
    errors.push(changed);
    let mut changed = good.clone();
    changed.details.push(changed.details[0].clone());
    errors.push(changed);
    let mut changed = good.clone();
    changed.details[0].kind = "admission.limit".into();
    errors.push(changed);
    let mut changed = good.clone();
    changed.details[0]
        .fields
        .insert("extra".into(), "not allowed".into());
    errors.push(changed);
    let mut changed = good.clone();
    changed.details[0].fields = [("other".into(), "admission-authority-busy".into())].into();
    errors.push(changed);
    for error in errors {
        let expected = error.clone();
        let pointer = error.message.as_ptr();
        let mut original = Some(error);
        let before = tokio::time::Instant::now();
        let actual = Window::new(Some(&Timer))
            .check(|| Err::<(), _>(original.take().unwrap()))
            .await
            .unwrap_err();
        assert_eq!(actual, expected);
        assert_eq!(actual.message.as_ptr(), pointer);
        assert_eq!(tokio::time::Instant::now(), before);
    }
}

#[tokio::test(start_paused = true)]
async fn retry_repeats_only_the_failed_read_and_forwards_one_success_owner() {
    let attempts = Cell::new(0);
    let owned = Arc::new(7);
    let mut owner = Some(Arc::clone(&owned));
    let start = tokio::time::Instant::now();
    let result = Window::new(Some(&Timer))
        .check(|| {
            attempts.set(attempts.get() + 1);
            if attempts.get() == 1 {
                Err(failure("admission-authority-busy"))
            } else {
                Ok(owner.take().unwrap())
            }
        })
        .await
        .unwrap();
    assert_eq!(attempts.get(), 2);
    assert!(Arc::ptr_eq(&result, &owned));
    assert_eq!(
        tokio::time::Instant::now() - start,
        Duration::from_millis(10)
    );
}

#[tokio::test(start_paused = true)]
async fn checkpoints_share_one_window_and_never_retry_after_its_expiry() {
    let window = Window::new(Some(&Timer));
    let first = Cell::new(0);
    window
        .check(|| {
            first.set(first.get() + 1);
            if first.get() == 1 {
                Err(failure("admission-authority-busy"))
            } else {
                Ok(())
            }
        })
        .await
        .unwrap();
    tokio::time::advance(Duration::from_millis(4_985)).await;
    let second = Cell::new(0);
    let error = failure("admission-authority-busy");
    let pointer = error.message.as_ptr();
    let mut original = Some(error);
    let result = window
        .check(|| {
            second.set(second.get() + 1);
            Err::<(), _>(original.take().unwrap())
        })
        .await
        .unwrap_err();
    assert_eq!(second.get(), 1);
    assert_eq!(result.message.as_ptr(), pointer);
    assert_eq!(Some(tokio::time::Instant::now().into_std()), window.until);
    // A long cold compilation must not buy the final checkpoint a new window.
    tokio::time::advance(Duration::from_secs(6)).await;
    let after = tokio::time::Instant::now();
    assert!(window
        .check(|| Err::<(), _>(failure("admission-authority-busy")))
        .await
        .is_err());
    assert_eq!(tokio::time::Instant::now(), after);
    assert_eq!(
        window.check(|| Ok::<_, PlatformError>(17)).await.unwrap(),
        17
    );
}

struct Owner(Arc<AtomicUsize>);
impl Drop for Owner {
    fn drop(&mut self) {
        self.0.fetch_add(1, Ordering::SeqCst);
    }
}

#[tokio::test(start_paused = true)]
async fn dropping_pending_read_wait_releases_owner_without_another_read() {
    let window = Window::new(Some(&Timer));
    let drops = Arc::new(AtomicUsize::new(0));
    let attempts = Arc::new(AtomicUsize::new(0));
    let owner = Owner(Arc::clone(&drops));
    let calls = Arc::clone(&attempts);
    let mut pending = Box::pin(window.check(move || {
        let _retained = &owner;
        calls.fetch_add(1, Ordering::SeqCst);
        Err::<(), _>(failure("admission-authority-busy"))
    }));
    assert!(pending
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()))
        .is_pending());
    assert_eq!(attempts.load(Ordering::SeqCst), 1);
    assert_eq!(drops.load(Ordering::SeqCst), 0);
    drop(pending);
    tokio::time::advance(Duration::from_secs(10)).await;
    assert_eq!(attempts.load(Ordering::SeqCst), 1);
    assert_eq!(drops.load(Ordering::SeqCst), 1);
}

#[test]
fn original_entry_needs_no_executor_and_returns_busy_without_waiting() {
    let window = Window::new(None);
    let mut error = Some(failure("admission-authority-busy"));
    let mut future = Box::pin(window.check(|| Err::<(), _>(error.take().unwrap())));
    let result = future
        .as_mut()
        .poll(&mut Context::from_waker(Waker::noop()));
    assert!(matches!(result, std::task::Poll::Ready(Err(_))));
    drop(future);
    assert!(error.is_none());
}
