use std::future::Future as _;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Weak};
use std::task::{Context, Wake, Waker};
use std::time::Duration;

use super::support::*;
use crate::compiler::state::{Core, Waiter};
use crate::compiler::ReadyPin;
use crate::PreparationStage;

#[test]
fn queue_window_is_associated_with_the_worker_job_without_claiming_thread_cpu() {
    let mut configuration = config();
    configuration.compiler_workers = Some(1);
    configuration.maximum_concurrent_preparations = 2;
    let pool = pool(&configuration);
    pool.core.observer.enable();
    let (first, _) = waiting(&pool, "first", None);
    let (started, first_release) = blocked(&pool, &first);
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    let (second, _) = waiting(&pool, "second", None);
    let (second_started, second_release) = blocked(&pool, &second);
    assert_eq!(pool.observer().snapshot().queued_jobs, 1);
    let submitted = pool.core.observer.snapshot().observed_nanos;
    first_release.send(()).unwrap();
    drop(complete(first).unwrap());
    second_started.recv_timeout(Duration::from_secs(5)).unwrap();
    second_release.send(()).unwrap();
    drop(complete(second).unwrap());
    idle(&pool);
    let snapshot = pool.core.observer.snapshot();
    let queue: Vec<_> = snapshot
        .recent_stages
        .iter()
        .filter(|record| record.stage == PreparationStage::QueueWait)
        .collect();
    assert_eq!(queue.len(), 2);
    assert!(queue[1].started_nanos <= submitted);
    assert!(queue[1].finished_nanos >= submitted);
    for record in queue {
        assert!(record.thread_cpu.is_none());
        assert!(record.succeeded);
        let whole = snapshot
            .recent_stages
            .iter()
            .find(|whole| {
                whole.job_id == record.job_id && whole.stage == PreparationStage::WholeJob
            })
            .unwrap();
        assert_eq!(whole.component_digest, record.component_digest);
        assert!(whole.started_nanos >= record.finished_nanos);
    }
}

#[test]
fn stopping_drops_already_delivered_ready_result_outside_waiter_and_registry_locks() {
    struct Reentrant {
        core: Weak<Core<u8>>,
        waiter: Weak<Waiter<u8>>,
        woke: AtomicBool,
        unlocked: AtomicBool,
    }
    impl Wake for Reentrant {
        fn wake(self: Arc<Self>) {
            let core = self.core.upgrade().unwrap();
            let waiter = self.waiter.upgrade().unwrap();
            let unlocked = core.state.try_lock().is_ok() && waiter.state.try_lock().is_ok();
            self.unlocked.store(unlocked, Ordering::Release);
            self.woke.store(true, Ordering::Release);
        }
    }
    let pool = pool(&config());
    let (future, _) = waiting(&pool, "stopping", None);
    let (started, release) = blocked(&pool, &future);
    started.recv_timeout(Duration::from_secs(5)).unwrap();
    let waiter = Arc::clone(&pool.core.lock().jobs[0].waiters[0]);
    let permit = waiter.state.lock().unwrap().permit.take().unwrap();
    let pin = ReadyPin {
        runtime: Arc::new(7),
        permit: permit.charge(8, 16).unwrap(),
    };
    waiter.state.lock().unwrap().result = Some(Ok(pin));
    let callbacks = Arc::new(Reentrant {
        core: Arc::downgrade(&pool.core),
        waiter: Arc::downgrade(&waiter),
        woke: AtomicBool::new(false),
        unlocked: AtomicBool::new(false),
    });
    let observer = pool.core.observer.clone();
    let mut changed = observer.wait_for_change(observer.snapshot().revision);
    let waker = Waker::from(Arc::clone(&callbacks));
    assert!(changed
        .as_mut()
        .poll(&mut Context::from_waker(&waker))
        .is_pending());
    drop(pool.quiesce());
    assert!(callbacks.woke.load(Ordering::Acquire));
    assert!(callbacks.unlocked.load(Ordering::Acquire));
    assert!(complete(future).is_err());
    release.send(()).unwrap();
    complete(pool.quiesce()).unwrap();
    assert_eq!(pool.observer().snapshot().ready_preparations, 0);
    assert_eq!(pool.core.cache.snapshot().preparing, 0);
}
