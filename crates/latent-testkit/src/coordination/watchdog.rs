//! A real-clock deadlock watchdog, independent of paused Tokio timers.

use std::future::{poll_fn, Future};
use std::pin::pin;
use std::sync::{mpsc, Arc, Mutex};
use std::task::Waker;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

pub const WATCHDOG: Duration = Duration::from_secs(5);

struct Watchdog {
    cancel: Option<mpsc::Sender<()>>,
    worker: Option<JoinHandle<()>>,
}

impl Drop for Watchdog {
    fn drop(&mut self) {
        // Cancellation, panic and normal completion all reap the watchdog thread.
        self.cancel.take();
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

/// Panics on a real monotonic deadline. This is a deadlock detector, never a
/// readiness signal. It cannot preempt a blocking `Future::poll`; use the test
/// runner's process timeout as the final bound for blocking/native code.
pub async fn with_watchdog<F: Future>(limit: Duration, future: F) -> F::Output {
    let deadline = Instant::now().checked_add(limit).expect("watchdog deadline overflow");
    let wake: Arc<Mutex<Option<Waker>>> = Arc::new(Mutex::new(None));
    let observed = Arc::clone(&wake);
    let (cancel, cancelled) = mpsc::channel();
    let worker = thread::spawn(move || {
        if cancelled.recv_timeout(limit) == Err(mpsc::RecvTimeoutError::Timeout) {
            let waker = observed.lock().unwrap().take();
            if let Some(waker) = waker {
                waker.wake();
            }
        }
    });
    let _watchdog = Watchdog { cancel: Some(cancel), worker: Some(worker) };
    let mut future = pin!(future);
    poll_fn(|cx| {
        *wake.lock().unwrap() = Some(cx.waker().clone());
        assert!(Instant::now() < deadline, "real-clock test watchdog expired");
        future.as_mut().poll(cx)
    }).await
}
