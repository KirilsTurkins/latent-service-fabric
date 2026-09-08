use std::sync::Arc;
use std::time::Duration;

use super::support::*;

#[test]
fn dropped_quiesce_future_keeps_stopping_owner_until_actual_join() {
    let mut pool = pool(&config());
    let observer = pool.observer();
    let (future, _) = waiting(&pool, "running", None);
    let (started, release) = blocked(&pool, &future);
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    drop(pool.quiesce());
    assert!(!observer.snapshot().accepting);
    assert!(complete(future).is_err());
    assert_eq!(pool.core.cache.snapshot().preparing, 1);
    assert!(pool.acquire(input("reopen", None)).is_err());
    release.send(()).unwrap();
    complete(pool.quiesce()).unwrap();
    assert_eq!(observer.snapshot().workers_joined, 0);
    pool.stop_and_join().unwrap();
    let snapshot = observer.snapshot();
    assert_eq!(
        (
            snapshot.workers_live,
            snapshot.workers_quiescent,
            snapshot.workers_joined
        ),
        (0, 2, 2)
    );
    assert_eq!(
        (
            snapshot.ready_preparations,
            snapshot.reserved_document_bytes
        ),
        (0, 0)
    );
}

#[cfg(unix)]
#[test]
fn reentrant_final_owner_abort_is_supervised() {
    use std::future::Future as _;
    use std::pin::Pin;
    use std::sync::Mutex;
    use std::task::{Context, Wake, Waker};

    const SCENARIO: &str = "compiler::tests::teardown::reentrant_final_owner_abort_is_supervised";
    const ENVIRONMENT: &str = "LSF_COMPILER_REENTRANT_TEST";
    const READY: &str = "compiler-reentrant-child-ready";
    if std::env::var(ENVIRONMENT).as_deref() == Ok(SCENARIO) {
        struct FinalOwner(Mutex<Option<Arc<crate::compiler::CompilerPool<u8>>>>);
        impl Wake for FinalOwner {
            fn wake(self: Arc<Self>) {
                drop(self.0.lock().unwrap().take());
            }
        }
        let pool = Arc::new(pool(&config()));
        let (mut future, _) = waiting(&pool, "reentrant", None);
        let (started, release) = blocked(&pool, &future);
        started.recv_timeout(Duration::from_secs(5)).unwrap();
        let waker = Waker::from(Arc::new(FinalOwner(Mutex::new(Some(Arc::clone(&pool))))));
        assert!(Pin::new(&mut future)
            .poll(&mut Context::from_waker(&waker))
            .is_pending());
        drop(waker);
        drop(pool);
        println!("{READY}");
        release.send(()).unwrap();
        // The worker invokes the only remaining pool owner's wake callback.
        let _future = future;
        std::thread::sleep(Duration::from_secs(2));
        panic!("reentrant final destruction must abort this child");
    }
    supervised_abort(SCENARIO, ENVIRONMENT, READY);
}
