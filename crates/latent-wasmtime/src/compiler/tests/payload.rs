use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{mpsc, Arc, Mutex};
use std::time::{Duration, Instant};

use latent_core::ReleaseDigest;

use super::support::*;
use crate::compiler::{Acquisition, CompilationResult, CompilerPool};
use crate::PreparationObserver;

struct PayloadCleanup {
    entered: mpsc::Sender<()>,
    release: mpsc::Receiver<()>,
    completed: Arc<AtomicBool>,
}

impl Drop for PayloadCleanup {
    fn drop(&mut self) {
        let _ = self.entered.send(());
        // A failed test must still release its worker, without a second panic.
        let released = self.release.recv_timeout(Duration::from_secs(5)).is_ok();
        self.completed.store(released, Ordering::Release);
    }
}

struct PayloadOwner(Mutex<Option<PayloadCleanup>>);

fn panic_with_owned_payload(value: &PayloadOwner) -> (usize, usize) {
    let payload = value.0.lock().unwrap().take().unwrap();
    std::panic::panic_any(payload)
}

#[test]
fn unexpected_panic_completion_waits_for_payload_cleanup_past_cutoff() {
    let configuration = config();
    let cache = Arc::new(crate::cache::PreparedCache::new(configuration.cache_limits()).unwrap());
    let mut pool = CompilerPool::new(
        &configuration,
        cache,
        PreparationObserver::new(4),
        panic_with_owned_payload,
    )
    .unwrap();
    let compiler = pool.observer();
    let Acquisition::Waiting { future, .. } = pool.acquire(input("payload", None)).unwrap() else {
        panic!("cold task")
    };
    let (entered_send, entered) = mpsc::channel();
    let (release, released) = mpsc::channel();
    let completed = Arc::new(AtomicBool::new(false));
    let runtime = Arc::new(PayloadOwner(Mutex::new(Some(PayloadCleanup {
        entered: entered_send,
        release: released,
        completed: Arc::clone(&completed),
    }))));
    let observer = pool.core.observer.clone();
    future
        .start(move |reservation| {
            Box::new(move |_queue| {
                Ok(CompilationResult {
                    runtime,
                    reservation: Some(reservation),
                    observation: observer
                        .begin(&ReleaseDigest(format!("sha256:{}", "d".repeat(64)))),
                })
            })
        })
        .unwrap();
    entered.recv_timeout(Duration::from_secs(5)).unwrap();
    assert!(!completed.load(Ordering::Acquire));
    assert!(compiler.last_work_completed_at().is_none());
    let cutoff = Instant::now();
    let quiescence = pool.quiesce();
    assert!(compiler.last_work_completed_at().is_none());
    release.send(()).unwrap();
    complete(quiescence).unwrap();
    assert!(complete(future).is_err());
    assert!(completed.load(Ordering::Acquire));
    assert!(compiler.last_work_completed_at().unwrap() > cutoff);
    assert!(pool.stop_and_join().is_err());
    let snapshot = compiler.snapshot();
    assert!(snapshot.failed);
    assert_eq!(snapshot.workers_joined, 2);
    assert_eq!(
        (
            snapshot.running_jobs,
            snapshot.assigned_jobs,
            snapshot.ready_preparations
        ),
        (0, 0, 0)
    );
    assert_eq!(pool.core.cache.snapshot().preparing, 0);
}

#[cfg(unix)]
#[test]
fn a_second_panic_during_payload_cleanup_aborts_and_is_reaped() {
    const SCENARIO: &str =
        "compiler::tests::payload::a_second_panic_during_payload_cleanup_aborts_and_is_reaped";
    const ENVIRONMENT: &str = "LSF_COMPILER_PAYLOAD_TEST";
    const READY: &str = "compiler-payload-child-ready";
    if std::env::var(ENVIRONMENT).as_deref() == Ok(SCENARIO) {
        struct SecondaryPayload;
        impl Drop for SecondaryPayload {
            fn drop(&mut self) {
                panic!("secondary payload must not be disposed before abort");
            }
        }
        struct PanickingPayload;
        impl Drop for PanickingPayload {
            fn drop(&mut self) {
                std::panic::panic_any(SecondaryPayload);
            }
        }
        let pool = pool(&config());
        let (future, _) = waiting(&pool, "double-panic", None);
        println!("{READY}");
        future
            .start(move |reservation| {
                Box::new(move |_queue| {
                    let _owned = reservation;
                    std::panic::panic_any(PanickingPayload)
                })
            })
            .unwrap();
        let _ = complete(future);
        panic!("panic during payload cleanup must abort this child");
    }
    supervised_abort(SCENARIO, ENVIRONMENT, READY);
}
