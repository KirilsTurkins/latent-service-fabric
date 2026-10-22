//! Actual lifecycle source with explicit admission/return boundaries only.
//! No canonical thread, selected sysroot, executor or signed runtime is proved.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Token {
    generation: u64,
    id: u64,
}
#[path = "../executor_lifecycle.rs"]
mod state;
use state::{Error, Future, Generation, Lifecycle, Worker};

fn token(id: u64) -> Token {
    Token { generation: 1, id }
}
fn worker(pool: &mut Lifecycle, canonical: u32) -> (Generation, Worker) {
    let generation = pool.prepare_generation(1).unwrap();
    let worker = pool.reserve_worker(generation).unwrap();
    pool.worker_started(worker, canonical).unwrap();
    pool.commit_generation(generation).unwrap();
    (generation, worker)
}
fn accepted(pool: &mut Lifecycle, id: u64) -> Future {
    let future = pool.reserve_future().unwrap();
    pool.commit_future(future, token(id), token(id + 1))
        .unwrap();
    future
}
fn complete(pool: &mut Lifecycle, future: Future) {
    pool.dequeued(future).unwrap();
    pool.completed(future).unwrap();
    pool.wake_dropped(future).unwrap();
}
fn returned(pool: &mut Lifecycle, worker: Worker, generation: Generation) {
    assert!(pool.claim_close(worker, generation).unwrap());
    pool.user_tls_drained(worker).unwrap();
    // This explicit test port supplies actual-return proof to the source state
    // machine. It does not infer physical Wasmtime retirement from guest flags.
    pool.frames_exited(worker).unwrap();
}

#[test]
fn actual_worker_start_and_complete_provision_are_required_before_acceptance() {
    let mut pool = Lifecycle::new();
    assert_eq!(pool.reserve_future(), Err(Error::WorkPending));
    let generation = pool.prepare_generation(2).unwrap();
    let first = pool.reserve_worker(generation).unwrap();
    assert_eq!(pool.reserve_future(), Err(Error::Busy));
    assert_eq!(pool.commit_generation(generation), Err(Error::WorkPending));
    pool.worker_started(first, 8).unwrap();
    assert_eq!(pool.commit_generation(generation), Err(Error::WorkPending));
    let second = pool.reserve_worker(generation).unwrap();
    assert_eq!(pool.worker_started(second, 8), Err(Error::State));
    pool.worker_started(second, 9).unwrap();
    pool.commit_generation(generation).unwrap();
    let future = accepted(&mut pool, 10);
    assert_eq!(pool.accepted(), 1);
    complete(&mut pool, future);
    assert_eq!(pool.request_close().unwrap().unwrap().messages, 2);
    returned(&mut pool, first, generation);
    returned(&mut pool, second, generation);
    pool.retire().unwrap();
}

#[test]
fn fallible_admission_reservation_pins_worker_without_accepting_or_losing_work() {
    let mut pool = Lifecycle::new();
    let (generation, w) = worker(&mut pool, 1);
    let reserved = pool.reserve_future().unwrap();
    assert_eq!(pool.accepted(), 0);
    // A broker admission may suspend here. A concurrent close must see the
    // reservation, and resource refusal must roll it back before future Drop.
    assert_eq!(pool.request_close(), Err(Error::WorkPending));
    pool.rollback_future(reserved).unwrap();
    let next = pool.reserve_future().unwrap();
    assert_ne!(next, reserved);
    assert_eq!(
        pool.commit_future(reserved, token(1), token(2)),
        Err(Error::Stale)
    );
    assert_eq!(
        pool.commit_future(next, token(0), token(2)),
        Err(Error::State)
    );
    assert_eq!(
        pool.commit_future(next, token(1), token(1)),
        Err(Error::State)
    );
    pool.rollback_future(next).unwrap();
    pool.request_close().unwrap();
    returned(&mut pool, w, generation);
    pool.retire().unwrap();
}

#[test]
fn independent_pool_state_and_empty_queue_do_not_confuse_unfinished_future() {
    let mut first = Lifecycle::new();
    let mut second = Lifecycle::new();
    let (g1, w1) = worker(&mut first, 1);
    let (g2, w2) = worker(&mut second, 2);
    let pending = accepted(&mut first, 10);
    first.dequeued(pending).unwrap();
    first.waiting(pending).unwrap();
    assert_eq!(first.accepted(), 1);
    assert_eq!(first.request_close(), Err(Error::WorkPending));
    let sibling = accepted(&mut second, 20);
    complete(&mut second, sibling);
    second.request_close().unwrap();
    returned(&mut second, w2, g2);
    second.retire().unwrap();
    assert_eq!(first.accepted(), 1);
    first.reserve_requeue(pending).unwrap();
    first.commit_requeue(pending, token(12)).unwrap();
    complete(&mut first, pending);
    first.request_close().unwrap();
    returned(&mut first, w1, g1);
    first.retire().unwrap();
}

#[test]
fn wake_requeue_is_reserved_before_admission_and_late_generation_never_recreates_task() {
    let mut pool = Lifecycle::new();
    let (generation, w) = worker(&mut pool, 1);
    let future = accepted(&mut pool, 1);
    assert_eq!(pool.dequeued(future).unwrap(), token(2));
    pool.waiting(future).unwrap();
    pool.reserve_requeue(future).unwrap();
    assert_eq!(pool.reserve_requeue(future), Err(Error::State));
    assert_eq!(pool.commit_requeue(future, token(1)), Err(Error::State));
    assert_eq!(pool.request_close(), Err(Error::WorkPending));
    pool.commit_requeue(future, token(3)).unwrap();
    assert_eq!(pool.dequeued(future).unwrap(), token(3));
    assert_eq!(pool.completed(future).unwrap(), token(1));
    assert_eq!(pool.reserve_requeue(future), Err(Error::State));
    assert_eq!(pool.accepted(), 0);
    pool.wake_dropped(future).unwrap();
    let reused = accepted(&mut pool, 4);
    assert_ne!(future, reused);
    assert_eq!(pool.reserve_requeue(future), Err(Error::Stale));
    complete(&mut pool, reused);
    pool.request_close().unwrap();
    returned(&mut pool, w, generation);
    pool.retire().unwrap();
}

#[test]
fn closing_worker_tls_submission_requires_actual_successor_and_old_close_cannot_kill_it() {
    let mut pool = Lifecycle::new();
    let (old, old_worker) = worker(&mut pool, 1);
    let close = pool.request_close().unwrap().unwrap();
    assert_eq!(close.generation, old);
    assert_eq!(pool.reserve_future(), Err(Error::WorkPending));
    let next = pool.prepare_generation(1).unwrap();
    let successor = pool.reserve_worker(next).unwrap();
    assert_eq!(pool.reserve_future(), Err(Error::Busy));
    pool.worker_started(successor, 2).unwrap();
    pool.commit_generation(next).unwrap();
    assert!(!pool.claim_close(successor, close.generation).unwrap());
    assert!(pool.claim_close(old_worker, close.generation).unwrap());
    // This is the actual worker's TLS interval, not an early destructor call.
    let continuation = accepted(&mut pool, 10);
    pool.user_tls_drained(old_worker).unwrap();
    pool.frames_exited(old_worker).unwrap();
    assert_eq!(pool.accepted(), 1);
    assert_eq!(pool.request_close(), Err(Error::WorkPending));
    complete(&mut pool, continuation);
    pool.request_close().unwrap();
    returned(&mut pool, successor, next);
    pool.retire().unwrap();
}

#[test]
fn logical_empty_still_waits_for_real_wake_drop_tls_and_frame_boundaries() {
    let mut pool = Lifecycle::new();
    let (generation, w) = worker(&mut pool, 1);
    let future = accepted(&mut pool, 1);
    pool.dequeued(future).unwrap();
    pool.completed(future).unwrap();
    assert_eq!(pool.accepted(), 0);
    pool.request_close().unwrap();
    assert_eq!(pool.frames_exited(w), Err(Error::State));
    assert!(pool.claim_close(w, generation).unwrap());
    assert_eq!(pool.frames_exited(w), Err(Error::State));
    pool.user_tls_drained(w).unwrap();
    assert_eq!(pool.retire(), Err(Error::WorkPending));
    pool.frames_exited(w).unwrap();
    assert_eq!(pool.retire(), Err(Error::WorkPending));
    pool.wake_dropped(future).unwrap();
    pool.retire().unwrap();
    assert_eq!(pool.reserve_future(), Err(Error::Closed));
    assert_eq!(pool.prepare_generation(1), Err(Error::Closed));
}

#[test]
fn partially_started_generation_retains_started_worker_until_its_real_exit() {
    let mut pool = Lifecycle::new();
    let generation = pool.prepare_generation(2).unwrap();
    let live = pool.reserve_worker(generation).unwrap();
    pool.worker_started(live, 1).unwrap();
    let unstarted = pool.reserve_worker(generation).unwrap();
    // The second actual native admission failed. Its port rolls back owners
    // and unstarted allocation; no callback was run for that reserved slot.
    let close = pool.abort_generation(generation).unwrap();
    assert_eq!(close.messages, 1);
    assert_eq!(pool.worker_started(unstarted, 2), Err(Error::Stale));
    assert_eq!(pool.reserve_future(), Err(Error::WorkPending));
    assert_eq!(pool.retire(), Err(Error::WorkPending));
    returned(&mut pool, live, generation);
    pool.retire().unwrap();
}

#[test]
fn finite_close_round_limit_refuses_before_an_unclosable_successor_or_future_is_accepted() {
    let mut pool = Lifecycle::new();
    for index in 0..4 {
        let (generation, w) = worker(&mut pool, index);
        let f = accepted(&mut pool, 10 + u64::from(index) * 2);
        complete(&mut pool, f);
        pool.request_close().unwrap();
        returned(&mut pool, w, generation);
    }
    assert_eq!(pool.prepare_generation(1), Err(Error::Capacity));
    assert_eq!(pool.reserve_future(), Err(Error::WorkPending));
    pool.retire().unwrap();
}
